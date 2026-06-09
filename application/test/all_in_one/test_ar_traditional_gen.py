"""AR 传统组网 — Generation API tests"""
import json
import _bootstrap  # noqa: F401
from app import app

client = app.test_client()

SAMPLE_HEADER = """\
LineID:609498A1
PE:szd-upe3
Tunnel:Tunnel0/0/1978
wanip:10.55.19.236/30
PE 对接:10.200.200.37
CE 对接:10.50.86.18
PE AS号:65510
CE AS号:65201
自环网段：100.100.100.0/30

拨号PE:szd-upe3
对接IP:10.200.200.37
LoopIP:10.50.86.18
拨号ip:183.56.161.86
秘钥:both-win

LineID:609498A2
PE:szc-upe1
Tunnel:Tunnel0/0/1136
wanip:10.30.36.216/30
PE 对接:10.200.200.27
CE 对接:10.50.118.34
PE AS号:65107
CE AS号:65201
自环网段：备 100.100.101.0/30

拨号PE:szc-upe1
对接IP:10.200.200.27
LoopIP:10.50.118.34
拨号ip:120.133.134.72
秘钥:both-win"""


def test_generate_success():
    """Basic generation with default params should succeed."""
    r = client.post("/api/generate/ar_traditional", json={
        "variant": "dual",
        "header_text": SAMPLE_HEADER,
        "network": {
            "wan_if": "GigabitEthernet0/0/9",
            "wan_ip": "173.15.30.40",
            "wan_mask": "255.255.255.0",
            "lan_if": "GigabitEthernet0/0/1",
            "lan_ip": "173.15.20.10",
            "lan_mask": "255.255.255.0",
            "wan_gw": "173.15.30.254",
            "lan_gw": "173.15.30.254",
            "inner_nets": "192.168.0.0/16\n172.16.0.0/12\n10.0.0.0/8",
            "bgp_networks": "173.15.30.0\n173.15.20.0\n173.15.40.0\n173.15.50.0",
            "gen_return_route": False,
            "bypass": False
        }
    })
    data = r.get_json()
    assert data["ok"], f"Generation failed: {data.get('error', '')}"
    output = data["output"]
    assert len(output) > 500, f"Output too short: {len(output)} chars"
    assert "bgp 65201" in output
    assert "interface GigabitEthernet0/0/9" in output
    assert "interface GigabitEthernet0/0/1" in output
    assert "ike peer main" in output
    assert "ike peer backup" in output
    assert "ipsec policy S2S-IPSEC" in output
    assert "Tunnel" in output
    assert "LoopBack" in output


def test_generate_empty_header():
    """Empty header should return error."""
    r = client.post("/api/generate/ar_traditional", json={
        "variant": "dual",
        "header_text": "",
        "network": {}
    })
    data = r.get_json()
    assert not data["ok"]


def test_generate_single_line_error():
    """Single line (missing backup) should return error."""
    r = client.post("/api/generate/ar_traditional", json={
        "variant": "dual",
        "header_text": "LineID:609498A1\nPE:szd-upe3\nTunnel:Tunnel0/0/1978\nwanip:10.55.19.236/30\nPE 对接:10.200.200.37\nCE 对接:10.50.86.18\nPE AS号:65510\nCE AS号:65201",
        "network": {}
    })
    data = r.get_json()
    assert not data["ok"]


def test_generate_with_return_routes():
    """Return route toggle should add static routes with tag 8888."""
    r = client.post("/api/generate/ar_traditional", json={
        "variant": "dual",
        "header_text": SAMPLE_HEADER,
        "network": {
            "wan_if": "GigabitEthernet0/0/9",
            "wan_ip": "173.15.30.40",
            "wan_mask": "255.255.255.0",
            "lan_if": "GigabitEthernet0/0/1",
            "lan_ip": "173.15.20.10",
            "lan_mask": "255.255.255.0",
            "wan_gw": "173.15.30.254",
            "lan_gw": "173.15.30.254",
            "inner_nets": "192.168.0.0/16",
            "gen_return_route": True,
            "bypass": False
        }
    })
    data = r.get_json()
    assert data["ok"]
    output = data["output"]
    assert "tag 8888" in output, "Return routes with tag 8888 should be present"


def test_generate_bypass_mode():
    """Bypass mode should omit LAN interface."""
    r = client.post("/api/generate/ar_traditional", json={
        "variant": "dual",
        "header_text": SAMPLE_HEADER,
        "network": {
            "wan_if": "GigabitEthernet0/0/9",
            "wan_ip": "173.15.30.40",
            "wan_mask": "255.255.255.0",
            "lan_if": "GigabitEthernet0/0/1",
            "lan_ip": "173.15.20.10",
            "lan_mask": "255.255.255.0",
            "wan_gw": "173.15.30.254",
            "lan_gw": "173.15.30.254",
            "bypass": True
        }
    })
    data = r.get_json()
    assert data["ok"]
    output = data["output"]
    assert "interface GigabitEthernet0/0/1" not in output or "undo portswitch" not in output


def test_example_api():
    """Example API should return sample data."""
    r = client.get("/api/examples/ar_traditional/dual")
    data = r.get_json()
    assert data["ok"]
    assert "LineID:" in data["example"]


def test_notes_api():
    """Notes API should return Chinese notes."""
    r = client.get("/api/notes/ar_traditional?variant=dual")
    data = r.get_json()
    assert data["ok"]
    assert len(data["notes"]) > 20
