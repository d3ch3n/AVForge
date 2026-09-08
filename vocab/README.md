# AVForge Vocabulary

AVForge Vocabulary v1.1.0 defines canonical terms used by the equipment model. It is separate from `schemas/equipment.schema.json`: the schema defines structure, while this directory defines the controlled language used in that structure.

## Scope

Each entry maps a term to one stable, lowercase kebab-case ID. An alias means another way of naming the same canonical concept. Aliases are input-normalization hints only; they do not represent equipment context, function, compatibility, version, capacity, transported protocol, or manufacturer description.

For example, `RJ-45` is an acceptable alias for `rj45-8p8c`. `10-pin Euroblock (shared GPIO input connector)` is not a pure alias for `euroblock-10-pin`, because `shared GPIO input connector` describes equipment context rather than the physical connector identity.

The vocabulary is intentionally small and evidence-based. Values that are descriptions, manufacturer marketing language, electrical characteristics, or project-instance data are not promoted to global terms without a clear canonical concept.

`signal-formats.json` is empty in v1.1.0 because the current equipment records do not populate `signal_format`. Terms such as line level, balanced, converter resolution, and phantom power remain descriptions or electrical/signal characteristics until the model records them explicitly as formats.

`slot-types.json` and `module-types.json` use `scope` to make their product-family-specific nature explicit. They are not a catalog of every Crestron part and do not create a general module hierarchy.

## Compatibility Boundary

Future connection compatibility may evaluate these independent layers:

1. Physical
2. Electrical
3. Signal
4. Protocol
5. Direction
6. Restrictions
7. Capacity
8. Known Compatibility

Physical compatibility alone does not imply connection compatibility. In particular, `rj45-8p8c` does not imply Ethernet, AES67, Dante, Q-LAN, DM NVX, HDBaseT, or any other signal or protocol. This vocabulary contains no connector-mating rules, protocol encapsulation, compatibility graph, inference rules, semantic validator, or connection engine.

## Deliberate Limits

- Equipment records are migrated separately from Vocabulary releases.
- Optional or undocumented protocol fields remain absent rather than being assigned `unknown` or a guessed protocol.
- No compatibility relation is encoded by shared aliases, labels, families, or connector IDs.
