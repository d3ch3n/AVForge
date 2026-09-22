"""Bounded HTTP acquisition and immutable runtime source artifacts."""

from __future__ import annotations

import hashlib
import html
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from .discovery import DiscoveryCandidate


DEFAULT_TIMEOUT = 20.0
DEFAULT_MAX_REDIRECTS = 5
DEFAULT_MAX_BYTES = 25 * 1024 * 1024


@dataclass(frozen=True)
class FetchResponse:
    status: int
    headers: dict[str, str]
    body: bytes
    final_url: str
    redirect_chain: tuple[str, ...] = ()


class RedirectLimitError(RuntimeError):
    pass


class _TrackingRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, max_redirects: int) -> None:
        super().__init__()
        self.max_redirects = max_redirects
        self.chain: list[str] = []

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.chain.append(newurl)
        if len(self.chain) > self.max_redirects:
            raise RedirectLimitError("maximum redirect count exceeded")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class UrllibFetcher:
    """The only live-network component in this phase."""

    def __call__(self, url: str, *, timeout: float, max_redirects: int, max_bytes: int) -> FetchResponse:
        redirects = _TrackingRedirectHandler(max_redirects)
        opener = urllib.request.build_opener(redirects)
        request = urllib.request.Request(url, headers={"User-Agent": "AVForge-Catalog-Ingestion/1.0"})
        with opener.open(request, timeout=timeout) as response:
            body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise ValueError("maximum download size exceeded")
            headers = {key.lower(): value for key, value in response.headers.items()}
            return FetchResponse(response.status, headers, body, response.geturl(), tuple(redirects.chain))


class _MetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self._in_title = False
        self.meta: dict[str, str] = {}
        self.links: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value or "" for key, value in attrs}
        if tag.lower() == "title":
            self._in_title = True
        if tag.lower() == "meta":
            key = values.get("name") or values.get("property")
            if key and values.get("content"):
                self.meta[key.lower()] = values["content"].strip()
        if tag.lower() == "link" and values.get("href"):
            self.links.append({"url": values["href"], "text": values.get("rel", "")})
        if tag.lower() == "a" and values.get("href"):
            self.links.append({"url": values["href"], "text": ""})

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data.strip()
        elif self.links and not self.links[-1].get("text"):
            self.links[-1]["text"] = data.strip()


def _header(headers: dict[str, str], name: str) -> str:
    return headers.get(name.lower(), "").split(";", 1)[0].strip().lower()


def detect_source_type(body: bytes, declared_type: str, url: str) -> tuple[str | None, str | None]:
    if body.startswith(b"%PDF-"):
        return "pdf", None
    sample = body[:4096].lstrip().lower()
    if b"<html" in sample or b"<!doctype html" in sample or re.search(br"<title[ >]", sample):
        if declared_type == "application/pdf" or urlparse(url).path.lower().endswith(".pdf"):
            return "html", "CONTENT_TYPE_MISMATCH"
        return "html", None
    if declared_type == "text/html":
        return "html", None
    return None, "UNSUPPORTED_TYPE"


def _safe_extension(source_type: str) -> str:
    return ".pdf" if source_type == "pdf" else ".html"


def _trusted_host(candidate: DiscoveryCandidate, url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    official = (candidate.official_domain or "").lower().removeprefix("https://").removeprefix("http://").split("/", 1)[0]
    approved = {value.lower().split("://")[-1].split("/", 1)[0] for value in candidate.approved_hosts}
    if candidate.trust_basis == "provider_verified_domain" and (candidate.provider_metadata or {}).get("verification") != "provider_domain_assertion":
        return False
    return bool(candidate.trust_basis in {"manufacturer_domain", "manufacturer_link", "approved_host", "provider_verified_domain"} and ((official and (host == official or host.endswith("." + official))) or host in approved))


def _metadata(body: bytes, source_type: str, candidate: DiscoveryCandidate) -> dict[str, Any]:
    metadata: dict[str, Any] = {"title": candidate.claimed_title}
    if source_type == "html":
        parser = _MetadataParser()
        parser.feed(body.decode("utf-8", errors="replace"))
        metadata["title"] = parser.title or parser.meta.get("og:title") or parser.meta.get("twitter:title") or candidate.claimed_title
        metadata["meta"] = parser.meta
        metadata["links"] = parser.links
        if parser.meta.get("canonical"):
            metadata["canonical_url"] = parser.meta["canonical"]
    return {key: value for key, value in metadata.items() if value}


def acquire_candidate(
    candidate: DiscoveryCandidate,
    fetcher: Callable[..., FetchResponse],
    cache_root: Path,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
    max_bytes: int = DEFAULT_MAX_BYTES,
    retrieved_at: str | None = None,
) -> dict[str, Any]:
    if not candidate.url.startswith(("http://", "https://")):
        return {"status": "FAILED", "failure": {"code": "INVALID_SOURCE_URL", "url": candidate.url}}
    try:
        response = fetcher(candidate.url, timeout=timeout, max_redirects=max_redirects, max_bytes=max_bytes)
    except TimeoutError as exc:
        return {"status": "FAILED", "failure": {"code": "TIMEOUT", "url": candidate.url, "message": str(exc)}}
    except RedirectLimitError as exc:
        return {"status": "FAILED", "failure": {"code": "REDIRECT_LIMIT", "url": candidate.url, "message": str(exc)}}
    except urllib.error.HTTPError as exc:
        return {"status": "FAILED", "failure": {"code": "HTTP_ERROR", "url": candidate.url, "status": exc.code, "message": str(exc)}}
    except (urllib.error.URLError, OSError) as exc:
        return {"status": "FAILED", "failure": {"code": "NETWORK_ERROR", "url": candidate.url, "message": str(exc)}}
    except ValueError as exc:
        code = "OVERSIZED_CONTENT" if "size" in str(exc) else "ACQUISITION_FAILED"
        return {"status": "FAILED", "failure": {"code": code, "url": candidate.url, "message": str(exc)}}
    if response.status >= 400:
        return {"status": "FAILED", "failure": {"code": "HTTP_ERROR", "url": candidate.url, "status": response.status}}
    if len(response.body) > max_bytes:
        return {"status": "FAILED", "failure": {"code": "OVERSIZED_CONTENT", "url": candidate.url}}
    declared = _header(response.headers, "content-type")
    source_type, mismatch = detect_source_type(response.body, declared, response.final_url)
    if mismatch:
        return {"status": "FAILED", "failure": {"code": mismatch, "url": candidate.url, "final_url": response.final_url}}
    if source_type is None:
        return {"status": "FAILED", "failure": {"code": "UNSUPPORTED_TYPE", "url": candidate.url, "content_type": declared}}
    content_hash = "sha256:" + hashlib.sha256(response.body).hexdigest()
    artifact_dir = cache_root / "sources" / "sha256"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact = artifact_dir / (content_hash.removeprefix("sha256:") + _safe_extension(source_type))
    if artifact.exists():
        if "sha256:" + hashlib.sha256(artifact.read_bytes()).hexdigest() != content_hash:
            return {"status": "FAILED", "failure": {"code": "HASH_STORAGE_FAILURE", "url": candidate.url}}
    else:
        artifact.write_bytes(response.body)
    observed = retrieved_at or datetime.now(timezone.utc).isoformat()
    source_id = "src-" + hashlib.sha256((candidate.url + "\0" + response.final_url + "\0" + content_hash).encode()).hexdigest()[:20]
    trusted = _trusted_host(candidate, candidate.url) and _trusted_host(candidate, response.final_url)
    redirect_status = "TRUSTED" if trusted else ("CROSS_DOMAIN_UNTRUSTED" if urlparse(candidate.url).hostname != urlparse(response.final_url).hostname else "UNVERIFIED")
    source = {
        "source_id": source_id,
        "source_type": source_type,
        "canonicality": "official-canonical" if trusted else "discovery-only",
        "tier": 1 if trusted else 4,
        "url": candidate.url,
        "path": str(artifact),
        "requested_url": candidate.url,
        "final_url": response.final_url,
        "redirect_chain": list(response.redirect_chain),
        "redirect_status": redirect_status,
        "http_status": response.status,
        "content_type": declared,
        "retrieved_at": observed,
        "byte_size": len(response.body),
        "content_hash": content_hash,
        "artifact_ref": str(artifact),
        "metadata": _metadata(response.body, source_type, candidate),
        "discovery": candidate.to_dict(),
    }
    return {"status": "ACQUIRED", "source": source}
