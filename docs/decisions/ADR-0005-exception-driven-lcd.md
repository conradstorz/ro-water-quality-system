# ADR-0005: Exception-driven sensor-node LCD

**Status:** Accepted for initial implementation specification (2026-11-11).

**Decision:** Replace unconditional normal-screen rotation with fault-first presentation. Rank critical > warning > advisory > normal. Display local sensor faults directly, and display main-controller operational faults only from a fresh, validated, display-only Modbus holding-register status extension. The LCD has no control authority. Keep normal page rotation when no higher-priority condition needs attention.

**Rationale:** Maintenance personnel should see the most actionable abnormal condition first without manually navigating pages. Avoid showing misleading operating states when communications are absent.

**Consequences:** Add a local fault manager, freshness checks, status-write validation, fault-code catalog, deterministic display ordering, and fault-injection tests. Existing sensor measurement addresses remain stable.
