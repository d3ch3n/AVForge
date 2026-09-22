# Deterministic Ingestion Core

This package implements the deterministic machinery around the contract in
`docs/catalog-ingestion-contract.md`. It locates source candidates through an
injected discovery provider and acquires bounded source content, but it does
not extract technical facts, author equipment from the internet, call an
agent, modify schemas or vocabularies, commit, or push.

## Layout

- `models.py`: JSON-serializable job, source, evidence, fact, issue, and
  mapping shape validation.
- `intake.py`: JSON/CSV parsing, normalization, duplicate rejection, and
  deterministic job IDs.
- `state.py`: stage state, primary-state precedence, batch summaries, and
  timestamp-independent rerun comparison.
- `validation.py`: wrapper for JSON parsing and the existing AVForge schema,
  semantic, test, catalog, and `git diff --check` commands.
- `runner.py`: independent batch jobs, runtime persistence, resume comparison,
  and publication eligibility.
- `manufacturer_registry.py`: tracked manufacturer identity/trust lookup,
  conservative proposals, and explicit review promotion.
- `discovery.py`: provider-neutral candidates, deterministic queries, fixture
  provider, and configuration-driven JSON provider adapter.
- `acquisition.py`: bounded HTTP acquisition, MIME checks, hashing, and cache.
- `identity.py`: official-evidence identity resolution without technical facts.
- `source_pipeline.py`: classification, manifest generation, and semantic
  manifest comparison.
- `extraction.py`: Fact Extraction v1 facts, evidence, conflicts, validation,
  serialization, and rerun comparison. It does not parse source documents.
- `__main__.py`: minimal `intake`, `sources`, `status`, `validate`, and
  `summary` CLI.

## Lifecycle

`python -m ingestion intake list.json --format json` creates one JSON job per
item under `.ingestion/jobs/`. Normal automated intake requires both
`manufacturer` and `model`. Legacy model-only input remains parseable, but is
marked `UNRESOLVED_MANUFACTURER` and cannot enter automated source discovery.
Such jobs have
`pipeline_status: BLOCKED`, a `BLOCKED` stage, and are not validation failures
or human-review issues. Their conservative primary state is `NEEDS_REVIEW`
because they are not eligible for publication.

Job IDs are derived from normalized logical intake content, not batch row
position. `batch_index` is retained only as occurrence metadata. Exact
duplicates are rejected within one batch; the same item in a later batch has
the same logical job ID.

Future stages may update the job with resolved identity, source/evidence/fact
records, mappings, and validation results. The model rejects malformed
references and unsupported mapping/state values but does not judge whether a
manufacturer claim is technically true.

## Manufacturer-First Source Pipeline

The supplied manufacturer is a constraint, not proof. The normal flow is:

`manufacturer + model` -> tracked manufacturer registry -> scoped official
discovery when verified, or conservative bootstrap discovery when unknown ->
acquisition -> model/manufacturer identity verification -> immutable manifest.

`manufacturers/registry.json` is tracked because verified manufacturer roots
are reusable governance data and should be reviewable and version-controlled.
It contains no equipment models or technical facts. Entries are `UNVERIFIED`,
`PROPOSED`, or `VERIFIED`. Automatic discovery can create a proposal with
source references, but only an explicit review promotion can create permanent
verified trust. A new manufacturer is therefore reviewed once per domain
relationship, not once per equipment job.

For a verified manufacturer, discovery queries are scoped to official roots
and approved document hosts. For an unknown manufacturer, queries use the
supplied manufacturer and model, but candidate pages remain untrusted until
AVForge evidence supports a reviewable manufacturer-root proposal. Search
ranking, snippets, and provider assertions never establish canonical authority.

## Phase 3 Source Pipeline

`python -m ingestion sources list.json --format json` runs the generic
identity/discovery/acquisition/classification boundary. Search providers are
injected through `DiscoveryProvider`; the CLI loads the tracked registry and
uses the optional
`AVFORGE_DISCOVERY_ENDPOINT` JSON provider when configured. An API key may be
provided through `AVFORGE_DISCOVERY_API_KEY`; it is never written to
manifests. `official_url` intake hints are acquired directly but remain
unverified unless a verified registry root or an explicit manufacturer-link
trust chain establishes authority. The provider returns candidates and
provenance only; it does not certify official status.

`UrllibFetcher` performs source acquisition network access. The configured
JSON provider performs only bounded search requests. Acquisition applies
timeout, redirect, and maximum-size limits (20 seconds, 5 redirects, 25 MiB), stores bytes under `.ingestion/sources/sha256/`, and
uses content hashes rather than server filenames. HTML/PDF content is passive
data. The pipeline extracts only document metadata needed for classification,
never technical specifications.

An official-domain trust basis must come from the discovery provider or an
verified manufacturer registry root, or a manufacturer-link trust chain.
Search result wording, provider assertions, and an intake URL alone do
not promote a source to Tier 1. Cross-domain redirects remain acquired data
but are downgraded to discovery-only unless the destination is explicitly
approved. A verified official HTML page receives one bounded targeted-link
pass for manuals, datasheets, specifications, A&E documents, and support
links. External document hosts are approved only for the manufacturer/job
through an explicit link from that verified page; unrelated external links
remain untrusted.

Official acquired pages must identify both the supplied manufacturer and the
exact requested model in acquired metadata. Family pages, similar models,
accessories, bundles, and variants remain ambiguous rather than being merged.
Third-party sources are retained only as discovery/corroboration evidence and
remain visibly noncanonical.

## Fact Extraction v1

Fact Extraction is an intermediate evidence layer between acquired sources and
future schema/vocabulary mapping:

`source -> extraction -> fact/evidence -> conflict analysis -> mapping -> equipment JSON`

`ingestion/extraction.py` represents generic facts with explicit subjects,
properties, JSON values, units, qualifiers, conditions, precision, polarity,
evidence references, and extraction method. It does not define equipment
schema paths or generate equipment records. A fact ID is derived from the
logical subject/property/value/qualifier semantics, excluding evidence IDs,
timestamps, filesystem paths, and extraction ordering. Identical facts found
in multiple sources therefore merge into one fact with multiple evidence IDs;
different values receive different fact IDs and may be represented by a
conflict.

Evidence binds a short observation and extensible locator to both `source_id`
and the immutable acquired source content hash. Validation rejects unknown
sources, hash mismatches, duplicate IDs, unsupported precision/status values,
and broken references. Source authority and manufacturer trust are preserved
from acquisition and cannot be promoted by extraction.

Values preserve source semantics: minimum, maximum, range, approximate,
nominal, `not-rated`, and `unknown` remain explicit. Conditions and qualifiers
are structured data and are never flattened into unconditional facts. Absence,
"not found", and "not documented" remain `UNKNOWN`; only explicit source
evidence may support a negative polarity.

`unit_normalization.py` derives exact canonical unit representations for
Mapping without changing a Fact. The source value and unit remain authoritative
and traceable through the original `fact_id`; the derived value records the
explicit conversion rule, canonical vocabulary unit, dimension, precision,
qualifiers, and conditions. Version 1 contains only the registered exact
`g`-to-`kilogram` mass conversion and fails closed for unsupported or
dimension-incompatible conversions. Equipment Generation consumes validated
normalized mappings and does not invent conversions.

Conflicts are separate records with relationship classes, fact/evidence
references, explanation, and resolution status. No source type, recency, or
value magnitude automatically wins. Rerun comparison distinguishes unchanged
results, evidence additions/removals, fact additions/removals/changes, and
conflict changes while ignoring observation timestamps.

Runtime extraction results are written under `.ingestion/extractions/` and are
not catalog records. Source content is passive data: this layer never executes
text, changes trust, downloads documents, maps schema fields, modifies
vocabularies, generates equipment JSON, commits, or pushes.

## Mapping v1

Mapping consumes a validated Fact Extraction result and records whether each
fact can fit the current AVForge schema and vocabularies. A Fact is not an
equipment schema field: extraction records what sources say, Mapping records
how or whether that fact fits the current model, and future Equipment
Generation will materialize accepted mappings.

The six mapping states are `STRUCTURED`, `NOTES_ONLY`, `OMIT_UNKNOWN`,
`VOCAB_GAP`, `SCHEMA_GAP`, and `CONFLICT`. Every fact in a completed result
receives exactly one decision. `STRUCTURED` requires a structured target that
preserves the subject, value, precision, and material qualifiers. `NOTES_ONLY`
is reserved for meaningful non-material descriptive information and cannot hide
an engineering schema deficiency. `OMIT_UNKNOWN` is limited to unknown or
not-applicable semantics. `VOCAB_GAP` means the schema shape exists but a
canonical vocabulary ID is missing; `SCHEMA_GAP` means the schema cannot
faithfully represent the engineering meaning. Neither gap state edits its
vocabulary or schema. `CONFLICT` references unresolved extraction conflicts
without selecting a source winner.

Mapping v1 does not auto-classify arbitrary facts. It validates an explicit
decision from a deterministic planner or reviewed proposal. If a future
planner receives multiple applicable dispositions, the documented precedence is
`CONFLICT`, `SCHEMA_GAP`, `VOCAB_GAP`, then the terminal states
`STRUCTURED`, `NOTES_ONLY`, and `OMIT_UNKNOWN`; validation still requires the
selected state to satisfy its own invariants.

Mapping format `1.1` adds `semantic_bindings` to current `STRUCTURED`
decisions. Bindings declare deterministic fingerprints for the Fact's subject,
value, unit, precision, qualifiers, conditions, and polarity, together with
the target fingerprint. A binding may include a validated Unit Normalization
result for an exact canonical unit. This is semantic-preservation validation,
not a copy of the complete Fact and not Equipment Generation.

Direct subject entities are checked against the Fact subject identity. Indirect
subject relationships must be declared by the planner and remain review-owned;
the validator does not infer arbitrary engineering equivalence.

Agents or planners select engineering targets and propose bindings. The
deterministic validator verifies that explicit Fact semantics are accounted for
but does not prove every domain-specific target interpretation. Published
Mapping `1.0` results are accepted only through explicit `allow_legacy=True`
validation and are not silently treated as `1.1` records.

Mapping targets use structured `property` and identity-based `entity` segments
rather than fragile array indexes or executable paths. Mapping records retain
the fact and evidence IDs, while gap proposals retain their evidence references.
Mapping IDs and gap IDs are deterministic. Runtime results are written under
`.ingestion/mappings/`, remain ignored by Git, and are not catalog records.
Mapping treats facts, evidence observations, notes, and source content as data;
it does not execute them, mutate trust, schema, vocabularies, equipment, or
manufacturer records, and it does not commit or push.

Per-job manifests are written under `.ingestion/manifests/`. They retain
identity claims, all discovery candidates, acquired source metadata,
classification/tier, hashes, artifact references, redirects, and failures.
Retrieval/discovery timestamps are excluded from semantic manifest comparison.
Runtime source artifacts and manifests are never catalog records.

Primary-state precedence is deterministic: `VALIDATION_FAILED`, `SCHEMA_GAP`,
`VOCAB_GAP`, `IDENTITY_AMBIGUOUS`, `SOURCE_NOT_FOUND`,
`INSUFFICIENT_EVIDENCE`, `NEEDS_REVIEW`, then `READY`. `READY` additionally
requires completed required stages, a resolved identity, and recorded passing
validation results.

`READY` is eligibility for explicit publication review only. There is no
publication command and no git commit/push path in this package.

## Runtime Paths

`.ingestion/` is runtime-only and ignored by Git. It contains jobs, manifests,
and SHA-256-addressed source artifacts; these are never catalog records.

## Reruns

Rerun comparison ignores retrieval and observation timestamps. It compares
identity, mappings, candidate data, facts, and source content/revision
metadata, producing `NO_CHANGE`, `SOURCE_UPDATED`, `FACTS_CHANGED`, or
`REVIEW_REQUIRED`.
