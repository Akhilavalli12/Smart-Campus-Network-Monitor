# Network topology and IP plan

## Topology (a tree rooted at the Internet)

```
INTERNET (1.1.1.1, REAL probe target)
   |  WAN link, 200 Mbps
[Edge Router]  10.0.0.1/30
   |  10.0.0.0/30 point-to-point, 1000 Mbps
[Core L3 Switch]  10.0.0.2/30   gateways: 192.168.10.1 / 192.168.20.1 / 192.168.30.1
   |-- [CSE Switch]     192.168.10.2 -- AP .3 | Server .10 | PCs .101 .102 .103
   |-- [Library Switch] 192.168.20.2 -- AP .3 | PCs .101 .102
   `-- [Admin Switch]   192.168.30.2 -- AP .3 | PCs .101 .102
```

17 devices, 16 links. Every device has exactly one upstream parent, so the model is a tree.

## IP plan

| Subnet | CIDR | Mask | Usable hosts | Gateway | Purpose |
|---|---|---|---|---|---|
| Edge-Core Link | 10.0.0.0/30 | 255.255.255.252 | 2 (.1 .2) | none | Router to core point-to-point link |
| CSE Network | 192.168.10.0/24 | 255.255.255.0 | 254 | 192.168.10.1 | CSE block LAN |
| Library Network | 192.168.20.0/24 | 255.255.255.0 | 254 | 192.168.20.1 | Library LAN |
| Admin Network | 192.168.30.0/24 | 255.255.255.0 | 254 | 192.168.30.1 | Admin block LAN |

Host numbering inside a block: `.1` gateway, `.2` switch (management IP), `.3` access point, `.10` server, `.101+` PCs.

All campus subnets are RFC 1918 private ranges. The Internet node uses a public address (1.1.1.1) because it is the one device we really probe in Stage 2; it sits outside every campus subnet.

### Subnet maths worked example (192.168.10.0/24)

- Prefix 24 -> 24 network bits, 8 host bits -> 2^8 = 256 addresses.
- Network address 192.168.10.0 and broadcast 192.168.10.255 are reserved -> 254 usable hosts (.1 to .254).
- Mask 255.255.255.0; wildcard 0.0.0.255.

### Why /30 for the router-core link

A point-to-point link only needs two addresses. A /30 has 4 addresses, minus network and broadcast = 2 usable (.1 router, .2 core). A /24 would waste 252 addresses. (A /31 per RFC 3021 would use both addresses, but /30 is the classic textbook choice and is supported everywhere.)

### Route summarisation (optional talking point)

The three campus blocks fall inside 192.168.0.0/19 (third octet 0 to 31), so the edge router could hold one static route `192.168.0.0/19 via 10.0.0.2` instead of three. Trade-off: it also covers unused space (192.168.0.0 to 192.168.31.255).

## Where the monitoring station sits (vantage point)

The device tree is rooted at the Internet, but the monitoring station is **not** on the Internet: it is plugged into
the core switch (setting `MONITOR_ATTACHED_TO`, default `core-switch`). "Which devices must work for a probe to
reach X?" is therefore the tree path from the core switch to X, not the path up to the Internet:

| Target | Devices that must work for the probe to arrive |
|---|---|
| CSE PC 1 | Core L3 Switch, CSE Switch |
| CSE Switch | Core L3 Switch |
| Internet (ISP) | Core L3 Switch, Edge Router |
| Core L3 Switch | none (the station's own attachment point) |

Consequences: an Internet outage does not make the campus LAN unreachable, and a core-switch failure isolates the
station from everything. `topology.reachability_path()` computes this; Stage 3 uses it for upstream-failure logic.
Limitation: a single vantage point; a failure that only affects the station's own link looks like a campus-wide outage.

## How devices communicate (conceptual, modelled)

- Inside a block: frames are switched by the L2 block switch using MAC addresses; ARP resolves IP to MAC; the subnet is one broadcast domain.
- Between blocks: a PC sends traffic to its default gateway (192.168.X.1, an interface of the core L3 switch). The core routes it into the destination subnet. The system models this path; it does not forward real packets.
- To the Internet: the core's default route points to the edge router (10.0.0.1), which forwards to the ISP.

## Why a Layer 3 switch at the core

It switches at wire speed inside a VLAN/subnet and also routes between subnets, so one device acts as the gateway for all three blocks without a separate router-on-a-stick. The edge router then only handles the WAN boundary.

## Why block switches have IP addresses

A Layer 2 switch forwards frames by MAC address and needs no IP to do that. The IP (.2 in each subnet) belongs to its management plane, so it can be reached by ping, SNMP or SSH. That management address is what we monitor.

## Simulated MAC addresses

Each device gets a deterministic MAC derived from its id. The first octet is `02`, which sets the locally administered bit and clears the multicast bit, so these can never collide with real vendor addresses. They are labelled SIMULATED data.

## Link capacities

Capacities are demo-scaled data (WAN 200 Mbps, backbone 1000 Mbps, uplinks and access 100 Mbps) so that utilisation percentages are visible in a small demo. They can be changed per device with `uplink_capacity_mbps`.

## Validation rules enforced when registering a device

1. IPv4 only, strictly parsed (no leading zeros, no out-of-range octets).
2. IP must be a usable host of the chosen subnet (not the network or broadcast address).
3. The subnet's gateway address is reserved for the gateway device.
4. IPs and ids are unique (also enforced by a unique MongoDB index).
5. The device's campus block must match its subnet's block.
6. The parent must exist and the pairing must be legal (for example a PC cannot sit directly under a core switch).
7. `monitoring_mode = real` requires `probe_target`; simulated devices must not set one.
8. Only one Internet root; a device with downstream devices cannot be deleted.

## OSI / TCP-IP mapping for this stage

| Layer | Where it appears |
|---|---|
| 1 Physical | Link capacity and link kind in the `links` collection |
| 2 Data link | Switch devices, simulated MACs, one broadcast domain per subnet |
| 3 Network | IPv4 plan, subnetting, gateways, default and summary routes (modelled) |

## Real vs simulated at this stage

- REAL: subnet calculations and validation (Python `ipaddress`), and the Internet node's probe target.
- SIMULATED: every other device, its MAC, `base_rtt_ms` (a simulator parameter, not a measurement), link capacities and the routing story above.
