# Fault-code catalog — initial draft

Fault codes are stable machine-readable identifiers. Human-facing descriptions are rendered locally. Codes below are provisional until controller implementation. Do not reuse retired numbers.

| Code | Source | Default severity | Description |
|---|---|---|---|
| 0 | controller | none | No active fault |
| 1001 | controller | critical | High RO feed pressure interlock |
| 1002 | controller | critical | Concentrate flow below configured limit during production |
| 1003 | controller | critical | Critical sensor data unavailable during production |
| 1004 | controller | critical | High-high storage level / overflow interlock |
| 1005 | controller | critical | RS485 sensor-node communications timeout during production |
| 2001 | controller | warning | Membrane rejection below configured warning limit |
| 2002 | controller | warning | Abnormal RO pressure trend |
| 3001 | controller | advisory | Maintenance or calibration due |
| 4001 | sensor | critical when required | Critical local measurement invalid or stale |
| 4002 | sensor | warning | Sensor degraded / inconsistent readings |
| 4003 | sensor | advisory | Controller status unavailable |
| 4004 | sensor | advisory | LCD communication failure (log only when display absent) |

A local sensor fault's effective severity depends on whether the measurement is required in the current operating state. If controller state is unknown, do not assume the system is in production or safe; display sensor invalidity clearly and let main-controller safety logic decide shutdown. Code catalog and on-screen strings should be version-controlled.
