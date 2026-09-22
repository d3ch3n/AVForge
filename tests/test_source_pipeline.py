import copy
import json
import tempfile
import unittest
from pathlib import Path

from ingestion.acquisition import FetchResponse, RedirectLimitError, acquire_candidate
from ingestion.discovery import (
    DiscoveryCandidate,
    JsonDiscoveryProvider,
    StaticDiscoveryProvider,
    build_queries,
    configured_provider,
    discover,
    discover_linked_sources,
)
from ingestion.intake import parse_json
from ingestion.source_pipeline import compare_manifests, run_source_pipeline


def item(model="Model X", manufacturer="Acme"):
    return parse_json({"contract_version": "1.0", "items": [{"manufacturer": manufacturer, "model": model}]})[0]


def candidate(url="https://manufacturer.example/product", **kwargs):
    defaults = {"url": url, "discovery_method": "fixture", "claimed_title": "Acme Model X", "claimed_manufacturer": "Acme", "claimed_model": "Model X", "official_domain": "manufacturer.example", "trust_basis": "manufacturer_domain", "source_class_hint": "official_product_page"}
    defaults.update(kwargs)
    return DiscoveryCandidate(**defaults)


class FakeFetcher:
    def __init__(self, responses):
        self.responses = list(responses)

    def __call__(self, url, **kwargs):
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def html_response(body=b"<!doctype html><title>Acme Model X</title>", url="https://manufacturer.example/product", headers=None, status=200, redirects=()):
    return FetchResponse(status, headers or {"content-type": "text/html; charset=utf-8"}, body, url, redirects)


class AcquisitionTests(unittest.TestCase):
    def acquire(self, response, **kwargs):
        with tempfile.TemporaryDirectory() as directory:
            return acquire_candidate(candidate(), FakeFetcher([response]), Path(directory), retrieved_at="2026-01-01T00:00:00Z", **kwargs)

    def test_official_html_acquisition_and_metadata(self):
        result = self.acquire(html_response())
        self.assertEqual(result["status"], "ACQUIRED")
        self.assertEqual(result["source"]["source_type"], "html")
        self.assertEqual(result["source"]["tier"], 1)
        self.assertEqual(result["source"]["metadata"]["title"], "Acme Model X")

    def test_pdf_acquisition_with_generic_mime(self):
        result = self.acquire(FetchResponse(200, {"content-type": "application/octet-stream"}, b"%PDF-1.7\n", "https://manufacturer.example/manual.bin"))
        self.assertEqual(result["source"]["source_type"], "pdf")

    def test_content_hash_and_hash_addressed_artifact(self):
        result = self.acquire(html_response())
        source = result["source"]
        self.assertTrue(source["content_hash"].startswith("sha256:"))
        self.assertIn(source["content_hash"].split(":", 1)[1], source["artifact_ref"])

    def test_same_content_deduplicates_artifact_across_urls(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            body = b"<!doctype html><title>Acme Model X</title>"
            first = acquire_candidate(candidate("https://manufacturer.example/a"), FakeFetcher([html_response(body, "https://manufacturer.example/a")]), root, retrieved_at="one")
            second = acquire_candidate(candidate("https://manufacturer.example/b"), FakeFetcher([html_response(body, "https://manufacturer.example/b")]), root, retrieved_at="two")
            self.assertEqual(first["source"]["content_hash"], second["source"]["content_hash"])
            self.assertEqual(first["source"]["artifact_ref"], second["source"]["artifact_ref"])

    def test_same_url_changed_content_is_detected_by_pipeline(self):
        candidates = [candidate(discovery_method="one"), candidate(discovery_method="two")]
        provider = StaticDiscoveryProvider(candidates)
        responses = [html_response(b"<!doctype html><title>Acme Model X</title>"), html_response(b"<!doctype html><title>Acme Model X Revised</title>")]
        with tempfile.TemporaryDirectory() as directory:
            manifest = run_source_pipeline(item(), root=Path(directory), providers=[provider], fetcher=FakeFetcher(responses), observed_at="one")
        self.assertTrue(any(failure["code"] == "URL_CONTENT_CHANGED" for failure in manifest["failures"]))

    def test_same_url_same_content_is_deduplicated(self):
        candidates = [candidate(discovery_method="one"), candidate(discovery_method="two")]
        with tempfile.TemporaryDirectory() as directory:
            manifest = run_source_pipeline(item(), root=Path(directory), providers=[StaticDiscoveryProvider(candidates)], fetcher=FakeFetcher([html_response(), html_response()]), observed_at="now")
        self.assertEqual(len(manifest["sources"]), 1)
        self.assertTrue(any(failure["code"] == "DUPLICATE_SOURCE" for failure in manifest["failures"]))

    def test_trusted_redirect_within_domain(self):
        response = html_response(b"<!doctype html><title>Acme Model X</title>")
        response = FetchResponse(200, {"content-type": "text/html"}, response.body, "https://docs.manufacturer.example/product", ("https://docs.manufacturer.example/product",))
        result = self.acquire(response)
        self.assertEqual(result["source"]["redirect_status"], "TRUSTED")

    def test_approved_document_host_is_trusted(self):
        approved = candidate(approved_hosts=("cdn.documents.example",))
        response = FetchResponse(200, {"content-type": "application/pdf"}, b"%PDF-1.7", "https://cdn.documents.example/file", ("https://cdn.documents.example/file",))
        with tempfile.TemporaryDirectory() as directory:
            result = acquire_candidate(approved, FakeFetcher([response]), Path(directory), retrieved_at="now")
        self.assertEqual(result["source"]["redirect_status"], "TRUSTED")

    def test_unrelated_redirect_is_noncanonical(self):
        response = FetchResponse(200, {"content-type": "text/html"}, b"<html><title>Acme Model X</title>", "https://unrelated.example/page", ("https://unrelated.example/page",))
        with tempfile.TemporaryDirectory() as directory:
            result = acquire_candidate(candidate(), FakeFetcher([response]), Path(directory), retrieved_at="now")
        self.assertEqual(result["source"]["redirect_status"], "CROSS_DOMAIN_UNTRUSTED")
        self.assertEqual(result["source"]["tier"], 4)

    def test_html_masquerading_as_pdf_is_rejected(self):
        response = FetchResponse(200, {"content-type": "application/pdf"}, b"<html><title>Error</title>", "https://manufacturer.example/file.pdf")
        result = self.acquire(response)
        self.assertEqual(result["failure"]["code"], "CONTENT_TYPE_MISMATCH")

    def test_http_failures_timeout_oversize_and_redirect_limit(self):
        self.assertEqual(self.acquire(FetchResponse(404, {}, b"", "https://manufacturer.example/product"))["failure"]["code"], "HTTP_ERROR")
        self.assertEqual(self.acquire(FetchResponse(500, {}, b"", "https://manufacturer.example/product"))["failure"]["code"], "HTTP_ERROR")
        self.assertEqual(self.acquire(TimeoutError("slow"))["failure"]["code"], "TIMEOUT")
        self.assertEqual(self.acquire(FetchResponse(200, {"content-type": "text/html"}, b"x" * 20, "https://manufacturer.example/product"), max_bytes=10)["failure"]["code"], "OVERSIZED_CONTENT")
        self.assertEqual(self.acquire(RedirectLimitError("loop"))["failure"]["code"], "REDIRECT_LIMIT")

    def test_unsafe_url_filename_does_not_escape_cache(self):
        result = self.acquire(html_response(url="https://manufacturer.example/../../../../tmp/evil.html?x=../a"))
        self.assertNotIn("..", Path(result["source"]["artifact_ref"]).name)


class DiscoveryIdentityManifestTests(unittest.TestCase):
    def test_query_generation_is_small_and_deterministic(self):
        self.assertEqual(build_queries(item()), ("Acme Model X", "Acme Model X manual", "Acme Model X datasheet", "Acme Model X specification"))
        self.assertEqual(build_queries({}), ())

    def test_json_provider_normalizes_results_and_queries(self):
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self, size):
                return b'{"results":[{"url":"https://reseller.example/x","title":"Model X","snippet":"hint"}]}'
        requests = []
        def opener(request, **kwargs):
            requests.append(request.full_url)
            return Response()
        provider = JsonDiscoveryProvider("https://search.example/api", api_key="secret", opener=opener)
        candidates = list(provider.search(item()))
        self.assertEqual(len(candidates), 4)
        self.assertIn("q=Acme+Model+X", requests[0])
        self.assertEqual(candidates[0].discovery_method, "configured_json_search")
        self.assertNotIn("secret", candidates[0].to_dict())

    def test_provider_configuration_is_external(self):
        self.assertIsNone(configured_provider({}))
        self.assertIsNotNone(configured_provider({"AVFORGE_DISCOVERY_ENDPOINT": "https://search.example/api"}))

    def test_first_result_is_not_automatically_trusted(self):
        untrusted = candidate(url="https://reseller.example/x", official_domain=None, trust_basis=None)
        with tempfile.TemporaryDirectory() as directory:
            manifest = run_source_pipeline(item(), root=Path(directory), providers=[StaticDiscoveryProvider([untrusted])], fetcher=FakeFetcher([html_response(url=untrusted.url)]), observed_at="now")
        self.assertEqual(manifest["sources"][0]["tier"], 4)

    def test_manufacturer_string_in_domain_is_not_trusted(self):
        untrusted = candidate(url="https://acme-lookalike.example/x", official_domain=None, trust_basis=None)
        with tempfile.TemporaryDirectory() as directory:
            manifest = run_source_pipeline(item(), root=Path(directory), providers=[StaticDiscoveryProvider([untrusted])], fetcher=FakeFetcher([html_response(url=untrusted.url)]), observed_at="now")
        self.assertEqual(manifest["sources"][0]["canonicality"], "discovery-only")

    def test_verified_provider_domain_is_auditable(self):
        verified = candidate(trust_basis="provider_verified_domain", provider_metadata={"verification": "provider_domain_assertion"})
        with tempfile.TemporaryDirectory() as directory:
            manifest = run_source_pipeline(item(), root=Path(directory), providers=[StaticDiscoveryProvider([verified])], fetcher=FakeFetcher([html_response()]), observed_at="now")
        source = manifest["sources"][0]
        self.assertEqual(source["tier"], 1)
        self.assertEqual(source["verified_official_domain"], "manufacturer.example")
        self.assertEqual(manifest["candidates"][0]["provider_metadata"]["verification"], "provider_domain_assertion")

    def test_insufficient_bootstrap_evidence_remains_untrusted(self):
        no_claim = candidate(official_domain="manufacturer.example", trust_basis=None)
        with tempfile.TemporaryDirectory() as directory:
            manifest = run_source_pipeline(item(), root=Path(directory), providers=[StaticDiscoveryProvider([no_claim])], fetcher=FakeFetcher([html_response()]), observed_at="now")
        self.assertEqual(manifest["sources"][0]["tier"], 4)

    def test_provider_domain_assertion_requires_verification_provenance(self):
        asserted = candidate(trust_basis="provider_verified_domain")
        with tempfile.TemporaryDirectory() as directory:
            result = acquire_candidate(asserted, FakeFetcher([html_response()]), Path(directory), retrieved_at="now")
        self.assertEqual(result["source"]["tier"], 4)

    def test_canonical_url_is_metadata_only(self):
        body = b'<html><head><link rel="canonical" href="https://manufacturer.example/canonical"></head><title>Acme Model X</title></html>'
        with tempfile.TemporaryDirectory() as directory:
            result = acquire_candidate(candidate(), FakeFetcher([html_response(body)]), Path(directory), retrieved_at="now")
        self.assertEqual(result["source"]["metadata"]["links"][0]["url"], "https://manufacturer.example/canonical")

    def test_verified_page_links_same_domain_manual(self):
        source = {"source_id": "src", "final_url": "https://manufacturer.example/product", "verified_official_domain": "manufacturer.example", "metadata": {"links": [{"url": "/manual.pdf", "text": "User manual"}]}}
        linked = discover_linked_sources(source)
        self.assertEqual(linked[0].source_class_hint, "official_manual")
        self.assertEqual(linked[0].trust_basis, "manufacturer_link")

    def test_verified_page_links_external_document_host_scoped(self):
        source = {"source_id": "src", "final_url": "https://manufacturer.example/product", "verified_official_domain": "manufacturer.example", "metadata": {"links": [{"url": "https://cdn.example/manual.pdf", "text": "Manual"}]}}
        linked = discover_linked_sources(source)
        self.assertEqual(linked[0].approved_hosts, ("cdn.example",))

    def test_unrelated_external_link_is_not_approved(self):
        source = {"source_id": "src", "final_url": "https://manufacturer.example/product", "verified_official_domain": "manufacturer.example", "metadata": {"links": [{"url": "https://social.example/company", "text": "Company"}]}}
        linked = discover_linked_sources(source)
        self.assertEqual(linked[0].approved_hosts, ())

    def test_document_host_trust_is_manufacturer_scoped(self):
        linked = candidate(url="https://cdn.example/manual.pdf", official_domain="other.example", approved_hosts=("cdn.example",), trust_basis="manufacturer_link", source_class_hint="official_manual")
        with tempfile.TemporaryDirectory() as directory:
            result = acquire_candidate(linked, FakeFetcher([FetchResponse(200, {"content-type": "application/pdf"}, b"%PDF-1.7", linked.url)]), Path(directory), retrieved_at="now")
        self.assertEqual(result["source"]["tier"], 1)
        unrelated = candidate(url="https://cdn.example/manual.pdf", official_domain="different.example", approved_hosts=(), trust_basis="manufacturer_link", source_class_hint="official_manual")
        with tempfile.TemporaryDirectory() as directory:
            result = acquire_candidate(unrelated, FakeFetcher([FetchResponse(200, {"content-type": "application/pdf"}, b"%PDF-1.7", unrelated.url)]), Path(directory), retrieved_at="now")
        self.assertEqual(result["source"]["tier"], 4)

    def test_redirect_from_trusted_candidate_downgrades(self):
        response = FetchResponse(200, {"content-type": "text/html"}, b"<html><title>Acme Model X</title>", "https://unrelated.example/x", ("https://unrelated.example/x",))
        with tempfile.TemporaryDirectory() as directory:
            result = acquire_candidate(candidate(), FakeFetcher([response]), Path(directory), retrieved_at="now")
        self.assertEqual(result["source"]["canonicality"], "discovery-only")

    def test_targeted_link_discovery_is_bounded(self):
        links = [{"url": f"/manual-{index}.pdf", "text": "Manual"} for index in range(20)]
        source = {"source_id": "src", "final_url": "https://manufacturer.example/product", "verified_official_domain": "manufacturer.example", "metadata": {"links": links}}
        self.assertEqual(len(discover_linked_sources(source, max_links=3)), 3)

    def test_duplicate_discovery_candidates_are_deduplicated(self):
        first = candidate(discovery_method="one")
        second = candidate(discovery_method="one")
        candidates, failures = discover(item(), [StaticDiscoveryProvider([first, second])])
        self.assertEqual(len(candidates), 1)
        self.assertFalse(failures)

    def test_provider_unavailable_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = run_source_pipeline(item(), root=Path(directory), observed_at="now")
        self.assertEqual(manifest["failures"][0]["code"], "DISCOVERY_PROVIDER_UNAVAILABLE")

    def test_provider_error_is_explicit(self):
        class Broken:
            def search(self, item):
                raise RuntimeError("provider error")
        with tempfile.TemporaryDirectory() as directory:
            manifest = run_source_pipeline(item(), root=Path(directory), providers=[Broken()], observed_at="now")
        self.assertTrue(any(failure["code"] == "DISCOVERY_PROVIDER_FAILED" for failure in manifest["failures"]))

    def test_linked_document_is_acquired_without_fact_extraction(self):
        page = b'<html><title>Acme Model X</title><a href="/manual.pdf">User manual</a></html>'
        provider = StaticDiscoveryProvider([candidate()])
        with tempfile.TemporaryDirectory() as directory:
            manifest = run_source_pipeline(item(), root=Path(directory), providers=[provider], fetcher=FakeFetcher([html_response(page), FetchResponse(200, {"content-type": "application/pdf"}, b"%PDF-1.7", "https://manufacturer.example/manual.pdf")]), observed_at="now")
        self.assertEqual(len(manifest["sources"]), 2)
        self.assertNotIn("facts", manifest)
    def test_intake_url_is_discovery_hint_not_evidence(self):
        value = item()
        value["official_url"] = "https://manufacturer.example/product"
        candidates, failures = discover(value)
        self.assertFalse(failures)
        self.assertTrue(candidates[0].to_dict()["discovery_only"])

    def test_provider_failure_isolated(self):
        class BrokenProvider:
            def search(self, item):
                raise RuntimeError("provider unavailable")
        candidates, failures = discover(item(), [BrokenProvider()])
        self.assertEqual(candidates, [])
        self.assertEqual(failures[0]["code"], "DISCOVERY_PROVIDER_FAILED")

    def test_resolved_identity_requires_trusted_official_source(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = run_source_pipeline(item(), root=Path(directory), providers=[StaticDiscoveryProvider([candidate()])], fetcher=FakeFetcher([html_response()]), observed_at="now")
        self.assertEqual(manifest["identity"]["identity_status"], "RESOLVED")
        self.assertEqual(manifest["identity"]["canonical_model"], "Model X")

    def test_unverified_intake_url_does_not_resolve_identity(self):
        value = item()
        value["official_url"] = "https://manufacturer.example/product"
        with tempfile.TemporaryDirectory() as directory:
            manifest = run_source_pipeline(value, root=Path(directory), fetcher=FakeFetcher([html_response()]), observed_at="now")
        self.assertEqual(manifest["identity"]["identity_status"], "IDENTITY_AMBIGUOUS")

    def test_variant_disagreement_is_ambiguous(self):
        candidates = [candidate(url="https://manufacturer.example/a", variant="Rev A", discovery_method="a"), candidate(url="https://manufacturer.example/b", variant="Rev B", discovery_method="b")]
        with tempfile.TemporaryDirectory() as directory:
            manifest = run_source_pipeline(item(), root=Path(directory), providers=[StaticDiscoveryProvider(candidates)], fetcher=FakeFetcher([html_response(), html_response()]), observed_at="now")
        self.assertEqual(manifest["identity"]["identity_status"], "IDENTITY_AMBIGUOUS")
        self.assertEqual({candidate["variant"] for candidate in manifest["candidates"]}, {"Rev A", "Rev B"})

    def test_source_classification_and_tier(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = run_source_pipeline(item(), root=Path(directory), providers=[StaticDiscoveryProvider([candidate(source_class_hint="official_manual")])], fetcher=FakeFetcher([FetchResponse(200, {"content-type": "application/pdf"}, b"%PDF-1.7", "https://manufacturer.example/manual.pdf")]), observed_at="now")
        self.assertEqual(manifest["sources"][0]["source_class"], "official_manual")
        self.assertEqual(manifest["sources"][0]["tier"], 1)

    def test_untrusted_source_remains_discovery_only(self):
        untrusted = candidate(official_domain=None, trust_basis=None)
        with tempfile.TemporaryDirectory() as directory:
            manifest = run_source_pipeline(item(), root=Path(directory), providers=[StaticDiscoveryProvider([untrusted])], fetcher=FakeFetcher([html_response()]), observed_at="now")
        self.assertEqual(manifest["sources"][0]["source_class"], "discovery-only")
        self.assertEqual(manifest["sources"][0]["tier"], 4)

    def test_search_snippet_is_not_source_evidence(self):
        fixture = candidate(snippet="Acme Model X supports many features")
        with tempfile.TemporaryDirectory() as directory:
            manifest = run_source_pipeline(item(), root=Path(directory), providers=[StaticDiscoveryProvider([fixture])], fetcher=FakeFetcher([html_response()]), observed_at="now")
        self.assertNotIn("facts", manifest)
        self.assertTrue(manifest["candidates"][0]["discovery_only"])

    def test_manifest_contains_failures_and_runtime_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = run_source_pipeline(item(), root=Path(directory), providers=[StaticDiscoveryProvider([candidate(), candidate(url="https://manufacturer.example/missing", discovery_method="missing")])], fetcher=FakeFetcher([html_response(), FetchResponse(404, {}, b"", "https://manufacturer.example/missing")]), observed_at="now")
            manifest_path = Path(manifest["manifest_path"])
            self.assertTrue(manifest_path.exists())
            self.assertTrue(manifest["sources"][0]["artifact_ref"].startswith(str(Path(directory) / ".ingestion")))
        self.assertTrue(any(failure["code"] == "HTTP_ERROR" for failure in manifest["failures"]))

    def test_manifest_semantic_comparison_ignores_observation_time(self):
        first = {"generated_at": "one", "sources": [{"source_id": "s", "content_hash": "sha256:a", "retrieved_at": "one"}]}
        second = copy.deepcopy(first)
        second["generated_at"] = "two"
        second["sources"][0]["retrieved_at"] = "two"
        self.assertEqual(compare_manifests(first, second), "NO_CHANGE")

    def test_manifest_hash_changes_when_source_changes(self):
        first = {"sources": [{"source_id": "s", "content_hash": "sha256:a"}]}
        second = {"sources": [{"source_id": "s", "content_hash": "sha256:b"}]}
        self.assertEqual(compare_manifests(first, second), "SOURCE_UPDATED")

    def test_changed_manifest_does_not_overwrite_previous_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            provider = StaticDiscoveryProvider([candidate()])
            first = run_source_pipeline(item(), root=root, providers=[provider], fetcher=FakeFetcher([html_response()]), observed_at="one")
            second = run_source_pipeline(item(), root=root, providers=[provider], fetcher=FakeFetcher([html_response(b"<!doctype html><title>Acme Model X Changed</title>")]), observed_at="two")
            self.assertNotEqual(first["manifest_path"], second["manifest_path"])
            self.assertTrue(Path(first["manifest_path"]).exists())
            self.assertTrue(Path(second["manifest_path"]).exists())

    def test_no_technical_fact_extraction_or_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = run_source_pipeline(item(), root=Path(directory), providers=[StaticDiscoveryProvider([candidate()])], fetcher=FakeFetcher([html_response()]), observed_at="now")
            self.assertNotIn("facts", manifest)
            self.assertFalse((Path(directory) / "equipment").exists())


if __name__ == "__main__":
    unittest.main()
