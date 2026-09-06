# Agent Instructions

- AVForge is an audiovisual engineering system. Its first phase is exclusively structured modeling of AV equipment.
- Do not implement agents, AI, databases, or DWG generation in this phase without explicit instruction.
- The data model must be universal across AV equipment categories; prefer extensible structures and stable IDs.
- Never conflate physical connectors with signal types. For example, RJ45 may carry LAN, HDBaseT, or a proprietary link; connector type alone must never imply compatibility.
- Proprietary interfaces require explicit protocol/family identification and pairing restrictions.
- Model power input/consumption for future load reports and support future graphical representation, including blocks and connection points.
- Keep official manufacturer data separate from the company’s internal knowledge.
- Use the Q-SYS Core 8 Flex as a schema stress test, but never couple the schema to Q-SYS.
- Do not invent missing technical specifications.
- Before changing architecture or introducing new abstractions, explain the decision.
- Always run relevant validations before concluding a task. Validate every non-empty JSON file touched with `python -m json.tool <path>`.
- Keep equipment entries under `equipment/<vendor>/` and JSON schemas under `schemas/`; reserve `docs/` for documentation.
- The current README, schema, and Core 8 Flex entry are placeholders; do not infer a data contract from them. Inspect or update the schema and representative entries together when defining one.
- This repository currently has no package manifest, build system, test suite, linter, formatter, CI configuration, or executable source.
- Project files are in this directory; the nested `AVForge/.git/` contains the only Git metadata and currently has no commits or tracked files.
- Do not commit or push automatically during schema definition unless explicitly requested.
