VALID_PC = {
    "name": "CSE PC 4", "type": "pc", "ip": "192.168.10.104",
    "subnet_id": "cse-net", "block": "cse", "parent_id": "cse-switch",
}


def test_list_subnets_includes_computed_info(seeded_client):
    body = seeded_client.get("/api/subnets").json()
    assert [s["id"] for s in body] == ["admin-net", "cse-net", "library-net", "p2p-edge-core"]
    cse = next(s for s in body if s["id"] == "cse-net")
    assert cse["info"]["netmask"] == "255.255.255.0"
    assert cse["info"]["usable_hosts"] == 254
    assert cse["gateway"] == "192.168.10.1"


def test_subnet_calculator(seeded_client):
    ok = seeded_client.get("/api/subnets/calculate", params={"cidr": "192.168.10.77/24"})
    assert ok.status_code == 200
    assert ok.json()["network_address"] == "192.168.10.0"
    bad = seeded_client.get("/api/subnets/calculate", params={"cidr": "192.168.10.0/33"})
    assert bad.status_code == 422 and "prefix length" in bad.json()["detail"]
    assert seeded_client.get("/api/subnets/calculate").status_code == 422  # missing parameter


def test_get_one_subnet_and_404(seeded_client):
    assert seeded_client.get("/api/subnets/cse-net").json()["info"]["broadcast_address"] == "192.168.10.255"
    assert seeded_client.get("/api/subnets/nope").status_code == 404


def test_list_devices_sorted_by_ip_and_filterable(seeded_client):
    devices = seeded_client.get("/api/devices").json()
    assert len(devices) == 17
    assert [d["id"] for d in devices[:3]] == ["internet", "edge-router", "core-switch"]
    cse = seeded_client.get("/api/devices", params={"block": "cse"}).json()
    assert len(cse) == 6
    pcs = seeded_client.get("/api/devices", params={"type": "pc"}).json()
    assert len(pcs) == 7
    assert seeded_client.get("/api/devices", params={"block": "mars"}).status_code == 422


def test_get_device_and_404(seeded_client):
    body = seeded_client.get("/api/devices/cse-switch").json()
    assert body["ip"] == "192.168.10.2" and body["monitoring_mode"] == "simulated" and body["status"] == "unknown"
    assert seeded_client.get("/api/devices/ghost").status_code == 404


def test_register_device_201_then_visible(seeded_client):
    response = seeded_client.post("/api/devices", json=VALID_PC)
    assert response.status_code == 201
    assert response.json()["id"] == "cse-pc-4"
    assert seeded_client.get("/api/devices/cse-pc-4").status_code == 200
    assert len(seeded_client.get("/api/links").json()) == 17


def test_register_rejects_malformed_ip_with_422(seeded_client):
    response = seeded_client.post("/api/devices", json={**VALID_PC, "ip": "999.1.1.1"})
    assert response.status_code == 422
    assert "valid IPv4" in str(response.json()["detail"])


def test_register_rejects_injection_style_probe_target(seeded_client):
    body = {**VALID_PC, "monitoring_mode": "real", "probe_target": "8.8.8.8; rm -rf /"}
    assert seeded_client.post("/api/devices", json=body).status_code == 422


def test_register_rejects_unknown_fields_and_bad_enums(seeded_client):
    assert seeded_client.post("/api/devices", json={**VALID_PC, "status": "online"}).status_code == 422
    assert seeded_client.post("/api/devices", json={**VALID_PC, "type": "toaster"}).status_code == 422
    assert seeded_client.post("/api/devices", json={"name": "x"}).status_code == 422


def test_register_rule_violation_422_and_conflict_409(seeded_client):
    outside = seeded_client.post("/api/devices", json={**VALID_PC, "ip": "192.168.77.4"})
    assert outside.status_code == 422 and "usable host" in outside.json()["detail"]
    duplicate = seeded_client.post("/api/devices", json={**VALID_PC, "ip": "192.168.10.101"})
    assert duplicate.status_code == 409


def test_delete_rules(seeded_client):
    assert seeded_client.delete("/api/devices/cse-switch").status_code == 409
    assert seeded_client.delete("/api/devices/cse-pc-3").status_code == 204
    assert seeded_client.get("/api/devices/cse-pc-3").status_code == 404
    assert seeded_client.delete("/api/devices/cse-pc-3").status_code == 404


def test_path_endpoint(seeded_client):
    hops = seeded_client.get("/api/devices/admin-ap/path").json()["hops"]
    assert [h["id"] for h in hops] == ["admin-ap", "admin-switch", "core-switch", "edge-router", "internet"]


def test_topology_endpoint(seeded_client):
    body = seeded_client.get("/api/topology").json()
    assert len(body["nodes"]) == 17 and len(body["edges"]) == 16
    edge = next(e for e in body["edges"] if e["id"] == "internet--edge-router")
    assert (edge["source"], edge["target"], edge["kind"]) == ("internet", "edge-router", "wan")


def test_database_down_returns_503_not_500(down_client):
    for path in ("/api/devices", "/api/subnets", "/api/topology", "/api/links"):
        response = down_client.get(path)
        assert response.status_code == 503, path
        assert response.json() == {"detail": "Database unavailable"}
