"""Small, auditable manufacturer ownership registry.

The registry contains trust roots only. It deliberately has no equipment,
model, capability, or technical specification data.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse


TRUST_STATES = {"UNVERIFIED", "PROPOSED", "VERIFIED"}
_FORBIDDEN_KEYS = {"model", "equipment", "facts", "specifications", "technical_specs", "capabilities"}


def _normal(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.lower()).split())


def _host(value: str) -> str:
    return normalize_host(value) or ""


def normalize_host(value: str | None) -> str | None:
    """Normalize a configured URL/host without broadening trust."""
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = value.strip()
    parsed = urlparse(candidate if "://" in candidate else f"https://{candidate}")
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        return None
    try:
        port = parsed.port
    except ValueError:
        return None
    host = parsed.hostname.lower().rstrip(".")
    if not host or ".." in host or not re.fullmatch(r"[a-z0-9.-]+", host):
        return None
    return f"{host}:{port}" if port is not None else host


def host_matches(candidate: str | None, configured: str | None) -> bool:
    """Match exact hosts or DNS-label subdomains of a configured root."""
    candidate_host = normalize_host(candidate)
    configured_host = normalize_host(configured)
    if not candidate_host or not configured_host:
        return False
    if candidate_host == configured_host:
        return True
    if ":" in configured_host:
        return False
    return candidate_host.endswith("." + configured_host)


def manufacturer_id(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not slug:
        raise ValueError("manufacturer name cannot produce an ID")
    return f"manufacturer.{slug}"


def _validate_entry(entry: dict[str, Any]) -> None:
    required = {"manufacturer_id", "canonical_name", "aliases", "official_web_roots", "approved_document_hosts", "trust"}
    if set(entry) != required:
        raise ValueError("manufacturer registry entry has an invalid shape")
    if not isinstance(entry["manufacturer_id"], str) or not entry["manufacturer_id"].startswith("manufacturer."):
        raise ValueError("manufacturer_id is invalid")
    if not isinstance(entry["canonical_name"], str) or not entry["canonical_name"].strip():
        raise ValueError("canonical_name is required")
    for key in ("aliases", "official_web_roots", "approved_document_hosts"):
        if not isinstance(entry[key], list) or not all(isinstance(value, str) and value.strip() for value in entry[key]):
            raise ValueError(f"{key} must be a list of strings")
    trust = entry["trust"]
    if not isinstance(trust, dict) or set(trust) != {"status", "provenance"}:
        raise ValueError("trust must contain status and provenance")
    if trust["status"] not in TRUST_STATES or not isinstance(trust["provenance"], list):
        raise ValueError("trust state is invalid")
    if any(key.lower() in _FORBIDDEN_KEYS for key in entry):
        raise ValueError("manufacturer registry cannot contain equipment data")


class ManufacturerRegistry:
    def __init__(self, manufacturers: Iterable[dict[str, Any]] = ()) -> None:
        self._entries = [copy.deepcopy(entry) for entry in manufacturers]
        for entry in self._entries:
            _validate_entry(entry)
        ids = [entry["manufacturer_id"] for entry in self._entries]
        names = [_normal(entry["canonical_name"]) for entry in self._entries]
        if len(ids) != len(set(ids)) or len(names) != len(set(names)):
            raise ValueError("manufacturer registry contains duplicates")

    @classmethod
    def empty(cls) -> "ManufacturerRegistry":
        return cls()

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ManufacturerRegistry":
        if value.get("registry_version") != "1.0" or not isinstance(value.get("manufacturers"), list):
            raise ValueError("manufacturer registry requires registry_version 1.0 and manufacturers")
        return cls(value["manufacturers"])

    @classmethod
    def from_file(cls, path: Path) -> "ManufacturerRegistry":
        if not path.exists():
            return cls.empty()
        return cls.from_dict(json.loads(path.read_text()))

    def to_dict(self) -> dict[str, Any]:
        entries = sorted(copy.deepcopy(self._entries), key=lambda entry: entry["manufacturer_id"])
        for entry in entries:
            entry["aliases"] = sorted(entry["aliases"], key=_normal)
            entry["official_web_roots"] = sorted(entry["official_web_roots"], key=_host)
            entry["approved_document_hosts"] = sorted(entry["approved_document_hosts"], key=_host)
        return {"registry_version": "1.0", "manufacturers": entries}

    def serialize(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"

    def lookup(self, name: str | None) -> dict[str, Any] | None:
        if not name:
            return None
        wanted = _normal(name)
        for entry in self._entries:
            if wanted == _normal(entry["canonical_name"]) or wanted in {_normal(alias) for alias in entry["aliases"]}:
                return copy.deepcopy(entry)
        return None

    def verified(self, name: str | None) -> dict[str, Any] | None:
        entry = self.lookup(name)
        return entry if entry and entry["trust"]["status"] == "VERIFIED" else None

    def propose(self, name: str, roots: Iterable[str], evidence_refs: Iterable[str]) -> dict[str, Any]:
        existing = self.lookup(name)
        return {
            "manufacturer_id": existing["manufacturer_id"] if existing else manufacturer_id(name),
            "canonical_name": existing["canonical_name"] if existing else name,
            "aliases": existing["aliases"] if existing else [],
            "official_web_roots": sorted({_host(root) for root in roots if _host(root)}),
            "approved_document_hosts": existing["approved_document_hosts"] if existing else [],
            "trust": {"status": "PROPOSED", "provenance": sorted(set(evidence_refs))},
        }

    def approve_proposal(self, entry: dict[str, Any], reviewer: str, evidence_ref: str) -> dict[str, Any]:
        _validate_entry(entry)
        if entry["trust"]["status"] != "PROPOSED" or not reviewer.strip():
            raise ValueError("only a proposed entry can be explicitly approved")
        approved = copy.deepcopy(entry)
        approved["trust"] = {
            "status": "VERIFIED",
            "provenance": sorted(set(approved["trust"]["provenance"] + [f"review:{reviewer}", evidence_ref])),
        }
        return approved


def assess_manufacturer(item: dict[str, Any], candidates: list[dict[str, Any]], sources: list[dict[str, Any]], registry: ManufacturerRegistry) -> dict[str, Any]:
    known = registry.lookup(item.get("manufacturer"))
    if known and known["trust"]["status"] == "VERIFIED":
        return {"status": "VERIFIED", "manufacturer_id": known["manufacturer_id"], "entry": known, "evidence_refs": known["trust"]["provenance"]}
    if known and known["trust"]["status"] == "PROPOSED":
        return {"status": "PROPOSED", "manufacturer_id": known["manufacturer_id"], "entry": known, "evidence_refs": known["trust"]["provenance"]}
    manufacturer = _normal(item.get("manufacturer", ""))
    model = _normal(item.get("model", ""))
    roots: set[str] = set()
    evidence: list[str] = []
    for source in sources:
        metadata = source.get("metadata", {})
        title = _normal(metadata.get("title", "")) if isinstance(metadata, dict) else ""
        meta_values = " ".join(_normal(str(value)) for value in (metadata.get("meta", {}) if isinstance(metadata, dict) else {}).values())
        if manufacturer and model and manufacturer in f"{title} {meta_values}" and model in title:
            roots.add(_host(source.get("final_url", "")))
            evidence.append(source["source_id"])
    proposal = registry.propose(item["manufacturer"], roots, evidence) if evidence else None
    return {"status": "PROPOSED" if proposal else "UNVERIFIED", "manufacturer_id": proposal["manufacturer_id"] if proposal else manufacturer_id(item["manufacturer"]), "entry": proposal, "evidence_refs": evidence}
