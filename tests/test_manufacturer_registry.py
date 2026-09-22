import tempfile
import unittest
from pathlib import Path

from ingestion.acquisition import FetchResponse
from ingestion.discovery import DiscoveryCandidate, JsonDiscoveryProvider, StaticDiscoveryProvider, build_queries
from ingestion.intake import parse_csv, parse_json
from ingestion.manufacturer_registry import ManufacturerRegistry, assess_manufacturer
from ingestion.source_pipeline import run_source_pipeline


def intake(manufacturer="Acme", model="Model X"):
    return parse_json({"contract_version": "1.0", "items": [{"manufacturer": manufacturer, "model": model}]})[0]


def entry(status="VERIFIED", name="Acme", root="manufacturer.example", hosts=None):
    return {"manufacturer_id": "manufacturer.acme", "canonical_name": name, "aliases": [], "official_web_roots": [root], "approved_document_hosts": hosts or [], "trust": {"status": status, "provenance": ["source:review"]}}


class Fetcher:
    def __init__(self, responses):
        self.responses = list(responses)
    def __call__(self, url, **kwargs):
        return self.responses.pop(0)


def response(title="Acme Model X", url="https://manufacturer.example/product"):
    body = f"<!doctype html><title>{title}</title>".encode()
    return FetchResponse(200, {"content-type": "text/html"}, body, url)


class RegistryTests(unittest.TestCase):
    def test_normal_intake_requires_manufacturer_and_model(self):
        value = intake()
        self.assertEqual(value["intake_status"], "VALID_NORMAL")
        self.assertTrue(value["automated_discovery_eligible"])

    def test_model_only_legacy_intake_is_explicitly_unresolved(self):
        value = parse_csv("model\nModel X\n")[0]
        self.assertEqual(value["intake_status"], "UNRESOLVED_MANUFACTURER")
        self.assertFalse(value["automated_discovery_eligible"])

    def test_missing_manufacturer_blocks_provider_before_search(self):
        class ExplodingProvider:
            def search(self, item):
                raise AssertionError("provider must not run")
        value = parse_json({"contract_version": "1.0", "items": [{"model": "Model X"}]})[0]
        with tempfile.TemporaryDirectory() as directory:
            result = run_source_pipeline(value, root=Path(directory), providers=[ExplodingProvider()])
        self.assertEqual(result["failures"][0]["code"], "MANUFACTURER_REQUIRED")

    def test_registry_lookup_and_aliases_are_explicit(self):
        registry = ManufacturerRegistry([dict(entry(), aliases=["ACME AV"])])
        self.assertEqual(registry.lookup("ACME AV")["manufacturer_id"], "manufacturer.acme")
        self.assertIsNone(registry.lookup("Acme Audio"))

    def test_registry_serialization_is_deterministic(self):
        registry = ManufacturerRegistry([dict(entry(), official_web_roots=["z.example", "a.example"], aliases=["Zed", "Acme AV"])])
        self.assertEqual(registry.serialize(), registry.serialize())
        self.assertLess(registry.serialize().index("a.example"), registry.serialize().index("z.example"))

    def test_registry_rejects_equipment_data(self):
        value = dict(entry())
        value["capabilities"] = []
        with self.assertRaises(ValueError):
            ManufacturerRegistry([value])

    def test_unknown_manufacturer_creates_proposal_only_from_page_evidence(self):
        registry = ManufacturerRegistry.empty()
        item = intake()
        candidate = DiscoveryCandidate(url="https://manufacturer.example/product", discovery_method="search")
        source = {"source_id": "src-1", "final_url": candidate.url, "metadata": {"title": "Acme Model X", "meta": {}}}
        result = assess_manufacturer(item, [candidate.to_dict()], [source], registry)
        self.assertEqual(result["status"], "PROPOSED")
        self.assertEqual(result["entry"]["trust"]["status"], "PROPOSED")

    def test_proposed_root_is_not_verified(self):
        registry = ManufacturerRegistry([entry("PROPOSED")])
        self.assertIsNone(registry.verified("Acme"))

    def test_known_verified_manufacturer_reuses_root(self):
        registry = ManufacturerRegistry([entry()])
        self.assertEqual(registry.verified("Acme")["official_web_roots"], ["manufacturer.example"])

    def test_known_verified_scopes_queries(self):
        self.assertEqual(build_queries({"manufacturer": "Acme", "model": "Model X", "_official_web_roots": ["manufacturer.example"]})[0], 'site:manufacturer.example "Model X"')

    def test_unknown_manufacturer_uses_bootstrap_queries(self):
        self.assertEqual(build_queries({"manufacturer": "Acme", "model": "Model X"})[0], "Acme Model X")

    def test_known_verified_root_reuses_authority_without_provider_assertion(self):
        registry = ManufacturerRegistry([entry()])
        candidate = DiscoveryCandidate(url="https://manufacturer.example/product", discovery_method="search")
        with tempfile.TemporaryDirectory() as directory:
            manifest = run_source_pipeline(intake(), root=Path(directory), registry=registry, providers=[StaticDiscoveryProvider([candidate])], fetcher=Fetcher([response()]), observed_at="now")
        self.assertEqual(manifest["sources"][0]["tier"], 1)
        self.assertEqual(manifest["manufacturer_trust"]["status"], "VERIFIED")

    def test_provider_assertion_cannot_establish_authority(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, size): return b'{"results":[{"url":"https://manufacturer.example/product","official_domain":"manufacturer.example","trust_basis":"provider_verified_domain"}]}'
        provider = JsonDiscoveryProvider("https://search.example/api", opener=lambda request, **kwargs: Response())
        candidates = list(provider.search(intake()))
        self.assertIsNone(candidates[0].official_domain)
        self.assertIsNone(candidates[0].trust_basis)

    def test_search_result_order_does_not_override_verified_root(self):
        registry = ManufacturerRegistry([entry()])
        candidates = [DiscoveryCandidate(url="https://reseller.example/product", discovery_method="search"), DiscoveryCandidate(url="https://manufacturer.example/product", discovery_method="search")]
        with tempfile.TemporaryDirectory() as directory:
            manifest = run_source_pipeline(intake(), root=Path(directory), registry=registry, providers=[StaticDiscoveryProvider(candidates)], fetcher=Fetcher([response(url=candidates[0].url), response(url=candidates[1].url)]), observed_at="now")
        self.assertEqual([source["tier"] for source in manifest["sources"]], [4, 1])

    def test_lookalike_domain_is_not_scoped(self):
        registry = ManufacturerRegistry([entry()])
        candidate = DiscoveryCandidate(url="https://manufacturer.example.attacker/product", discovery_method="search")
        with tempfile.TemporaryDirectory() as directory:
            manifest = run_source_pipeline(intake(), root=Path(directory), registry=registry, providers=[StaticDiscoveryProvider([candidate])], fetcher=Fetcher([response(url=candidate.url)]), observed_at="now")
        self.assertEqual(manifest["sources"][0]["tier"], 4)

    def test_exact_model_is_required(self):
        registry = ManufacturerRegistry([entry()])
        candidate = DiscoveryCandidate(url="https://manufacturer.example/product", discovery_method="search")
        with tempfile.TemporaryDirectory() as directory:
            manifest = run_source_pipeline(intake(), root=Path(directory), registry=registry, providers=[StaticDiscoveryProvider([candidate])], fetcher=Fetcher([response("Acme Model XY")]), observed_at="now")
        self.assertEqual(manifest["identity"]["identity_status"], "IDENTITY_AMBIGUOUS")

    def test_family_page_is_ambiguous(self):
        registry = ManufacturerRegistry([entry()])
        candidate = DiscoveryCandidate(url="https://manufacturer.example/family", discovery_method="search")
        with tempfile.TemporaryDirectory() as directory:
            manifest = run_source_pipeline(intake(), root=Path(directory), registry=registry, providers=[StaticDiscoveryProvider([candidate])], fetcher=Fetcher([response("Acme Model Family")]), observed_at="now")
        self.assertEqual(manifest["identity"]["identity_status"], "IDENTITY_AMBIGUOUS")

    def test_review_approval_is_explicit_and_not_automatic(self):
        registry = ManufacturerRegistry.empty()
        proposal = registry.propose("Acme", ["manufacturer.example"], ["src-1"])
        self.assertEqual(proposal["trust"]["status"], "PROPOSED")
        approved = registry.approve_proposal(proposal, "reviewer-1", "review:source-check")
        self.assertEqual(approved["trust"]["status"], "VERIFIED")

    def test_multiple_products_reuse_one_registry_entry(self):
        registry = ManufacturerRegistry([entry()])
        self.assertEqual(registry.verified("Acme")["manufacturer_id"], registry.verified("Acme")["manufacturer_id"])

    def test_registry_has_no_equipment_facts(self):
        serialized = ManufacturerRegistry([entry()]).serialize().lower()
        self.assertNotIn("model", serialized)
        self.assertNotIn("specification", serialized)

    def test_third_party_source_is_noncanonical(self):
        candidate = DiscoveryCandidate(url="https://reseller.example/product", discovery_method="search", trust_basis="authorized_third_party", official_domain="reseller.example")
        with tempfile.TemporaryDirectory() as directory:
            manifest = run_source_pipeline(intake(), root=Path(directory), providers=[StaticDiscoveryProvider([candidate])], fetcher=Fetcher([response(url=candidate.url)]), observed_at="now")
        self.assertEqual(manifest["sources"][0]["canonicality"], "approved-third-party")
        self.assertEqual(manifest["sources"][0]["tier"], 3)

    def test_no_facts_or_equipment_are_generated(self):
        registry = ManufacturerRegistry([entry()])
        candidate = DiscoveryCandidate(url="https://manufacturer.example/product", discovery_method="search")
        with tempfile.TemporaryDirectory() as directory:
            manifest = run_source_pipeline(intake(), root=Path(directory), registry=registry, providers=[StaticDiscoveryProvider([candidate])], fetcher=Fetcher([response()]), observed_at="now")
            self.assertNotIn("facts", manifest)
            self.assertFalse((Path(directory) / "equipment").exists())


if __name__ == "__main__":
    unittest.main()
