"""Provider-neutral source discovery contracts.

Discovery returns hints only. It never fetches URLs or treats snippets as
technical evidence.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from typing import Any, Callable, Iterable, Protocol
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
import urllib.request


@dataclass(frozen=True)
class DiscoveryCandidate:
    url: str
    discovery_method: str
    query: str | None = None
    discovered_from: str | None = None
    claimed_title: str | None = None
    claimed_manufacturer: str | None = None
    claimed_model: str | None = None
    product_family: str | None = None
    variant: str | None = None
    source_class_hint: str | None = None
    official_domain: str | None = None
    approved_hosts: tuple[str, ...] = ()
    trust_basis: str | None = None
    provider_metadata: dict[str, Any] | None = None
    snippet: str | None = None
    discovered_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["discovery_only"] = True
        return value


class DiscoveryProvider(Protocol):
    def search(self, item: dict[str, Any]) -> Iterable[DiscoveryCandidate]:
        """Return discovery hints without acquiring or interpreting sources."""


class StaticDiscoveryProvider:
    """Deterministic fixture/provider boundary for offline tests."""

    def __init__(self, candidates: Iterable[DiscoveryCandidate] = ()) -> None:
        self._candidates = tuple(candidates)

    def search(self, item: dict[str, Any]) -> Iterable[DiscoveryCandidate]:
        return self._candidates


def build_queries(item: dict[str, Any]) -> tuple[str, ...]:
    """Build a small deterministic query set, scoped when roots are known."""
    manufacturer = " ".join(str(item.get("manufacturer", "")).split())
    model = " ".join(str(item.get("model", "")).split())
    identity = " ".join(part for part in (manufacturer, model) if part)
    roots = tuple(item.get("_official_web_roots", ()))
    if roots and model:
        return tuple(query for root in roots for query in (f'site:{root} "{model}"', f'site:{root} "{model}" manual', f'site:{root} "{model}" datasheet', f'site:{root} "{model}" specification'))
    if not identity:
        return ()
    return (identity, f"{identity} manual", f"{identity} datasheet", f"{identity} specification")


class JsonDiscoveryProvider:
    """Adapter for an externally configured JSON search endpoint.

    The endpoint is intentionally configuration-driven. Its response is
    normalized here so provider-specific fields never leave this adapter.
    """

    def __init__(self, endpoint: str, *, api_key: str | None = None, opener: Callable[..., Any] | None = None) -> None:
        parsed = urlparse(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("discovery endpoint must be an HTTP(S) URL")
        self.endpoint = endpoint
        self.api_key = api_key
        self._opener = opener or urllib.request.urlopen

    def search(self, item: dict[str, Any]) -> Iterable[DiscoveryCandidate]:
        for query in build_queries(item):
            parsed = urlparse(self.endpoint)
            query_values = dict(parse_qsl(parsed.query))
            query_values["q"] = query
            url = urlunparse(parsed._replace(query=urlencode(query_values)))
            headers = {"Accept": "application/json", "User-Agent": "AVForge-Catalog-Ingestion/1.0"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            request = urllib.request.Request(url, headers=headers)
            with self._opener(request, timeout=20.0) as response:
                payload = json.loads(response.read(2 * 1024 * 1024).decode("utf-8"))
            results = payload.get("results", payload) if isinstance(payload, dict) else payload
            if not isinstance(results, list):
                raise ValueError("discovery response must contain a results list")
            for result in results:
                if not isinstance(result, dict) or not isinstance(result.get("url"), str):
                    continue
                yield DiscoveryCandidate(
                    url=result["url"],
                    discovery_method="configured_json_search",
                    query=query,
                    claimed_title=result.get("title"),
                    claimed_manufacturer=result.get("manufacturer"),
                    claimed_model=result.get("model"),
                    product_family=result.get("product_family"),
                    variant=result.get("variant"),
                    snippet=result.get("snippet"),
                    provider_metadata={"provider": type(self).__name__, "provider_fields": {key: result[key] for key in ("official_domain", "approved_hosts", "trust_basis") if key in result}, **(result.get("provider_metadata") or {})},
                )


def configured_provider(environ: dict[str, str] | None = None) -> DiscoveryProvider | None:
    values = environ or os.environ
    endpoint = values.get("AVFORGE_DISCOVERY_ENDPOINT")
    if not endpoint:
        return None
    return JsonDiscoveryProvider(endpoint, api_key=values.get("AVFORGE_DISCOVERY_API_KEY"))


def classify_link(anchor: str, url: str) -> str:
    value = f"{anchor} {url}".lower()
    for words, source_class in (
        (("datasheet", "data sheet", "specification", "spec sheet"), "official_datasheet"),
        (("manual", "user guide", "hardware guide"), "official_manual"),
        (("a&e", "architect", "engineering"), "official_ae"),
        (("support", "help", "download"), "official_support"),
    ):
        if any(word in value for word in words):
            return source_class
    return "official_other"


def discover_linked_sources(source: dict[str, Any], *, max_links: int = 12) -> tuple[DiscoveryCandidate, ...]:
    """Return bounded document hints from one verified official page."""
    metadata = source.get("metadata", {})
    links = metadata.get("links", []) if isinstance(metadata, dict) else []
    result: list[DiscoveryCandidate] = []
    for link in links[:max_links]:
        if not isinstance(link, dict):
            continue
        linked_url = urljoin(source.get("final_url", ""), link.get("url", ""))
        if not _valid_http_url(linked_url):
            continue
        link_text = link.get("text", "")
        if link_text.lower() in {"canonical", "stylesheet", "icon", "alternate"} or linked_url.lower().split("?", 1)[0].endswith((".css", ".js", ".ico")):
            continue
        source_class = classify_link(link_text, linked_url)
        linked_host = urlparse(linked_url).hostname or ""
        official_host = urlparse(source.get("verified_official_domain", "")).hostname or source.get("verified_official_domain", "")
        approved_hosts = list(source.get("approved_document_hosts", ()))
        if source_class != "official_other" and linked_host and linked_host != official_host:
            approved_hosts.append(linked_host)
        result.append(DiscoveryCandidate(
            url=linked_url,
            discovery_method="verified_page_link",
            discovered_from=source.get("source_id"),
            claimed_title=link_text,
            official_domain=source.get("verified_official_domain"),
            approved_hosts=tuple(dict.fromkeys(approved_hosts)),
            trust_basis="manufacturer_link",
            source_class_hint=source_class,
        ))
    return tuple(result)


def _valid_http_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def discover(item: dict[str, Any], providers: Iterable[DiscoveryProvider] = (), discovered_at: str | None = None) -> tuple[list[DiscoveryCandidate], list[dict[str, Any]]]:
    candidates: list[DiscoveryCandidate] = []
    failures: list[dict[str, Any]] = []
    official_url = item.get("official_url")
    if official_url:
        if _valid_http_url(official_url):
            candidates.append(DiscoveryCandidate(
                url=official_url,
                discovery_method="intake_official_url",
                claimed_manufacturer=item.get("manufacturer"),
                claimed_model=item.get("model"),
                discovered_at=discovered_at,
            ))
        else:
            failures.append({"code": "INVALID_SOURCE_URL", "message": "official_url must be an HTTP(S) URL", "url": official_url})
    for provider in providers:
        try:
            for candidate in provider.search(item):
                if not _valid_http_url(candidate.url):
                    failures.append({"code": "INVALID_SOURCE_URL", "message": "discovery provider returned a non-HTTP URL", "url": candidate.url})
                    continue
                candidates.append(candidate)
        except Exception as exc:
            failures.append({"code": "DISCOVERY_PROVIDER_FAILED", "message": str(exc), "provider": type(provider).__name__})
    unique: dict[tuple[str, str | None], DiscoveryCandidate] = {}
    for candidate in candidates:
        unique.setdefault((candidate.url, candidate.discovery_method), candidate)
    return list(unique.values()), failures
