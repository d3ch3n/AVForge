"""Evidence-aware, manufacturer-agnostic identity resolution."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse


def _norm(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def _same(left: str | None, right: str | None) -> bool:
    return bool(left and right and (_norm(left) == _norm(right) or _norm(left) in _norm(right) or _norm(right) in _norm(left)))


def _contains_exact_phrase(text: str, phrase: str) -> bool:
    words, wanted = _norm(text).split(), _norm(phrase).split()
    return bool(wanted) and any(words[index:index + len(wanted)] == wanted for index in range(len(words) - len(wanted) + 1))


def _source_identity_match(source: dict[str, Any], manufacturer: str | None, model: str | None) -> bool:
    metadata = source.get("metadata", {})
    if not isinstance(metadata, dict):
        return False
    title = str(metadata.get("title", ""))
    meta = metadata.get("meta", {})
    values = " ".join(str(value) for value in meta.values()) if isinstance(meta, dict) else ""
    return _contains_exact_phrase(title, model or "") and _contains_exact_phrase(f"{title} {values}", manufacturer or "")


def resolve_identity(item: dict[str, Any], candidates: list[dict[str, Any]], sources: list[dict[str, Any]]) -> dict[str, Any]:
    official = [source for source in sources if source.get("canonicality") == "official-canonical"]
    claims: list[dict[str, Any]] = []
    source_by_url = {source.get("requested_url"): source for source in official}
    for candidate in candidates:
        source = source_by_url.get(candidate.get("url"))
        if not source:
            continue
        if not _source_identity_match(source, item.get("manufacturer"), item.get("model")):
            continue
        if candidate.get("claimed_model") and not _same(candidate.get("claimed_model"), item.get("model")):
            continue
        claims.append({
            "manufacturer": item.get("manufacturer"),
            "canonical_model": item.get("model"),
            "product_family": candidate.get("product_family"),
            "variant": candidate.get("variant"),
            "official_domain": candidate.get("official_domain") or (urlparse(source.get("final_url", "")).hostname or ""),
            "official_product_url": source.get("final_url"),
            "identity_evidence": [source.get("source_id")],
        })
    if not claims:
        return {"identity_status": "IDENTITY_AMBIGUOUS", "reason": "no acquired official source established exact identity", "evidence_refs": []}
    models = {claim["canonical_model"] for claim in claims if claim.get("canonical_model")}
    manufacturers = {claim["manufacturer"] for claim in claims if claim.get("manufacturer")}
    variants = {_norm(claim.get("variant")) for claim in claims if claim.get("variant")}
    families = {_norm(claim.get("product_family")) for claim in claims if claim.get("product_family")}
    if len({_norm(model) for model in models}) > 1 or len({_norm(manufacturer) for manufacturer in manufacturers}) > 1 or len(variants) > 1 or len(families) > 1:
        return {"identity_status": "IDENTITY_AMBIGUOUS", "reason": "official sources disagree on manufacturer or model", "claims": claims, "evidence_refs": [ref for claim in claims for ref in claim["identity_evidence"]]}
    claim = claims[0]
    if item.get("manufacturer") and not _same(item["manufacturer"], claim.get("manufacturer")):
        return {"identity_status": "IDENTITY_AMBIGUOUS", "reason": "official source manufacturer does not match intake", "claims": claims, "evidence_refs": claim["identity_evidence"]}
    if item.get("model") and not _same(item["model"], claim.get("canonical_model")):
        return {"identity_status": "IDENTITY_AMBIGUOUS", "reason": "official source model does not match intake", "claims": claims, "evidence_refs": claim["identity_evidence"]}
    return {"manufacturer": claim.get("manufacturer"), "canonical_manufacturer": claim.get("manufacturer"), "canonical_model": claim.get("canonical_model"), "product_family": claim.get("product_family"), "variant": claim.get("variant"), "official_domain": claim.get("official_domain"), "official_product_url": claim.get("official_product_url"), "identity_evidence": claim.get("identity_evidence", []), "identity_status": "RESOLVED"}
