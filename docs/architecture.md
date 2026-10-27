# Architecture

Filled in progressively.

## Stage 0 decisions

| Decision | What / Why | Limitation / future |
|---|---|---|
| FastAPI | Typed request validation (Pydantic) and automatic OpenAPI docs at `/docs`, which doubles as the frontend/backend contract | Async code needs care around blocking calls |
| PyMongo async API (`AsyncMongoClient`) | Current official async driver; works with FastAPI's event loop | Driver connects lazily, so startup does not prove the database is up |
| `/api/health` returns 200 with `status: degraded` when MongoDB is down | Separates "API process alive" from "dependency healthy" | A load balancer may want a stricter readiness endpoint |
| Settings from environment (`pydantic-settings`) | No secrets or URIs in source code | |
| Short MongoDB server-selection timeout (2 s) | Fail fast instead of the driver's 30 s default | Too short for a slow remote cluster; configurable |

## Stage 1 decisions

| Decision | What / Why | Limitation / future |
|---|---|---|
| Layered network model: routes -> service -> store | Routes are thin; rules live in `network_model/service.py`; persistence sits behind a `NetworkStore` interface | More files than a single module, but each is testable alone |
| Same service for API and seed script | Seed data is validated by the same rules as user input | |
| Contract tests run on an in-memory store and the real driver | Proves the Mongo implementation matches the intended behaviour | Needs a MongoDB-protocol server to run the second half (skipped otherwise) |
| Pure functions for addressing and topology | No I/O, so unit tests are fast and exhaustive | |
| Indexes created by a background task with retry | The API starts even when MongoDB is down; indexes appear once it is reachable | Brief window at startup without unique indexes (the service still checks) |
| `DatabaseError -> HTTP 503` handler | A dead database is reported as "unavailable", not a 500 stack trace | |
| Tree topology with typed parent/child rules | Enables upstream-failure reasoning (Stage 3) | No redundant links |

### Modules (backend/app/network_model)

`enums` vocabulary - `errors` domain errors -> HTTP codes - `addressing` IPv4 maths - `models` Pydantic schemas - `topology` tree logic - `store` MongoDB persistence - `service` registration rules - `seed_data` / `seed` demo campus.


## Stage 2 decisions (probe layer)

| Decision | What / Why | Limitation / future |
|---|---|---|
| One `Probe` interface, two implementations | The engine calls `probe(device, settings, upstream=...)` and cannot tell real from simulated; `ProbeDispatcher` picks by `monitoring_mode` | Real results can never be altered by simulated faults (hybrid caveat) |
| `icmplib` as primary real backend | Builds ICMP Echo packets itself, async, returns raw per-reply RTTs so REAL and SIMULATED stats use the same formulas | Needs raw sockets: root/Administrator/CAP_NET_RAW, or on Linux/macOS an OS setting for unprivileged ICMP sockets. icmplib forces raw sockets on Windows |
| System `ping` as automatic fallback | The OS `ping` is already privileged, so it works for ordinary users. Run with an argument list, never a shell | Output parsing depends on the OS and language; Windows ping cannot set the gap between requests; only Linux was tested live |
| Probe ERROR is not packet loss | If no backend can run, the result carries `error` and `loss_pct = None` instead of 100 % | The engine must handle "unknown" (Stage 3) |
| Probe targets validated before use | IPv4 literals only; multicast, broadcast, 0.0.0.0, link-local and reserved are refused (broadcast pings enable amplification) | The API has no authentication, so anyone who can register a device can make the server ping a unicast address |
| Seeded per-device random streams | Same seed gives the same numbers; probing one device never changes another's; toggling a fault never shifts later samples | |
| Fault effects accumulate along the path | Offline upstream means no reply; delays add; per-hop loss compounds (1 - product of (1 - p)) | Educational model, not packet-level simulation |
| Vantage-point reachability path | Dependency of a probe = tree path from the monitoring station's attachment point | One station only |
| Circular import avoided | `app.probes` initialiser stays light; the dispatcher (which imports the simulator) is imported explicitly | |


## Stage 3 decisions (monitoring engine)

| Decision | What / Why | Limitation / future |
|---|---|---|
| Engine runs inside the API process as one asyncio task | Simple to run and debug; the API still only READS results, it never probes. Cleanly separated module, so it can become its own process | If the API process dies, monitoring stops. A separate worker plus a watchdog is the improvement |
| Fixed-rate loop, cycles never overlap | `poll_interval` is the minimum spacing between cycle starts; a slow cycle delays the next one | One slow REAL probe (a dead target waits out its timeouts, about 6 s) stretches every cycle, so detection of simulated faults slows too |
| All devices probed concurrently, bounded to 20 | A cycle lasts as long as its slowest probe, not the sum of all | Hundreds of devices need batching or per-device schedules |
| Evaluate devices nearest the monitoring station first | A device's root cause is known before its dependants are judged, in the same cycle | Needs a tree; redundant links would need graph reachability |
| Pure state machine (`monitoring/state_machine.py`) | No I/O or clock, so every transition is unit-tested | |
| OFFLINE needs N consecutive failed cycles (default 3) | One lost ping must not raise an outage. Worst-case detection time = poll interval x N | Trade-off: faster detection means more false alarms |
| Recovery needs M consecutive good cycles (default 2) | Hysteresis against a flapping device | Slower to show recovery |
| DEGRADED judged on a rolling window (default 5 cycles) | With 5 echoes per cycle one lost echo is 20 % loss; over the window it is 4 %, below the 5 % threshold, so a healthy device does not flicker | After a fault clears, DEGRADED lasts until the window refills (about 3 cycles) |
| Window cleared on recovery | Old outage data would otherwise cause a DEGRADED blip right after recovery | |
| UNREACHABLE means "failing AND an upstream device is OFFLINE" | One alert-worthy root cause instead of one per child | The monitor cannot tell a dead child from a dead parent while the parent is down; the child is re-evaluated when the parent recovers |
| Probe ERROR changes nothing | A broken monitor (no permission, crash) is shown as `monitoring_error`, not as a dead device | Needs an operator to notice the message |
| Latest metrics stored on the device document | Dashboard reads one collection and never scans history | Duplicates the newest measurement |
| `measurements` TTL index (default 26 h) | MongoDB deletes old data by itself; the dashboard needs about 24 h | Not verified on a real MongoDB in my environment, see README |
| Events collection | Every status change with its reason and root cause; Stage 5 alerts are built on these | |
| Runtime configuration in `settings` collection | Poll interval, confirmation counts, window and thresholds change without a restart; read at the start of every cycle | Probe count and timeouts remain environment-only |
| Persisted device state, in-memory window | A restart resumes OFFLINE/UNREACHABLE and the failure counters without duplicate events | The rolling window restarts empty, so DEGRADED is judged again after 3 cycles |
| Misconfigured vantage point skips the cycle | Every dependency decision would be wrong, so the engine refuses to guess and reports the error | |
| Fault injection service + CLI pulled forward from Stage 6 | Needed to demonstrate and test detection now; Stage 6 adds the REST API and UI on the same function | |

### Status state machine

```
UNKNOWN --reply--> ONLINE <--window ok / window bad--> DEGRADED
   |                  |                                    |
   |                  +----- N failed cycles ------+------+
   |                                               v
   +------------- N failed cycles ---------> OFFLINE  <--(upstream offline?)--> UNREACHABLE
                                               |                                    |
                                               +---- M reply cycles ----> ONLINE <--+
```


## Stage 4 decisions (traffic engine)

| Decision | What / Why | Limitation / future |
|---|---|---|
| Rates from cumulative counter differences | `rate = (counter_now - counter_before) x 8 / seconds`; the same method SNMP-based tools use on ifInOctets/ifOutOctets. Utilization = rate / capacity x 100 | Real NMS tools read the counters over SNMP; here they come from the simulator (campus) or psutil (this PC) |
| Simulated counters are 32-bit and start at random offsets | Real Counter32 values wrap (a busy 100 Mbit/s link every ~6 minutes), so the wrap handling is genuinely exercised and tested | At 1 Gbit/s a 32-bit byte counter wraps in 34 s; polling slower than the wrap time loses a lap (why 64-bit HC counters exist) |
| Wrap vs reset | A smaller counter is a wrap, unless that would imply more than 125 % of the link capacity, then it is a reset and the sample is discarded; a decrease of a 64-bit counter is always a reset | A reset that happens to look plausible is misread as a wrap |
| Full-duplex utilization = busier direction / capacity | Capacity applies to each direction separately | |
| Direction convention | download = upstream device to downstream device, upload = the reverse | |
| Traffic of a link = sum of the links behind it (WAN = 70 % of backbone) | Numbers add up from PCs to backbone; blocks resemble the spec's 42 / 18 / 11 Mbit/s at busy hours | Traffic between two devices inside one block is not modelled separately |
| Daily rhythm + AR(1) noise + per-link seeded randomness | Graphs look like real traffic and stay reproducible; faults never shift later values | |
| Faults change traffic consistently with probes | Congestion drives the uplink to the requested utilization (same parameter as the latency/loss model); offline devices and everything cut off behind them carry nothing | Natural high utilization does not (yet) raise latency |
| Protocol mix is SIMULATED and labelled so everywhere | No packet is captured or inspected. DNS = port 53, TCP/UDP exclude DNS | Live capture with scapy is a stretch feature |
| REAL host NIC kept separate from campus traffic | psutil counters of the monitoring computer (non-loopback interfaces); never mixed into campus numbers | Link speed unknown on Wi-Fi/virtual NICs, so no utilization then |
| Traffic engine is its own polling service | Shares the polling loop base class with the monitoring engine; a failing host read never disturbs campus numbers | |
| Latest reading on each link document + history in `traffic_samples` | Dashboard reads one small collection; history has a TTL index | |
| Link state computed when read | down (an end is OFFLINE/UNREACHABLE), congested/busy (utilization vs the configurable thresholds), up | |


## Stages 5-9 decisions

| Decision | What / Why | Limitation / future |
|---|---|---|
| Alert engine is a separate polling service that reads the database | Same pattern as the other engines; rules are pure functions (`alerts/rules.py`) tested without I/O | Alerts lag the monitoring cycle by up to one interval |
| Root-cause suppression by topology | One alert per failure; children listed on it | Tree topology only |
| Evidence rules (at least 3 lost echoes, no loss alerts while failures are being counted) | Removes statistical noise; found by running 24 h of history and seeing 33 alerts instead of 9 | Slightly higher effective loss threshold on small windows |
| Hysteresis + clear delay | Alerts do not flap | Alerts resolve about 3 checks after recovery |
| Fault injection API + scenarios | Demo control; only simulated devices; can be switched off | No authentication (documented) |
| `/api/dashboard/summary` | One call for the KPI strip, computed from stored state | Averages mix REAL and SIMULATED devices; the UI badges say so |
| Demo history generator = real engines in fast-forward on in-memory stores, then bulk write | History is produced by the same logic, not hand-drawn; labelled `demo-backfill` | It is generated data and must be presented as such |
| Frontend: polling hooks + pure helper modules | Layout, chart-data and formatting logic is unit-tested; React Flow and Recharts are smoke-tested in a DOM | No end-to-end browser test |
| Chart data bucketed server-side (`bucket_s`) | Keeps 24 h charts to about 240 points | Averaging hides sub-bucket spikes (worst status is kept) |
