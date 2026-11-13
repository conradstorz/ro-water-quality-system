# ADR-0009: 1-Wire monitoring input

**Status:** Proposed (2026-11-13) — pending owner review. Design basis: `docs/superpowers/specs/2026-11-13-onewire-input-design.md`.

**Decision:** Add a 1-Wire bus to every sensor node (up to 8 mixed-family devices, daisy-chained) as a monitoring only input. 1-Wire data never permits or inhibits RO production; any interlock stays hardwired. Protocol 1.2 to 1.3, additive: the input polling window grows from 100-139 to 100-199 (single window, one coherent snapshot, one read per period), with header registers 140-143 and 8 slots of 7 words from 144. Fault bit 10 `onewire_bus_fault` is monitoring only; 1-Wire bits are never added to `validity_mask` or `critical_validity_bits`. ROM-ID-to-role binding lives in the controller config; a node's self-report never defines a role. Connector: Nilight 3-pin waterproof male/female harness connector, inline, labeled "1-WIRE".

**Rationale:**
- Cheap temperature and monitor devices are useful for logging and display but are not safety measurements.
- A single polling window matches the schema rule that occupied input addresses equal the polling window; a v1.2 reader of 100-139 still works.
- Binding roles in the controller keeps a swapped or rogue device from silently becoming "feed temperature".

**Alternatives rejected:**
- Critical 1-Wire (loss inhibits production): would put a long, unshielded, hot-pluggable bus inside the safety path; rejected.
- A second poll block (separate read of 140-199): the schema requires one polling window, it doubles the reads and breaks snapshot coherence; rejected.
- Paged or windowed access to a device table: more protocol state and torn-read risk for at most 8 devices; rejected.

**Consequences:**
- Generic 3-pin automotive plugs mate with each other; the hazard is mitigated only by labeling and routing away from 24 V and RS485.
- Unsupported families are reported by ROM ID only; no value is guessed.

**TBD (do not guess):** connector cavity numbering and voltage/current rating; pull-up value; GPIO; polyfuse rating; maximum cable length and device count; rescan interval; supported DS2438 variants and other families.
