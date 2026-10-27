# Viva preparation

Format per topic: WHAT / HOW / WHY / INTERNALS / LIMITATIONS / IMPROVEMENTS. Grows each stage.

## Stage 1: network model

### Subnet validation and the calculator
- **What:** validates CIDR input and reports network, mask, wildcard, broadcast, usable range.
- **How:** Python `ipaddress.IPv4Network`. The mask is `prefix` ones followed by zeros; the broadcast address is the network address with all host bits set; usable hosts = 2^(32 - prefix) - 2.
- **Why:** reusing the standard library avoids hand-written bit errors; the same code validates device IPs and the calculator endpoint.
- **Internals:** `192.168.10.5/24` is rejected in strict mode because host bits are set; the calculator uses non-strict mode and reduces it to `192.168.10.0/24`, like a classroom subnet calculator.
- **Limitations:** IPv4 only; no VLSM planner; no IPv6.
- **Improvements:** IPv6 support, automatic subnet allocation.

### Q: Why /24 for each block?
254 usable hosts is enough for a lab/department, keeps each block its own broadcast domain, and the third octet (10/20/30) is easy to read in a demo. A real campus might use larger or smaller prefixes per VLAN.

### Q: Why /30 for the router-core link?
Two usable addresses are all a point-to-point link needs. See `network-topology.md`.

### Q: What is a broadcast domain? How many do we have?
The set of devices that receive a layer-2 broadcast (for example an ARP request). One per subnet: CSE, Library, Admin, plus the tiny link subnet. The core L3 switch separates them, so broadcasts do not cross blocks.

### Q: How does traffic go from the CSE subnet to the Library subnet?
The CSE PC sees the destination is outside 192.168.10.0/24, ARPs for its gateway 192.168.10.1 (core L3 switch), sends the frame there, the core looks up the route to 192.168.20.0/24 (directly connected) and forwards it out its Library interface. Modelled, not simulated packet by packet.

### Q: Why a Layer 3 switch rather than a router at the core?
See `network-topology.md`: wire-speed inter-subnet routing, one gateway device for all blocks.

### Q: Why does a switch have an IP address?
Management plane only; forwarding still uses MAC addresses.

### Q: Why private addresses (RFC 1918)?
They are not routable on the public Internet, so campus hosts reach the Internet through NAT at the edge. The code rejects non-RFC 1918 campus subnets. Note Python's `is_private` also includes other reserved ranges, so we check the three RFC 1918 blocks explicitly.

### Q: Why is the topology a tree?
Each device has one upstream parent. That makes "if the CSE switch fails, its 5 children are unreachable because of it" a simple descendant lookup, which lets us raise one meaningful alert later instead of six. Limitation: real campuses have redundant links (loops, spanning tree, ECMP); a tree cannot model redundancy.

### Q: Are the MAC addresses real?
No. They are deterministic, simulated, locally administered addresses (first octet 02). They illustrate layer 2; nothing sends frames.

### Q: Which parts are real and which are simulated?
Real: IP arithmetic and validation, the database, the API. Simulated: all campus devices, MACs, RTT parameters, capacities. The Internet node is configured as a real probe target for Stage 2.

### Q: Why can a "real" device have a different probe_target than its IP?
Our modelled IP (for example 192.168.10.101) does not exist on the monitoring host's network. To monitor a real laptop we record the address we can actually reach (`probe_target`) while keeping the modelled position in the topology. Only IPv4 literals are accepted, never hostnames or free text, which blocks command injection into later `ping` calls.

### Q: How do you stop duplicate IPs?
Two layers: the service checks first (clear message), and a unique MongoDB index on `ip` guarantees it even under concurrent requests.

### Q: Why MongoDB?
Flexible documents suit device attributes that differ by type, and the team knows it. Honest trade-off: relational integrity (foreign keys) is enforced in the service layer, and a time-series database would suit measurements better at large scale.

### Q: What if registering a device half-fails?
Standalone MongoDB has no multi-document transactions, so the service inserts the device, then its link, and deletes the device again if the link insert fails. Limitation: a crash between the two writes could leave an orphan; a replica set with transactions would fix this.


## Stage 2: probe layer

### Evidence that the REAL probe is real
Captured on the loopback interface while `RealIcmpProbe` ran (3 echo requests). The probe reported 3 sent, 3 received.
Each packet appears twice because a packet capture on loopback sees both the outgoing and the incoming copy.

```
src        dst        ttl type          id   seq  ip_len
127.0.0.1  127.0.0.1  64  8 Echo Request 363  0    84
127.0.0.1  127.0.0.1  64  0 Echo Reply   363  0    84
127.0.0.1  127.0.0.1  64  8 Echo Request 363  1    84
127.0.0.1  127.0.0.1  64  0 Echo Reply   363  1    84
127.0.0.1  127.0.0.1  64  8 Echo Request 363  2    84
127.0.0.1  127.0.0.1  64  0 Echo Reply   363  2    84
```
84 bytes = 20 (IP header) + 8 (ICMP header) + 56 (payload). To show the same in Wireshark use the display filter `icmp`
and ping a device on a real network (for example a phone on a hotspot); loopback traffic on Windows needs the Npcap loopback adapter.

### Q: What does ping actually measure?
Round-trip time of an ICMP Echo Request/Reply: the time from sending the request until the matching reply arrives.
It includes propagation, queueing, and the target's time to generate the reply. It is not one-way delay and not throughput.

### Q: Is ICMP TCP or UDP?
Neither. ICMP is its own IP protocol (protocol number 1), carried directly inside IP datagrams. It has no ports and no handshake.
It belongs to the network layer: it reports errors and does diagnostics for IP. Echo Request is type 8 and Echo Reply is type 0.

### Q: Why isn't ping failure proof the device is down?
Firewalls often drop ICMP, routers rate-limit or deprioritise it, and the path may be congested. A device can serve TCP traffic perfectly
while ignoring ping. We reduce false alarms with several echoes per cycle and (Stage 3) a confirmation count of consecutive failed cycles.
A TCP-connect check against a service port is a planned Core+ improvement.

### Q: How is packet loss calculated?
`loss % = (sent - received) / sent x 100`, from echo requests sent versus replies received in one probe.
Limitation: with 5 echoes per cycle the resolution is 20 %, so we will smooth over several cycles when charting.

### Q: What is jitter, and how do you compute it?
Variation in delay. We use the mean absolute difference between consecutive RTTs (needs at least 2 replies). RFC 3550 uses a smoothed
estimator and Linux `ping` prints `mdev` (standard deviation), so numbers will not match those tools exactly. We define it and say so.

### Q: Why does the probe need root or Administrator?
`icmplib` crafts the ICMP packet itself, which needs a raw socket. Raw sockets could forge arbitrary packets, so the OS restricts them.
Linux and macOS also allow ICMP datagram sockets for ordinary users if the OS permits (Linux sysctl `net.ipv4.ping_group_range`); then the kernel builds the header.
The system `ping` program is already privileged, so our fallback uses it.

### Q: What happens if neither works?
The probe returns an ERROR result, not "100 % loss". A broken monitoring tool must not look like a dead network. The engine will report
"monitoring unavailable" for that device instead of raising a device-offline alert.

### Q: How do you stop command injection?
The target must parse as an IPv4 literal (Python `ipaddress`) before it reaches any socket or subprocess. The subprocess is started with an argument list
(`create_subprocess_exec`), never through a shell, and the address is the last argument. Strings like `1.1.1.1; rm -rf /` or `-f` are rejected.

### Q: Why can't I configure a broadcast or multicast probe target?
Pinging a broadcast address makes every host on that network reply (the amplification idea behind the "smurf" attack). We refuse multicast,
broadcast, unspecified, link-local and reserved addresses. Loopback and private addresses are allowed for demos.

### Q: Which parts are real and which are simulated?
Real: Internet node (and any device you register with `monitoring_mode=real` and a reachable `probe_target`). Simulated: all other devices.
Every result carries `source` (`real` or `simulated`) which the UI shows as a badge. A simulated fault can never change a real measurement.

### Q: How does the simulator work?
Per echo it draws random numbers from a per-device seeded generator: a loss draw, Gaussian noise (10 % of the mean RTT), and a rare spike.
Faults change the model: OFFLINE drops everything; HIGH_LATENCY raises the mean RTT to a target (default 180 ms); PACKET_LOSS sets a loss probability (default 12 %);
CONGESTION adds queueing delay `service_time x rho / (1 - rho)` with `rho = utilization` (capped at 0.99) and starts dropping packets above 90 % utilization.
This is an educational approximation of a single queue, not a packet-level simulator.

### Q: What happens to devices behind a failed switch?
The simulated probe combines effects along the path from the monitoring station: an offline device upstream means no reply downstream, delays add, and
per-hop loss compounds. So the PCs behind a dead switch show 100 % loss too, exactly what a real monitor would see. Stage 3 uses the topology to explain why.

### Q: Why is the monitoring station at the core switch?
A monitor inside the campus does not depend on the Internet link. If the Internet is down, campus devices are still reachable; if the core switch is down, nothing is.
See `network-topology.md`. Limitation: one vantage point.

### Q: Why does the same seed give the same results?
Repeatable demos and tests. Each device has its own stream seeded from `seed:device-id`, and every echo consumes the same four random numbers whether or not a
fault is active, so injecting a fault does not change what happens afterwards.

### Q: Why did you reject a probe of 255.255.255.255 and how is that tested?
Unit tests cover multicast, broadcast, 0.0.0.0, link-local, malformed and injection-style strings, and assert no backend is ever called.


## Stage 3: monitoring engine

### Q: How does the monitoring engine work?
Every `poll_interval` seconds it loads the device list and settings, probes every device concurrently (real ICMP or simulator), evaluates each device with a
state machine, and stores measurements, the new device state and any status-change events in MongoDB. The dashboard only reads MongoDB.

### Q: Why doesn't the API probe when the dashboard asks?
Probing on request would make results depend on how many people watch the dashboard, add load to the network, and make every page load slow. Measuring on a fixed schedule
gives evenly spaced samples (needed for charts), and many viewers cost nothing extra.

### Q: How do you avoid false alerts?
Four mechanisms: several echoes per cycle; OFFLINE only after N consecutive failed cycles; DEGRADED judged over a rolling window rather than one cycle; and recovery only after M good cycles (hysteresis).
Alerts (Stage 5) are built on confirmed status changes, not on single measurements.

### Q: How fast do you detect a failure?
At worst `poll_interval x failure_confirmations` (default 5 s x 3 = 15 s), plus the probe time of the cycle. The API reports this as `detection_time_s`. Lowering it means more false alarms.

### Q: What happens when a switch fails?
Its own probes fail, and so do the probes of everything behind it, because they pass through it. After N cycles the switch becomes OFFLINE. In the same cycle, devices behind it that are also
failing are marked UNREACHABLE with `caused_by` set to the switch, because the monitor evaluates the devices closest to it first. One root cause, N dependants, instead of N+1 identical alarms.
(Demo result: CSE Switch OFFLINE and its 5 devices UNREACHABLE: 6 events, 1 root cause.)

### Q: How does the monitor know a device is "behind" another?
From the topology. The monitoring station sits at the core switch; the devices a probe passes through are the tree path from the core to the target (`reachability_path`).
The Internet being down does not make the campus unreachable, but the core switch being down makes everything unreachable.

### Q: Can UNREACHABLE be wrong?
It is an inference: while the parent is down we cannot know whether the child is also broken. When the parent recovers and the child still does not answer, the child turns OFFLINE (its own fault).
That case is covered by a test. The model is also limited to tree topologies; redundant links would need graph reachability.

### Q: Packet loss is 0 % but status is DEGRADED. Why?
DEGRADED looks at windowed average latency as well as windowed loss. A device can answer every echo slowly (for example 180 ms against a 100 ms warning threshold).

### Q: One echo out of five was lost; why is the device still ONLINE?
That is 20 % loss in one cycle but 4 % over the 25 echoes of the 5-cycle window, under the 5 % warning threshold. We smooth deliberately; the cost is that real problems need a few cycles to show.

### Q: What if the monitoring tool itself breaks (no ICMP permission)?
The probe returns an ERROR, the device keeps its previous status, and `monitoring_error` is shown. It is never counted as packet loss or an outage.
Test: a device whose probe errors for 6 cycles stays ONLINE.

### Q: What is "uptime" here?
The time the monitor has continuously seen the device answer (`up_since`, set when it enters ONLINE/DEGRADED, cleared when it goes OFFLINE/UNREACHABLE). It is not the device's operating-system uptime
(that would need SNMP or an agent).

### Q: Are the thresholds standards?
No. They are configurable system defaults (latency warning 100 ms, loss warning 5 %, ...) stored in the `settings` collection and changed through `PUT /api/monitoring/config` without restarting; the engine reads them each cycle.

### Q: What happens if MongoDB goes down while monitoring runs?
The cycle fails with a logged error ("database unavailable"), the loop keeps running and retries next interval; the API returns 503 for data routes. Nothing is half-written because writes happen at the end of a cycle.
Limitation: the cycle's measurements are lost, not buffered.

### Q: What happens when the engine restarts?
Device status and failure counters are persisted, so an OFFLINE device stays OFFLINE and no duplicate event is created. The rolling window restarts empty, so DEGRADED is judged again after 3 cycles.

### Q: What if the monitoring server itself fails?
Monitoring stops and nothing alerts about it: the monitor is a single point of failure. The `/api/monitoring/status` endpoint shows the time of the last cycle and the dashboard flags "Engine stalled" if it is old.
A real deployment would add a second monitor or an external watchdog.

### Q: How does this scale?
Probes run concurrently (limit 20), so a cycle takes about as long as the slowest probe. For hundreds of devices: batch probing, per-device schedules, multiple pollers, and a time-series database for measurements.
Storage today: 17 devices x one document per 5 s is about 300 000 documents per day, expired by the TTL index.

### Q: Why is the Internet node shown as OFFLINE on some networks?
It is a REAL probe of a public address (default 1.1.1.1). Some campus networks block outgoing ICMP, so the probe gets no reply even though the Internet works. That is exactly the "ping failure is not proof of an outage" limitation.
Choose another reachable target with `python -m app.network_model.seed --reset --internet-target <ip>`.

### Q: Simulated faults can't affect real devices. Isn't that inconsistent?
Yes, and it is the honest consequence of a hybrid system. If the simulated core switch is "offline", the REAL Internet probe still answers because it travels over the real network. We keep it that way instead of faking a real result.


## Stage 4: traffic engine

### Q: How is bandwidth (throughput) measured?
Devices keep cumulative counters of bytes and packets sent and received. Every sample we read them, subtract the previous reading and divide by the elapsed time:
`rate = delta_bytes x 8 / delta_seconds`. Example: 6,250,000 bytes in 5 s = 10 Mbit/s. Counters are used because a device cannot report "current speed" directly, and subtraction is cheap and exact.
In production this is what SNMP polling of `ifInOctets`/`ifOutOctets` does; we read the same kind of counters from the simulator and, for this computer, from the operating system (psutil).

### Q: Bandwidth vs throughput vs utilization?
Bandwidth (capacity) is the maximum the link can carry (we store it per link in Mbit/s). Throughput is what actually flows (our measured rate). Utilization = throughput / bandwidth x 100.
We use the busier direction because a full-duplex link has its full capacity in each direction.

### Q: What is counter wrap and how do you handle it?
A fixed-width counter overflows and restarts at 0 (a 32-bit counter at 4.29 GB). If the new value is smaller than the old one we add the missing lap: `(2^32 - old) + new`. Our simulated counters are 32-bit on purpose, so wraps happen every few minutes and the tests prove the rates stay correct.
Limitation: if the counter wraps twice between two readings the second lap is invisible; at 1 Gbit/s a 32-bit byte counter wraps every 34 s, which is why modern devices offer 64-bit counters.

### Q: How do you tell a wrap from a device reboot (counter reset)?
Both look like "the counter went down". If treating it as a wrap gives a rate above 125 % of the link capacity, it is physically impossible, so we call it a reset and discard that sample rather than plot a fake burst. A 64-bit counter takes decades to wrap, so any decrease is a reset.

### Q: Is the traffic real?
The campus traffic (links, blocks, protocol mix) is SIMULATED and labelled so. One panel is REAL: the network counters of the computer running the monitor, read with psutil. They describe that computer, not the campus, and are never added to the campus numbers.

### Q: How does the simulated traffic behave?
Each PC, access point and server link carries traffic with a daily rhythm and smoothly drifting noise; every other link carries the sum of the links behind it, so a switch uplink is the sum of its devices and the backbone the sum of the blocks.
The WAN carries 70 % of the backbone traffic. A link cannot exceed its capacity. Offline devices (and anything behind them) go silent; a congestion fault drives a link to the requested utilization.

### Q: How is congestion connected to latency and loss?
One parameter, `utilization_pct`, feeds both models. The traffic model sets the link to that utilization; the probe model adds queueing delay `service_time x rho / (1 - rho)` and starts dropping packets above 90 % (rho = utilization). At 95 % that is about +76 ms and 7.5 % loss, so the device turns DEGRADED while the link shows CONGESTED.
Why: when a link nears saturation its queues fill, which adds delay first and then forces drops. Limitation: a simplified single-queue model, and natural high utilization does not yet raise latency.

### Q: How is traffic by campus block calculated?
The block's uplink is the link between the core switch and that block's switch; it carries everything the block sends and receives. Block total = download + upload on that link; block utilization = busier direction / link capacity.

### Q: What does the protocol chart show and how real is it?
TCP, UDP, DNS (port 53, UDP or TCP), ICMP and other, as shares of bytes. It is SIMULATED: servers are TCP-heavy, access points carry more UDP (voice/video), and so on. No packet is captured or inspected, and the chart says so. Real classification would use packet capture (scapy/Wireshark) and the IP protocol number (TCP 6, UDP 17, ICMP 1) plus ports.

### Q: Why is the first sample missing after a restart?
A rate needs two readings, so the first cycle only records counters. Likewise a counter reset costs one sample.

### Q: How would you detect unusual traffic?
Planned for later: compare each link's rate with its own rolling baseline (mean and standard deviation) and flag large deviations. That is statistics, not AI, and the stored history already supports it.

### Q: Why store both the latest values on the link and a history?
The dashboard polls every few seconds and needs only the newest values (one small collection). Charts need history, which lives in `traffic_samples` and expires by itself after the retention period.


## Stage 5: alerts

### Q: When is an alert raised?
Four types: DEVICE_OFFLINE (status OFFLINE), HIGH_LATENCY and HIGH_PACKET_LOSS (windowed values above the warning / critical thresholds) and HIGH_UTILIZATION (a link above its thresholds). Thresholds are configurable settings (stored in MongoDB, changed with `PUT /api/monitoring/config`), not networking standards.

### Q: How do you avoid alert storms?
Five mechanisms: (1) alerts are built on debounced status and windowed averages, not single measurements; (2) de-duplication: one open alert per key such as `DEVICE_OFFLINE:cse-switch`, updated in place; (3) root-cause suppression: devices that are UNREACHABLE because of a failed switch get no alert, they are listed on the switch's alert; latency/loss on a device is hidden when an upstream device has the same problem; (4) hysteresis: an open alert stays open until the value is below threshold x 0.9; (5) a clear delay: it resolves only after the condition has been gone for 3 checks, so a value flickering around a threshold stays one alert. Loss alerts also need at least 3 really lost echoes, because even a healthy path loses an occasional echo.

### Q: Why did you add the minimum of 3 lost echoes?
Our first demo-history run produced 33 alerts instead of about 9: with 5 echoes per cycle and a 5-cycle window, two lost echoes out of 25 look like 8 % loss, above the 5 % threshold. A healthy path drops 0.2 % of echoes, so over thousands of windows that happens. Requiring real evidence removed the noise. This is a good example of a statistical false-positive problem in monitoring.

### Q: What is hysteresis?
Different thresholds for opening and closing, like a thermostat. Without it a value hovering at the threshold would open and close alerts every cycle.

### Q: What does "acknowledge" do?
Marks that a human has seen the alert. It does not resolve it; resolution is automatic when the condition clears.

### Q: What does an alert contain?
Type, severity, device and link, message with the numbers, metrics snapshot with the peak value, opened/updated/resolved times, last response time, the devices cut off behind it, acknowledgement, and the de-duplication key.

## Stage 6: fault simulation

### Q: How does fault injection work?
The API (or CLI) writes a `sim_state` (fault type and parameters) on a SIMULATED device. The simulator reads it on the next probe, so the monitoring engine detects it through its normal path. Nothing tells the engine a fault exists.

### Q: Can you inject a fault into a real device?
No, the API refuses (HTTP 422). A simulated fault must never alter a real measurement. Fault injection can be disabled entirely with `SIMULATION_ENABLED=false`, and as it has no authentication it is a demo tool, not for an exposed deployment.

### Q: What do the four faults model?
OFFLINE: every echo is lost. High latency: mean RTT raised to a target (default 180 ms). Packet loss: each echo lost with a probability (default 12 %). Congestion: utilization (default 95 %) adds queueing delay `service_time x rho / (1 - rho)` and causes loss above 90 %; the traffic model drives the link to the same utilization.

## Stages 7-9: dashboard, topology, charts

### Q: How does the dashboard get its data and why not WebSockets?
It polls REST endpoints every 3 seconds. The API only reads what the engines stored. Polling is simple, robust and easy to explain; WebSockets would reduce latency and are a documented improvement.

### Q: How is the topology drawn?
React Flow renders nodes and edges. A small deterministic tree layout centres each parent over its children. Node colour is the device status (grey = unreachable because of an upstream failure); edge colour, width and label show link utilization and state.

### Q: Why can the history before the demo loader ran be trusted?
It cannot be treated as real, and the system says so: the demo loader runs the same engines in fast-forward over a scripted incident timeline, labels the data (backend `demo-backfill`, never REAL), shows a banner with the load time, and replaces itself only when asked. It exists so charts are not empty on presentation day.

## Master list: the questions in the assignment brief

| Question | Short answer |
|---|---|
| Is this real monitoring or simulation? | Hybrid. The monitoring pipeline is real; the campus devices are simulated. Real: ICMP to real hosts (Internet node, any laptop you register), this computer's NIC counters, IP/subnet maths. Simulated: campus devices, their RTT/loss, link traffic, protocol mix, faults. Every metric carries a REAL / SIMULATED badge. |
| What does ping measure? | Round-trip time of an ICMP echo request/reply, plus whether a reply arrives at all (Layer 3 reachability). |
| Is ICMP TCP or UDP? | Neither: its own IP protocol (number 1), no ports. |
| Why does a switch have an IP? | Management plane only; forwarding uses MAC addresses. |
| What happens when ping fails? | The failed cycle is counted; OFFLINE needs 3 consecutive failed cycles; UNREACHABLE if an upstream device is OFFLINE; a probe that could not run is a monitoring error, never an outage. |
| Why isn't a ping failure proof the device is down? | Firewalls and rate limiting drop ICMP, and a path problem looks the same. We use several echoes, confirmations, and topology reasoning; a TCP check is the planned improvement. |
| How is packet loss calculated? | (sent - received) / sent x 100. |
| What is jitter? | Variation in delay; we use the mean absolute difference of consecutive RTTs. |
| How is bandwidth calculated? | From counter differences: delta bytes x 8 / delta seconds; utilization = rate / capacity x 100. |
| Bandwidth vs throughput? | Capacity versus what actually flows. |
| Why /24 and /30? | /24: 254 hosts per block and its own broadcast domain; /30: exactly 2 usable addresses for the point-to-point link. |
| What is a broadcast domain? | Devices that receive a layer-2 broadcast; one per subnet. |
| How does one subnet talk to another? | Via the default gateway (the core L3 switch), which routes between its connected subnets. |
| Why a Layer 3 switch? | Wire-speed routing between subnets in one device; the edge router then only handles the WAN. |
| Why not SNMP? | Simulated devices have no agents and no real switches were available; we reproduce SNMP's counter-difference method. SNMP is the named improvement. |
| Why MongoDB? | Flexible documents for per-type device attributes, TTL indexes for history, async driver, team knowledge. Trade-off: a time-series database scales better for measurements. |
| How would this scale? | Concurrent probes (limit 20) now; batching, per-device schedules, several pollers, a time-series database and WebSockets later. |
| What if the monitoring server fails? | Monitoring stops and nothing alerts: a single point of failure. The dashboard shows "Engine stalled"; a second monitor or an external watchdog is the fix. |
| How do you avoid false alerts? | See the Stage 5 answer: debounce, windows, evidence, dedupe, suppression, hysteresis, clear delay. |
| How does fault injection work? / Which parts are real or simulated? | See Stage 6 and the first row. |

## Questions a faculty member may challenge, with the honest answer
1. *"Your devices do not exist, so what are you actually monitoring?"* The pipeline: scheduling, probing, statistics, state machine, dependency reasoning, alerting, visualisation. Real ICMP works against any reachable host; the simulation lets us demonstrate failures that cannot be caused on demand in a real campus.
2. *"Is the protocol chart real?"* No, it is labelled SIMULATED and says no packets are inspected. Real classification needs packet capture (scapy/Wireshark) and port/protocol numbers; it is a stretch feature.
3. *"The congestion model is too simple."* Yes: a single-queue approximation (M/M/1-like). It reproduces the right shape (delay grows sharply as utilization nears 100 %, loss begins near saturation) and is documented as educational.
4. *"A simulated core failure still leaves the real Internet node green."* Correct and deliberate: a simulated fault never alters a real measurement.
5. *"Counters in your simulator are 32-bit, is that realistic?"* Yes for classic SNMP ifInOctets; it is chosen so wrap handling is exercised. 64-bit counters are supported too.
6. *"What is detection time?"* Poll interval x confirmations, about 15 s with the defaults (5 s x 3), shown by `/api/monitoring/status`.
7. *"Why are there alerts for congestion on a switch for latency and loss too?"* Congestion really causes all three; the engine keeps them as separate, related alerts with the same root device.
8. *"What happens to the data when MongoDB is down?"* The engines log and retry each cycle and the API returns 503; cycles during the outage are lost (no buffering).
