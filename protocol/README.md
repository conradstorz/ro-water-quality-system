# Protocol source of truth
`register_map.yaml` is the normative contract. All addresses are zero-based PDU offsets. Read measurement registers with function 04. Holding registers use function 03 and are read-only in release 0.1. Use generated constants and codecs in both firmwares. Never silently reinterpret register types or scales.

Enums, controller-flag bits and the fault-code catalog are machine-readable in register_map.yaml; host_tools tests fail if the markdown tables drift from it.
