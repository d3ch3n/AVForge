"""Deterministic JSON and CSV intake parsing."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
from typing import Any, Iterable

ALLOWED_FIELDS = {"manufacturer", "model", "product_family", "official_url", "local_sources", "notes", "equipment"}


class IntakeError(ValueError):
    """A structurally invalid intake document."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _text(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise IntakeError("INVALID_INTAKE", f"{field} must be a string")
    value = " ".join(value.split())
    return value or None


def _item(raw: dict[str, Any], position: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise IntakeError("INVALID_INTAKE", f"item {position} must be an object")
    unknown = set(raw) - ALLOWED_FIELDS
    if unknown:
        raise IntakeError("INVALID_INTAKE", f"item {position} has unsupported fields: {sorted(unknown)}")
    manufacturer = _text(raw.get("manufacturer"), "manufacturer")
    model = _text(raw.get("model") or raw.get("equipment"), "model")
    if not model:
        raise IntakeError("INVALID_INTAKE", f"item {position} requires model or equipment")
    local_sources = raw.get("local_sources", [])
    if isinstance(local_sources, str):
        local_sources = [local_sources]
    if not isinstance(local_sources, list) or not all(isinstance(path, str) and path.strip() for path in local_sources):
        raise IntakeError("INVALID_INTAKE", f"item {position}.local_sources must be a list of paths")
    item = {"manufacturer": manufacturer, "model": model, "intake_status": "VALID_NORMAL" if manufacturer else "UNRESOLVED_MANUFACTURER", "automated_discovery_eligible": bool(manufacturer), "product_family": _text(raw.get("product_family"), "product_family"), "official_url": _text(raw.get("official_url"), "official_url"), "local_sources": [" ".join(path.split()) for path in local_sources], "notes": _text(raw.get("notes"), "notes"), "original": {key: raw[key] for key in raw}, "batch_index": position}
    item["job_id"] = _job_id(item)
    return item


def _job_id(item: dict[str, Any]) -> str:
    identity = {key: item[key] for key in ("manufacturer", "model", "product_family", "official_url", "local_sources", "notes")}
    payload = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return "job-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def _finish(raw_items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    items = [_item(raw, position) for position, raw in enumerate(raw_items)]
    fingerprints = [json.dumps({key: value for key, value in item.items() if key not in {"job_id", "original", "batch_index"}}, sort_keys=True, separators=(",", ":")) for item in items]
    if len(fingerprints) != len(set(fingerprints)):
        raise IntakeError("DUPLICATE_ITEM", "duplicate exact intake item")
    return items


def parse_json(value: str | Path | dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        document = value
    else:
        try:
            path = Path(value)
            document = json.loads(path.read_text() if path.exists() else str(value))
        except (OSError, json.JSONDecodeError) as exc:
            raise IntakeError("INVALID_INTAKE", f"invalid JSON intake: {exc}") from exc
    if not isinstance(document, dict) or document.get("contract_version") != "1.0" or not isinstance(document.get("items"), list):
        raise IntakeError("INVALID_INTAKE", "JSON intake requires contract_version 1.0 and items array")
    return _finish(document["items"])


def parse_csv(value: str | Path) -> list[dict[str, Any]]:
    try:
        path = Path(value)
        text = path.read_text() if path.exists() else str(value)
        rows = list(csv.DictReader(io.StringIO(text)))
    except (OSError, csv.Error) as exc:
        raise IntakeError("INVALID_INTAKE", f"invalid CSV intake: {exc}") from exc
    if not rows or not rows[0]:
        raise IntakeError("INVALID_INTAKE", "CSV intake requires a header and at least one row")
    headers = {header.strip() for header in rows[0] if header is not None}
    if not headers.intersection({"model", "equipment"}):
        raise IntakeError("INVALID_INTAKE", "CSV intake requires model or equipment column")
    return _finish([{key.strip(): value for key, value in row.items() if key is not None} for row in rows])
