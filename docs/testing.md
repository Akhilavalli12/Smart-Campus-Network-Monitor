# Testing

## How to run
```bash
cd backend && pytest          # backend (runs the MongoDB-backed tests too when a server is reachable)
cd frontend && npm test       # frontend
```

## What is covered

| Area | Tests |
|---|---|
| Addressing / subnetting | CIDR parsing, /24 /30 /31 /32 maths, RFC 1918, usable hosts, probe-target safety, MAC generation |
| Network model | registration rules, uniqueness, topology tree, reachability paths from the monitoring station |
| Probes | loss and jitter formulas, ping output parsing (Linux real output, Windows/macOS samples), command construction, backend fallback, injection-style targets, real ICMP to localhost |
| Simulator | RTT/loss/congestion models, path effects, determinism, independence of per-device streams |
| Status state machine | confirmations, hysteresis, windows, evidence rule, upstream failure, monitoring errors, recovery |
| Monitoring engine | scenarios: device failure, upstream failure, core failure, Internet outage, latency, loss, congestion, recovery, restart, crashing/timeout probes, runtime config, DB outage loop |
| Counters / traffic | delta, 32-bit wrap, reset detection, rate maths, congestion/offline effects, sum-of-children, host NIC (fake psutil), counter wrap over 35 simulated minutes |
| Alerts | grading, hysteresis, evidence, suppression, dedupe, clear delay, peak tracking, every scenario opens and resolves its alert |
| API | every route, validation errors (422), 404, 409, 403 (simulation disabled), 503 (database down) |
| Persistence | the same contract tests run on the in-memory stores and on the real driver |
| Demo data | generation, labelling, incidents and alerts, no false alarms, reproducibility, write/replace in MongoDB, served by the API |
| Frontend | topology layout, edge colours, chart helpers, KPI logic, form logic, formatting, render tests, and real React Flow / Recharts mounting in a DOM |

## Mutation checks
I broke the code on purpose and confirmed the tests fail: needing an extra failure before OFFLINE, ignoring upstream devices, counting probe errors as failures, wrapping counters incorrectly, and a wrong unit in the rate formula.

## Not verified (be upfront about these)
* TTL (expiry) indexes: the MongoDB-compatible server used for my tests does not implement them; verify with `db.measurements.getIndexes()`.
* Windows and macOS: `ping` output parsing and the `.bat` scripts were not run on those systems.
* No browser-level end-to-end test; the UI was verified through render tests, a DOM mount of the two heavy libraries, and the production build.
* Real ICMP to the Internet could not run in my sandbox (no outbound ICMP).
