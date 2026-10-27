# Demo script (10 minutes)

## Before you present (10 minutes ahead)
1. Start MongoDB (Docker: `docker compose up -d mongo`).
2. `setup` once, then `start` (`start.bat` on Windows). The first start generates 24 hours of demo history (about 15 s). If the **Internet (ISP)** row shows OFFLINE (or an Internet alert appears), your network blocks ping to 1.1.1.1. Stop the app, then from `backend` (venv active) run one of:
   `python -m app.network_model.seed --reset --internet-target <your router or 8.8.8.8>` (keeps one REAL ping), or
   `python -m app.network_model.seed --reset --internet-simulated` (no real pings at all: safest for a lab without internet access), then `python -m app.demo`, and start again.
3. Open http://localhost:5173. Wait about 30 seconds so the live engines have run several cycles.
4. Optional but impressive: open Wireshark on your Wi-Fi/Ethernet interface with the display filter `icmp`. Every 5 seconds you will see real Echo Requests/Replies to the Internet node.
5. Check: Dashboard shows 17 online, 0 alerts, charts filled. If not, re-run `python -m app.demo` (it replaces the history) and refresh.

## The story

| Step | You do | The screen shows | What to say |
|---|---|---|---|
| 1 | Dashboard tab | KPI strip, topology, charts, device table | "This is a mini Network Operations Center for a campus: CSE block, Library, Admin, a core Layer 3 switch and an edge router to the Internet." |
| 2 | Point at the colours | All nodes green, link labels show utilization | "Green means ONLINE. Link colour and width show how busy each link is." |
| 3 | Point at REAL / SIMULATED badges | Badges on every metric | "Only the Internet node and my computer's network interface are real measurements. The campus devices are simulated and labelled, because our fictional campus has no physical hardware." |
| 4 | Click **CSE Switch** | Drawer: IP 192.168.10.2, latency, loss, jitter, packets, uplink traffic, uptime, last seen, 4 charts | "Latency comes from ICMP echo round-trip times; packet loss is (sent minus received) over sent; bandwidth comes from interface counter differences." |
| 5 | Scroll the drawer, switch 1 h / 6 h / 24 h | 24 hours of history with shaded outage periods | "This history is generated demo data from the same engines run in fast-forward, so you can see earlier incidents. Everything after the banner time is live." |
| 6 | **Alerts** tab, "Resolved" | 9 past alerts with peaks and durations | "Each earlier incident produced alerts that opened and resolved automatically." |
| 7 | **Traffic** tab | Blocks (CSE 42-ish Mbps...), WAN, backbone, this PC's NIC (REAL), protocol bar (SIMULATED) | "Traffic by block, and the protocol mix, which is clearly labelled simulated: we do not inspect packets." |
| 8 | **Simulation** tab, scenario **CSE switch fails** > Run | Message: engine should detect within about 15 s | "I am breaking the CSE switch. The monitor does not know; it has to detect it by itself." |
| 9 | Back to **Dashboard** (or Topology) and watch (about 15-20 s) | CSE Switch turns **red**, its 5 devices turn **grey**, KPI "Offline 1 (+5 unreachable)", Alerts badge shows 1 | "It waited for 3 failed probe cycles so one lost ping cannot raise an outage. The devices behind the switch are not marked offline; they are unreachable because of it, so there is ONE alert naming the root cause." |
| 10 | **Alerts** tab | "CSE Switch is unreachable. Packet loss: 100%. Last response: hh:mm:ss. 5 downstream device(s) are cut off by this failure." | "Layer 3 reachability, ICMP, and topology dependency together." |
| 11 | Click **Acknowledge** (optional) | Flag changes | |
| 12 | **Simulation** > **Recover everything** | Cleared | "Now I restore it." |
| 13 | Watch about 10-15 s | Green again, alert turns resolved, Status changes feed shows the recovery | "Recovery needs 2 good cycles, so a flapping device does not bounce." |
| 14 | Optional second scenario: **Network congestion** | Admin uplink turns red, utilization alert, Admin devices get slower | "Congestion: as utilization nears 100 percent queues fill, delay rises and then packets are dropped." |
| 15 | Show `docs/uml` and `docs/viva.md` | | Close with the concepts below. |

## Concepts to name while demoing
OSI layers (switches = layer 2, subnets/ICMP/routing = layer 3, TCP/UDP classification = layer 4, DNS/HTTP = application), IP addressing and subnetting (/24 per block, /30 link), ICMP, RTT, jitter, packet loss, bandwidth vs throughput vs utilization, congestion, fault detection, network monitoring.

## If something goes wrong
| Symptom | Fix |
|---|---|
| Blank page / "Cannot reach the backend" | Backend not running: check the backend window; the Connection tab shows API and MongoDB status |
| MongoDB error on start | Start MongoDB (`docker compose up -d mongo`) or fix `MONGODB_URI` in `backend/.env` |
| Internet node OFFLINE | Reseed with a pingable target or `--internet-simulated` (see step 2 above); it is a real ping and your network may block it. A dead real probe also makes every cycle slower (about 6 s), which delays detection |
| Charts empty | `python -m app.demo` (from `backend`), then refresh |
| Detection feels slow | Set `POLL_INTERVAL_S=2` in `backend/.env` and restart the backend (detection about 6-8 s) |
| Want a clean slate | `python -m app.simulator clear --all`, or Simulation > Recover everything |
