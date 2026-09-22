# Deterministic Ingestion Core

This package implements the deterministic machinery around the contract in
`docs/catalog-ingestion-contract.md`. It does not search, download, extract,
author equipment from the internet, call an agent, modify schemas or
vocabularies, commit, or push.

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
- `__main__.py`: minimal `intake`, `status`, `validate`, and `summary` CLI.

## Lifecycle

`python -m ingestion intake list.json --format json` creates one JSON job per
item under `.ingestion/jobs/`. The deterministic core completes intake and
pauses at identity resolution because source discovery and technical identity
resolution are not implemented in this phase. Such jobs have
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

Primary-state precedence is deterministic: `VALIDATION_FAILED`, `SCHEMA_GAP`,
`VOCAB_GAP`, `IDENTITY_AMBIGUOUS`, `SOURCE_NOT_FOUND`,
`INSUFFICIENT_EVIDENCE`, `NEEDS_REVIEW`, then `READY`. `READY` additionally
requires completed required stages, a resolved identity, and recorded passing
validation results.

`READY` is eligibility for explicit publication review only. There is no
publication command and no git commit/push path in this package.

## Runtime Paths

`.ingestion/jobs/` is runtime-only and ignored by Git. Source caches, reports,
and downloaded manufacturer documents are intentionally not implemented.

## Reruns

Rerun comparison ignores retrieval and observation timestamps. It compares
identity, mappings, candidate data, facts, and source content/revision
metadata, producing `NO_CHANGE`, `SOURCE_UPDATED`, `FACTS_CHANGED`, or
`REVIEW_REQUIRED`.
