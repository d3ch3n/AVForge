"""Phase 3 identity, discovery, acquisition, classification, and manifest flow."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .acquisition import UrllibFetcher, acquire_candidate
from .discovery import DiscoveryCandidate, DiscoveryProvider, discover, discover_linked_sources
from .identity import resolve_identity
from .manufacturer_registry import ManufacturerRegistry, assess_manufacturer, host_matches, normalize_host

TIER_ONE_CLASSES = {"official_product_page", "official_datasheet", "official_manual", "official_protocol", "official_ae", "official_technical_help"}
TIER_TWO_CLASSES = {"official_support", "official_release_notes", "official_other"}
THIRD_PARTY_CLASS = "third-party-corroboration"


def _normal(value: str | None) -> str:
    return " ".join((value or "").lower().replace("-", " ").split())


def _trust_transition(item: dict[str, Any], candidate: DiscoveryCandidate, source: dict[str, Any]) -> list[str]:
    transition = ["DISCOVERED_CANDIDATE"]
    title = _normal(source.get("metadata", {}).get("title"))
    manufacturer = _normal(candidate.claimed_manufacturer or item.get("manufacturer"))
    model = _normal(candidate.claimed_model or item.get("model"))
    if manufacturer and model and manufacturer in title and model in title:
        transition.append("IDENTITY_MATCH_CANDIDATE")
    if source.get("canonicality") == "official-canonical":
        transition.extend(("OFFICIAL_DOMAIN_CANDIDATE", "VERIFIED_OFFICIAL_DOMAIN"))
    return transition


def classify_source(source: dict[str, Any], candidate: DiscoveryCandidate, item: dict[str, Any] | None = None) -> dict[str, Any]:
    hint = candidate.source_class_hint
    trusted = source.get("canonicality") == "official-canonical"
    if candidate.trust_basis == "authorized_third_party":
        source_class = THIRD_PARTY_CLASS
    elif not trusted:
        source_class = "discovery-only"
    elif hint in TIER_ONE_CLASSES:
        source_class = hint
    elif hint in TIER_TWO_CLASSES:
        source_class = hint
    elif trusted and source.get("source_type") == "html":
        source_class = "official_product_page"
    elif trusted:
        source_class = "official_other"
    else:
        source_class = "discovery-only"
    if source_class in TIER_ONE_CLASSES and trusted:
        source["tier"], source["canonicality"] = 1, "official-canonical"
    elif source_class in TIER_TWO_CLASSES and trusted:
        source["tier"], source["canonicality"] = 2, "official-canonical"
    elif candidate.trust_basis == "authorized_third_party":
        source["tier"], source["canonicality"] = 3, "approved-third-party"
    elif not trusted:
        source["tier"], source["canonicality"] = 4, "discovery-only"
    source["source_class"] = source_class
    source["trust_transition"] = _trust_transition(item or {}, candidate, source)
    if trusted:
        source["verified_official_domain"] = candidate.official_domain or source.get("final_url", "").split("/", 3)[2]
        source["approved_document_hosts"] = list(candidate.approved_hosts)
    return source


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _semantic(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _semantic(item) for key, item in sorted(value.items()) if key not in {"retrieved_at", "discovered_at", "generated_at", "manifest_path"}}
    if isinstance(value, list):
        values = [_semantic(item) for item in value]
        if all(isinstance(item, dict) for item in values):
            values.sort(key=lambda item: item.get("source_id") or item.get("url") or item.get("code") or "")
        return values
    return value


def compare_manifests(previous: dict[str, Any], current: dict[str, Any]) -> str:
    old = json.dumps(_semantic(previous), sort_keys=True, separators=(",", ":"))
    new = json.dumps(_semantic(current), sort_keys=True, separators=(",", ":"))
    return "NO_CHANGE" if old == new else "SOURCE_UPDATED"


def run_source_pipeline(
    item: dict[str, Any],
    *,
    root: Path,
    providers: Iterable[DiscoveryProvider] = (),
    fetcher: Any | None = None,
    timeout: float = 20.0,
    max_redirects: int = 5,
    max_bytes: int = 25 * 1024 * 1024,
    observed_at: str | None = None,
    registry: ManufacturerRegistry | None = None,
) -> dict[str, Any]:
    observed_at = observed_at or _now()
    registry = registry or ManufacturerRegistry.empty()
    if not item.get("manufacturer"):
        manifest = {
            "contract_version": "1.0",
            "job_id": item["job_id"],
            "pipeline_status": "BLOCKED",
            "identity": {"identity_status": "IDENTITY_AMBIGUOUS", "reason": "manufacturer is required for normal automated discovery", "evidence_refs": []},
            "manufacturer_trust": {"status": "UNVERIFIED", "reason": "manufacturer missing from intake"},
            "candidates": [],
            "sources": [],
            "failures": [{"code": "MANUFACTURER_REQUIRED", "message": "normal automated discovery requires manufacturer and model"}],
            "generated_at": observed_at,
        }
        return _write_manifest(manifest, item, root)
    registry_entry = registry.lookup(item["manufacturer"])
    discovery_item = dict(item)
    discovery_item["_official_web_roots"] = registry_entry["official_web_roots"] if registry_entry and registry_entry["trust"]["status"] == "VERIFIED" else []
    candidates, failures = discover(discovery_item, providers, discovered_at=observed_at)
    candidates = _apply_registry_scope(candidates, registry_entry)
    manifest_candidates = list(candidates)
    if not candidates and not providers and not item.get("official_url"):
        failures.append({"code": "DISCOVERY_PROVIDER_UNAVAILABLE", "message": "no discovery provider was supplied"})
    elif not candidates:
        failures.append({"code": "SOURCE_NOT_FOUND", "message": "discovery providers returned no candidates"})
    fetch = fetcher or UrllibFetcher()
    sources: list[dict[str, Any]] = []
    acquired_failures = list(failures)
    url_hashes: dict[str, str] = {}
    source_ids: set[str] = set()
    processed_candidates: set[tuple[str, str]] = set()
    pending = list(candidates)
    link_depth = 0
    while pending and link_depth <= 1:
        current = pending
        pending = []
        for candidate in current:
            candidate_key = (candidate.url, candidate.discovery_method)
            if candidate_key in processed_candidates:
                continue
            processed_candidates.add(candidate_key)
            result = acquire_candidate(candidate, fetch, root / ".ingestion", timeout=timeout, max_redirects=max_redirects, max_bytes=max_bytes, retrieved_at=observed_at)
            if result["status"] != "ACQUIRED":
                acquired_failures.append({**result["failure"], "candidate": candidate.to_dict()})
                continue
            source = classify_source(result["source"], candidate, item)
            if source["source_id"] in source_ids:
                acquired_failures.append({"code": "DUPLICATE_SOURCE", "url": candidate.url, "source_id": source["source_id"]})
                continue
            source_ids.add(source["source_id"])
            prior_hash = url_hashes.get(candidate.url)
            if prior_hash and prior_hash != source["content_hash"]:
                acquired_failures.append({"code": "URL_CONTENT_CHANGED", "url": candidate.url, "previous_hash": prior_hash, "content_hash": source["content_hash"]})
            url_hashes[candidate.url] = source["content_hash"]
            sources.append(source)
            if source.get("canonicality") == "official-canonical":
                linked = discover_linked_sources(source)
                pending.extend(linked)
                manifest_candidates.extend(linked)
        link_depth += 1
    identity = resolve_identity(item, [candidate.to_dict() for candidate in candidates], sources)
    manufacturer_trust = assess_manufacturer(item, [candidate.to_dict() for candidate in candidates], sources, registry)
    manifest = {
        "contract_version": "1.0",
        "job_id": item["job_id"],
        "pipeline_status": "COMPLETED" if candidates and sources else "BLOCKED",
        "identity": identity,
        "manufacturer_trust": manufacturer_trust,
        "candidates": [candidate.to_dict() for candidate in manifest_candidates],
        "sources": sources,
        "failures": acquired_failures,
        "generated_at": observed_at,
    }
    return _write_manifest(manifest, item, root)


def _apply_registry_scope(candidates: list[DiscoveryCandidate], entry: dict[str, Any] | None) -> list[DiscoveryCandidate]:
    if not entry or entry["trust"]["status"] != "VERIFIED":
        return candidates
    roots = tuple(entry["official_web_roots"])
    hosts = tuple(entry["approved_document_hosts"])
    scoped: list[DiscoveryCandidate] = []
    for candidate in candidates:
        root = next((root for root in roots if host_matches(candidate.url, root)), None)
        if root:
            candidate = replace(candidate, official_domain=root, approved_hosts=hosts, trust_basis="manufacturer_domain")
        elif normalize_host(candidate.url) in {normalize_host(host_value) for host_value in hosts}:
            candidate = replace(candidate, official_domain=roots[0] if roots else None, approved_hosts=hosts, trust_basis="approved_host")
        scoped.append(candidate)
    return scoped


def _write_manifest(manifest: dict[str, Any], item: dict[str, Any], root: Path) -> dict[str, Any]:
    manifest["semantic_hash"] = "sha256:" + hashlib.sha256(json.dumps(_semantic(manifest), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    manifest_dir = root / ".ingestion" / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    base_path = manifest_dir / f"{item['job_id']}.json"
    if base_path.exists():
        previous = json.loads(base_path.read_text())
        manifest_path = base_path if compare_manifests(previous, manifest) == "NO_CHANGE" else manifest_dir / f"{item['job_id']}.{manifest['semantic_hash'].split(':', 1)[1][:20]}.json"
    else:
        manifest_path = base_path
    if not manifest_path.exists():
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    manifest["manifest_path"] = str(manifest_path)
    return manifest
