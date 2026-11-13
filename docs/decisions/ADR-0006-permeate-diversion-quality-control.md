# ADR-0006: Permeate diversion is a quality control, not a fail-safe

**Status:** Proposed (2026-11-12) — pending owner review. Supersedes the "fail-to-drain" diversion wording in `docs/safety/SAFETY_REQUIREMENTS.md`, `hardware/plumbing/PROCESS_AND_INSTRUMENTATION.md`, `docs/test/ACCEPTANCE_TEST_PLAN.md`, and `AGENTS.md` rule 3.

**Decision:** Permeate is plumbed membrane -> gross permeate flow/temp -> permeate EC -> tee -> atmospheric tank. A normally closed (NC) solenoid valve on the tee's drain branch (relay K3) redirects permeate to waste when energized. Unpowered, the valve is closed and permeate flows to the tank. There is no fail-to-drain behavior and no 3-way valve. The main controller dumps permeate until EC is acceptable (startup slug) and during permeate-quality faults (failing membrane), then de-energizes K3 to fill the tank.

**Rationale:** Diversion is wanted to keep startup slug and failing-membrane permeate out of the tank, not to protect against controller failure. A single NC valve is the simplest hardware that achieves that. On reset or comms loss the pump contactor (K1) is de-energized and the concentrate bypass (K2, normally open) opens, so no permeate is produced regardless of K3 state.

**Consequences:**
- Residual risk: controller alive but logic wrong, K3 stuck closed, or sensor wrong while the pump runs -> bad permeate reaches the tank with no independent catch. Mitigated only by EC validity/staleness inhibits (AGENTS.md rule 4) and tank EC monitoring if added later.
- With K3 de-energized and the drain branch open to atmosphere, flow splits by path resistance; some permeate may still reach the tank during a dump. A low-cracking-pressure check valve (about 0.5–1 psi) on the tank branch after the tee is recommended. TBD: confirm and size.
- Permeate back pressure: highest point of the permeate line is about 5 ft above the membrane permeate port (about 2.2 psi static). Typical spiral-wound limit is permeate pressure <= feed/concentrate pressure + about 5 psi at all times. Budget sensor friction and check-valve cracking pressure. TBD: verify the limit in the membrane datasheet (model TBD); keep highest line point <= 5 ft unless re-verified.
- Shutdown (K2 opens, feed side depressurizes while permeate head remains) is the governing back-pressure case, not running pressure.
- Open-by-default drain is not provided; a stuck or failed-open K3 wastes product but is not unsafe.
- Sensor node remains measurement-only and never actuates K3 (`SENSOR_NODE_MODBUS_RS485_SPEC.md`). The flow sensor stays upstream of diversion and counts gross membrane output.

**TBD (do not guess):** EC acceptance threshold for switching dump -> tank; maximum continuous dump time and the fault raised on timeout (new catalog code); startup dump duration; NC valve model, pressure rating, coil voltage and duty cycle (energized for the whole dump, which may be minutes after every start); drain-branch air gap/routing; check-valve model; membrane model and its datasheet back-pressure limit.
