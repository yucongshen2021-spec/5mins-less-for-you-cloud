"""AR 传统组网 — 全量测试（生成、初始化默认、模板）"""
import json
import _bootstrap  # noqa: F401
import app as app_mod
from app import app, _load_module

client = app.test_client()
SCENARIO_KEY = "AR 传统组网 · 双线"

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

NET = {"wan_eth": "0", "wan_cidr": "10.4.7.252/24", "wan_gw": "10.4.7.254",
       "lan_eth": "1", "lan_cidr": "173.15.20.10/24", "lan_gw": "173.15.20.254",
       "inner_nets": "10.0.0.0/8\n172.16.0.0/12\n192.168.0.0/16"}


# ═══ 1. 基础生成测试 ═══

def test_generate_success():
    """基础生成 — LAN 接口可见，CIDR 格式 IP."""
    r = client.post("/api/generate/ar_traditional", json={
        "variant": "dual", "header_text": SAMPLE_HEADER,
        "network": {**NET, "gen_return_route": False, "bypass": False}
    })
    data = r.get_json()
    assert data["ok"], f"Generation failed: {data.get('error', '')}"
    output = data["output"]
    assert len(output) > 500
    assert "Tunnel0/0/1000" in output and "Tunnel0/0/2000" in output
    assert "LoopBack1000" in output and "LoopBack2000" in output
    assert "nqa test-instance admin ipsecmain" in output
    assert "undo portswitch" in output       # LAN 接口
    assert "173.15.20.10" in output           # LAN IP
    assert "keepalive 10 3" not in output
    assert "  network " not in output


def test_generate_empty_header():
    r = client.post("/api/generate/ar_traditional", json={
        "variant": "dual", "header_text": "", "network": {}
    })
    assert not r.get_json()["ok"]


def test_generate_single_line_error():
    r = client.post("/api/generate/ar_traditional", json={
        "variant": "dual",
        "header_text": "LineID:609498A1\nPE:szd-upe3\nTunnel0/0/1978\nwanip:10.55.19.236/30\nPE 对接:10.200.200.37\nCE 对接:10.50.86.18\nPE AS号:65510\nCE AS号:65201",
        "network": {}
    })
    assert not r.get_json()["ok"]


def test_generate_with_return_routes():
    """回程路由=True → 内网段以 LAN GW 为下一跳."""
    r = client.post("/api/generate/ar_traditional", json={
        "variant": "dual", "header_text": SAMPLE_HEADER,
        "network": {**NET, "inner_nets": "192.168.0.0/16",
                    "gen_return_route": True, "bypass": False}
    })
    assert r.get_json()["ok"]
    output = r.get_json()["output"]
    assert "192.168.0.0 255.255.0.0 173.15.20.254" in output


def test_generate_bypass_mode():
    """旁挂=True → 输出无 LAN 接口."""
    r = client.post("/api/generate/ar_traditional", json={
        "variant": "dual", "header_text": SAMPLE_HEADER,
        "network": {**NET, "bypass": True}
    })
    assert r.get_json()["ok"]
    assert "undo portswitch" not in r.get_json()["output"]


def test_example_api():
    r = client.get("/api/examples/ar_traditional/dual")
    assert r.get_json()["ok"]


def test_notes_api():
    r = client.get("/api/notes/ar_traditional?variant=dual")
    assert r.get_json()["ok"]


# ═══ 2. 初始化默认值 ═══

def test_init_defaults_factory():
    """工厂默认值 — CIDR 格式 IP，回程路由默认 ON，无 DHCP 键."""
    app_mod._snapshot_factory_defaults()
    r = client.get(f"/api/init-defaults/{SCENARIO_KEY}")
    d = r.get_json()
    assert d["ok"]
    vals = d["values"]
    assert vals.get("DEFAULT_WAN_IP") == "10.4.7.252/24", f"Got: {vals.get('DEFAULT_WAN_IP')}"
    assert vals.get("DEFAULT_LAN_IP") == "173.15.20.10/24"
    assert vals.get("DEFAULT_GEN_RETURN_ROUTE") == True  # 默认打开
    assert "DEFAULT_WAN_MASK" not in vals  # 无独立掩码
    assert "DEFAULT_LAN_MASK" not in vals
    assert "DEFAULT_WAN_DHCP" not in vals  # 无 DHCP
    assert "DEFAULT_LAN_DHCP" not in vals


def test_init_defaults_save_and_generate():
    """保存自定义值 → 生成 → 验证."""
    r = client.post("/api/init-defaults/save", json={
        "key": SCENARIO_KEY,
        "values": {"DEFAULT_WAN_IP": "10.99.99.10/24", "DEFAULT_WAN_GW": "10.99.99.1",
                   "DEFAULT_LAN_IP": "172.16.99.1/24", "DEFAULT_GEN_RETURN_ROUTE": True}
    }).get_json()
    assert r["ok"]

    r = client.post("/api/generate/ar_traditional", json={
        "variant": "dual", "header_text": SAMPLE_HEADER,
        "network": {"wan_eth": "0", "wan_cidr": "10.99.99.10/24", "wan_gw": "10.99.99.1",
                    "lan_eth": "1", "lan_cidr": "172.16.99.1/24",
                    "inner_nets": "192.168.100.0/24",
                    "gen_return_route": True, "bypass": False}
    }).get_json()
    assert r["ok"]
    output = r["output"]
    assert "172.16.99.1" in output
    assert "10.99.99.1" in output
    client.post("/api/init-defaults/reset", json={"key": SCENARIO_KEY})


# ═══ 3. 模板 ═══

def test_template_load():
    r = client.post("/api/template/load", json={"key": SCENARIO_KEY})
    d = r.get_json()
    assert d["ok"]
    assert len(d["template"]) > 500


def test_scenario_in_list():
    r = client.get("/api/scenarios")
    keys = [s["key"] for s in r.get_json()["scenarios"]]
    assert SCENARIO_KEY in keys


def test_scenario_in_tree():
    r = client.get("/api/scenarios")
    def find(nodes):
        for n in nodes:
            if n.get("key") == SCENARIO_KEY: return True
            if "children" in n and find(n["children"]): return True
        return False
    assert find(r.get_json()["tree"])
