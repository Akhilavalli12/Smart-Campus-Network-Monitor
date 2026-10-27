# Smart Campus Network Monitoring System

A web-based mini **Network Operations Center (NOC)** for a modelled college campus.
It measures reachability (ICMP), latency, packet loss and traffic, detects faults, raises alerts and
shows everything on a live dashboard. Computer Networks PBL project.

> **Honesty rule:** the monitoring pipeline is real, but the fictional campus devices do not physically
> exist. Every metric in the UI is labelled `REAL` or `SIMULATED`.

## Quick start (from the zip)

You need **Python 3.12+**, **Node.js 20+** and a **MongoDB** (the database server cannot be put inside a zip; pick one):
Docker (`docker compose up -d mongo`, included), a local MongoDB install, or a free MongoDB Atlas connection string in `backend/.env` (`MONGODB_URI`).
The collections, indexes and demo campus are created automatically.

| | Linux / macOS / WSL / Git Bash | Windows |
|---|---|---|
| once | `./setup.sh` | `setup.bat` |
| every time | `./start.sh` | `start.bat` |

Then open **http://localhost:5173** (tabs: Dashboard, Topology, Alerts, Traffic, Devices, Simulation, Inventory, Connection). The first start also generates **24 hours of demo history** so every chart is full; follow `docs/demo.md` to present. API docs: http://localhost:8000/docs.
`start` checks MongoDB (starts the Docker one if Docker is installed), loads the demo campus, and launches backend + frontend.
Break something to see the system react: `cd backend`, activate the venv, then `python -m app.simulator inject cse-switch offline` (undo: `python -m app.simulator clear --all`).
`setup.sh` and `start.sh` were tested on Linux; the Windows `.bat` files could not be tested by me, so tell me if they fail.

The **Internet (ISP)** node does a REAL ping of `1.1.1.1`. If your network blocks that it shows OFFLINE (and cycles take longer); choose another target:
`python -m app.network_model.seed --reset --internet-target <ip that answers>` (for example your router), or `--internet-simulated` to make it simulated too (no real pings; best for a lab without internet). After `--reset` run `python -m app.demo` to reload the demo history.

## Status

| Stage | Description | State |
|---|---|---|
| 0 | Skeleton, config, MongoDB connection, health API, connection-check page | Done |
| 1 | Network model, 17-device seed, subnet validation, device registration API, inventory page | Done |
| 2 | Probe layer: real ICMP (icmplib + system ping fallback), simulator, probe CLI | Done |
| 3 | Monitoring engine, status state machine, upstream-failure logic, fault CLI, live Monitoring page | Done |
| 4 | Traffic engine: counters, rates, utilization, block totals, simulated protocol mix, REAL host NIC, Traffic page | Done |
| 5 | Alert engine: 4 alert types, dedupe, auto-resolve, hysteresis, clear delay, root-cause suppression, acknowledge | Done |
| 6 | Fault simulation API, scenarios and Simulation page | Done |
| 7 | Dashboard with KPIs, alerts feed, traffic and protocol charts, device table | Done |
| 8 | Interactive topology (React Flow) | Done |
| 9 | Charts and device details (latency, loss, traffic, utilization) | Done |
| 10 | Testing and hardening | Done (see `docs/testing.md`) |
| 11 | Documentation and 10 Mermaid UML diagrams | Done (`docs/uml`) |
| 12 | Demo and viva preparation, 24-hour demo history | Done (`docs/demo.md`, `docs/viva.md`) |

## Architecture (target)

```
React Dashboard ──HTTP/JSON──> FastAPI ──reads──> MongoDB <──writes── Monitoring Engine
                                                                          │
                                                          Probe layer: RealIcmpProbe | SimulatedProbe
```

The API only **reads** stored results; it never probes on a dashboard request.

## Prerequisites

- Python 3.12+
- Node.js 20+ (developed on 22)
- MongoDB reachable from the backend (the API starts and reports `degraded` without it, but seeding and the inventory need it)

## Setup

### 1. MongoDB (pick one)

- **Local install:** https://www.mongodb.com/docs/manual/installation/ (default URI `mongodb://localhost:27017`)
- **Docker:** `docker run -d --name campus-mongo -p 27017:27017 mongo:7`
- **Atlas free tier:** put the connection string in `MONGODB_URI` in `backend/.env`

### 2. Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # Windows: copy .env.example .env
uvicorn app.main:app --reload --port 8000
```

Check: http://localhost:8000/api/health and the auto-generated API docs at http://localhost:8000/docs

### 3. Seed the demo campus (needs MongoDB running)

```bash
cd backend
python -m app.network_model.seed            # idempotent: adds anything missing
python -m app.network_model.seed --reset    # wipe subnets/devices/links and re-seed
```

### 4. Frontend

```bash
cd frontend
npm install
cp .env.example .env               # Windows: copy .env.example .env
npm run dev
```

Open http://localhost:5173. The **Inventory** tab lists subnets, devices and a subnet calculator; the **Connection** tab shows backend and MongoDB status (refreshes every 5 s).

## Run the live demo (Stage 3)

1. Start MongoDB, then seed: `python -m app.network_model.seed --reset` (from `backend`).
2. Start the backend (`uvicorn app.main:app --reload --port 8000`). The monitoring engine starts with it.
   For a faster demo, set `POLL_INTERVAL_S=2` in `backend/.env`.
3. Start the frontend (`npm run dev`) and open the **Monitoring** tab: every device should become ONLINE within a few cycles.
4. Break something from a second terminal (in `backend`, venv active):

```bash
python -m app.simulator list
python -m app.simulator inject cse-switch offline            # root cause + 5 UNREACHABLE children
python -m app.simulator inject cse-ap high_latency --param rtt_ms=250
python -m app.simulator inject library-pc-1 packet_loss --param loss_pct=50
python -m app.simulator inject admin-switch congestion --param utilization_pct=98
python -m app.simulator clear cse-switch                      # or: clear --all
```

Expected: the switch turns OFFLINE after 3 failed cycles (default), its 5 devices turn UNREACHABLE ("cut off by CSE Switch"), and the Status changes panel shows one root cause.
Clear the fault and everything is ONLINE again after 2 good cycles.

**The Internet (ISP) node is REAL**: it pings `1.1.1.1` with genuine ICMP. If your network blocks that, it shows OFFLINE (a truthful reading, and good viva material).
Pick a host that answers: `python -m app.network_model.seed --reset --internet-target 8.8.8.8` (or your router's IP).

Check the TTL index on your MongoDB (the one part I could not run against a real MongoDB):
`db.measurements.getIndexes()` should list `ttl_measurement_ts` and `db.traffic_samples.getIndexes()` should list `ttl_traffic_ts`, both with `expireAfterSeconds: 93600`.

## Try the probes (Stage 2)

```bash
cd backend
python -m app.probes 127.0.0.1                      # REAL ICMP echo to localhost
python -m app.probes <ip-of-a-device-on-your-network> --count 10
python -m app.probes --simulate --fault offline     # SIMULATED
python -m app.probes --simulate --fault congestion --param utilization_pct=95 --count 20
python -m app.probes 127.0.0.1 --backend system     # force the system ping program
```

Real ICMP needs permission: run as root/Administrator, or let the `auto` backend fall back to the system `ping`.
If nothing can run, the tool prints `PROBE ERROR` (which is deliberately not reported as packet loss).

## Tests

```bash
cd backend && pytest               # runs contract tests against a MongoDB server too, if one is reachable
cd frontend && npm test
```

## Configuration

Backend (`backend/.env`): `MONGODB_URI`, `MONGODB_DB_NAME`, `MONGODB_SERVER_SELECTION_TIMEOUT_MS`, `CORS_ORIGINS`, `ENSURE_INDEXES_ON_STARTUP`.
Monitoring: `MONITORING_ENABLED`, `POLL_INTERVAL_S`, `FAILURE_CONFIRMATIONS`, `RECOVERY_CONFIRMATIONS`, `WINDOW_CYCLES`, `MEASUREMENT_RETENTION_HOURS` (poll interval, confirmations, window and thresholds can also be changed at runtime with `PUT /api/monitoring/config`).
Probe settings: `PROBE_COUNT`, `PROBE_TIMEOUT_S`, `PROBE_INTERVAL_S`, `ICMP_BACKEND` (`auto|icmplib|system`), `SIMULATOR_SEED`, `MONITOR_ATTACHED_TO`.
Tests optionally use `TEST_MONGODB_URI` (default `mongodb://127.0.0.1:27017`); they create and drop a throwaway database.
Set `TEST_UNREACHABLE_IP` to an address that never answers on your network to enable the real total-loss test.
Frontend (`frontend/.env`): `VITE_API_BASE_URL`. Never commit `.env` files.

## Repository layout

```
backend/app/{api,alerts,config,db,monitoring,network_model,probes,simulator,traffic}
backend/tests
frontend/src/{components,pages,hooks,services}
docs/{architecture.md,uml/,network-topology.md,viva.md,demo.md}   # filled in as stages land
```

## API (Stage 1)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | API + MongoDB status |
| GET | `/api/subnets`, `/api/subnets/{id}` | Subnets with computed mask, broadcast, usable range |
| GET | `/api/subnets/calculate?cidr=` | Subnet calculator |
| GET/POST | `/api/devices` | List (filter `block`, `type`, `subnet_id`) / register a device |
| GET/DELETE | `/api/devices/{id}` | Read / delete a leaf device |
| GET | `/api/devices/{id}/path` | Upstream chain to the Internet |
| GET | `/api/links`, `/api/topology` | Links; nodes + edges for the topology view |

Interactive docs: http://localhost:8000/docs

## API (Stage 3)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/monitoring/status` | Engine state, last cycle, detection time |
| GET / PUT | `/api/monitoring/config` | Poll interval, confirmations, window, thresholds (applies next cycle) |
| GET | `/api/devices/{id}/measurements?hours=&limit=` | Probe history, oldest first |
| GET | `/api/events?limit=&device_id=` | Status changes, newest first |

Device documents now also carry `status`, `latest` metrics, `consecutive_failures`, `caused_by`, `monitoring_error`, `last_seen`, `up_since`.

## API (Stage 4)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/traffic/status` | Traffic engine state, host NIC in use |
| GET | `/api/traffic/links` | Every link: download/upload Mbps, packets/s, utilization, state (up / busy / congested / down) |
| GET | `/api/traffic/summary` | Traffic by campus block, WAN, backbone, busiest link, this computer's REAL NIC |
| GET | `/api/traffic/protocols?minutes=` | SIMULATED protocol distribution (TCP / UDP / DNS / ICMP / other) |
| GET | `/api/traffic/links/{id}/history?hours=&limit=&bucket_s=` | Link time series |
| GET | `/api/traffic/blocks/history?hours=&bucket_s=` | Per-block time series |
| GET | `/api/traffic/host/history` | REAL host NIC time series |

Traffic settings: `TRAFFIC_ENABLED`, `TRAFFIC_INTERVAL_S`, `HOST_NIC` (empty = all non-loopback interfaces).

## API (Stages 5-9)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/alerts?state=&type=&limit=` | Alerts (newest first); `/api/alerts/summary`, `/api/alerts/{id}` |
| POST | `/api/alerts/{id}/acknowledge` | Mark an alert as seen |
| GET | `/api/simulation/state` | Simulated devices, active faults, fault catalogue, scenarios |
| POST / DELETE | `/api/simulation/faults`, `/api/simulation/faults/{device}` | Inject / clear a fault (`DELETE /api/simulation/faults` recovers everything) |
| POST | `/api/simulation/scenarios/{id}/run` | Run a demo scenario |
| GET | `/api/dashboard/summary` | KPI strip |
| GET | `/api/devices/{id}/history?hours=&bucket_s=` | Chart-ready latency / loss / jitter |

## Demo history

`python -m app.demo` (from `backend`) generates 24 hours of history with the real engines in fast-forward and replaces the measurement, traffic, event and alert history.
`start` runs it automatically when there is none. It is generated data and is labelled as such (backend `demo-backfill`, banner on the dashboard).

## Documentation
`docs/demo.md` (presentation script) · `docs/viva.md` (viva answers) · `docs/architecture.md` (every decision) · `docs/network-topology.md` (IP plan) · `docs/testing.md` · `docs/uml/` (10 diagrams)
