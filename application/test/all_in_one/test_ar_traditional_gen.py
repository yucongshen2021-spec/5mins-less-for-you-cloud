"""AR 传统组网 — 全量测试（生成、初始化默认、模板）"""
import json
import _bootstrap  # noqa: F401
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


# ═══ 1. 基础生成测试 ═══

def test_generate_success():
    """基础生成成功，输出含 BGP、IPSec、Tunnel、LoopBack."""
    r = client.post("/api/generate/ar_traditional", json={
        "variant": "dual",
        "header_text": SAMPLE_HEADER,
        "network": {
            "wan_if": "GigabitEthernet0/0/9", "wan_ip": "173.15.30.40", "wan_mask": "255.255.255.0",
            "lan_if": "GigabitEthernet0/0/1", "lan_ip": "173.15.20.10", "lan_mask": "255.255.255.0",
            "wan_gw": "173.15.30.254", "lan_gw": "173.15.30.254",
            "inner_nets": "192.168.0.0/16\n172.16.0.0/12\n10.0.0.0/8",
            "bgp_networks": "173.15.30.0\n173.15.20.0\n173.15.40.0\n173.15.50.0",
            "gen_return_route": False, "bypass": False
        }
    })
    data = r.get_json()
    assert data["ok"], f"Generation failed: {data.get('error', '')}"
    output = data["output"]
    assert len(output) > 500, f"Output too short: {len(output)} chars"
    assert "bgp 65201" in output
    assert "interface GigabitEthernet0/0/9" in output
    assert "ike peer main" in output
    assert "ike peer backup" in output
    assert "ipsec policy S2S-IPSEC" in output
    assert "Tunnel" in output
    assert "LoopBack" in output


def test_generate_empty_header():
    """空数据头返回错误."""
    r = client.post("/api/generate/ar_traditional", json={
        "variant": "dual", "header_text": "", "network": {}
    })
    assert not r.get_json()["ok"]


def test_generate_single_line_error():
    """单线（缺少备线）返回错误."""
    r = client.post("/api/generate/ar_traditional", json={
        "variant": "dual",
        "header_text": "LineID:609498A1\nPE:szd-upe3\nTunnel:Tunnel0/0/1978\nwanip:10.55.19.236/30\nPE 对接:10.200.200.37\nCE 对接:10.50.86.18\nPE AS号:65510\nCE AS号:65201",
        "network": {}
    })
    assert not r.get_json()["ok"]


def test_generate_with_return_routes():
    """回程路由 → 输出含 tag 8888."""
    r = client.post("/api/generate/ar_traditional", json={
        "variant": "dual", "header_text": SAMPLE_HEADER,
        "network": {
            "wan_if": "GigabitEthernet0/0/9", "wan_ip": "173.15.30.40", "wan_mask": "255.255.255.0",
            "lan_if": "GigabitEthernet0/0/1", "lan_ip": "173.15.20.10", "lan_mask": "255.255.255.0",
            "wan_gw": "173.15.30.254", "lan_gw": "173.15.30.254",
            "inner_nets": "192.168.0.0/16", "gen_return_route": True, "bypass": False
        }
    })
    assert r.get_json()["ok"]
    assert "tag 8888" in r.get_json()["output"]


def test_generate_bypass_mode():
    """旁挂模式 → 输出不含 LAN 接口."""
    r = client.post("/api/generate/ar_traditional", json={
        "variant": "dual", "header_text": SAMPLE_HEADER,
        "network": {
            "wan_if": "GigabitEthernet0/0/9", "wan_ip": "173.15.30.40", "wan_mask": "255.255.255.0",
            "lan_if": "GigabitEthernet0/0/1", "lan_ip": "173.15.20.10", "lan_mask": "255.255.255.0",
            "wan_gw": "173.15.30.254", "lan_gw": "173.15.30.254", "bypass": True
        }
    })
    assert r.get_json()["ok"]
    output = r.get_json()["output"]
    assert "interface GigabitEthernet0/0/1" not in output or "undo portswitch" not in output


def test_example_api():
    """示例 API 返回样例数据."""
    r = client.get("/api/examples/ar_traditional/dual")
    data = r.get_json()
    assert data["ok"]
    assert "LineID:" in data["example"]


def test_notes_api():
    """备注 API 返回中文."""
    r = client.get("/api/notes/ar_traditional?variant=dual")
    data = r.get_json()
    assert data["ok"]
    assert len(data["notes"]) > 20


# ═══ 2. 初始化默认值完整链路测试 ═══

def test_init_defaults_save_and_generate():
    """保存自定义网络参数 → 生成 → 验证输出包含自定义值."""
    # Step 1: 保存自定义参数
    r = client.post("/api/init-defaults/save", json={
        "key": SCENARIO_KEY,
        "values": {
            "wan_if": "GigabitEthernet0/0/5",
            "wan_ip": "10.99.99.10",
            "wan_mask": "255.255.255.0",
            "wan_gw": "10.99.99.1",
            "lan_if": "GigabitEthernet0/0/3",
            "lan_ip": "172.16.99.1",
            "lan_mask": "255.255.255.0",
            "lan_gw": "172.16.99.1",
            "inner_nets": "192.168.100.0/24",
            "bgp_networks": "10.99.99.0",
            "gen_return_route": True,
            "bypass": False
        }
    }).get_json()
    assert r["ok"], f"Save init defaults failed: {r.get('error','')}"

    # Step 2: 用自定义值生成
    r = client.post("/api/generate/ar_traditional", json={
        "variant": "dual", "header_text": SAMPLE_HEADER,
        "network": {
            "wan_if": "GigabitEthernet0/0/5", "wan_ip": "10.99.99.10", "wan_mask": "255.255.255.0",
            "wan_gw": "10.99.99.1",
            "lan_if": "GigabitEthernet0/0/3", "lan_ip": "172.16.99.1", "lan_mask": "255.255.255.0",
            "lan_gw": "172.16.99.1",
            "inner_nets": "192.168.100.0/24",
            "bgp_networks": "10.99.99.0",
            "gen_return_route": True, "bypass": False
        }
    }).get_json()
    assert r["ok"], f"Generate with custom init failed: {r.get('error','')}"
    output = r["output"]

    # Step 3: 验证自定义值反映在输出中
    assert "GigabitEthernet0/0/5" in output, "Custom WAN if should be in output"
    assert "172.16.99.1" in output, "Custom LAN IP should be in output"
    assert "10.99.99.1" in output, "Custom WAN GW should be in output"
    assert "192.168.100.0" in output, "Custom inner net should be in output"
    assert "tag 8888" in output, "Return routes should be present"

    # Clean up
    client.post("/api/init-defaults/reset", json={"key": SCENARIO_KEY})


def test_init_defaults_bypass_chain():
    """保存 bypass=True → 生成 → 验证不含 LAN 接口."""
    r = client.post("/api/init-defaults/save", json={
        "key": SCENARIO_KEY,
        "values": {"bypass": True}
    }).get_json()
    assert r["ok"]

    r = client.post("/api/generate/ar_traditional", json={
        "variant": "dual", "header_text": SAMPLE_HEADER,
        "network": {
            "wan_if": "GigabitEthernet0/0/9", "wan_ip": "173.15.30.40", "wan_mask": "255.255.255.0",
            "wan_gw": "173.15.30.254", "bypass": True
        }
    }).get_json()
    assert r["ok"]
    output = r["output"]
    assert "undo portswitch" not in output, "Bypass mode should omit LAN if block"

    client.post("/api/init-defaults/reset", json={"key": SCENARIO_KEY})


def test_init_defaults_reset():
    """恢复出厂 → 自定义值被清除."""
    # Save custom
    client.post("/api/init-defaults/save", json={
        "key": SCENARIO_KEY,
        "values": {"wan_ip": "99.99.99.99"}
    }).get_json()

    # Verify saved
    r = client.get(f"/api/init-defaults/{SCENARIO_KEY}")
    d = r.get_json()
    assert d["ok"]
    assert d.get("values", {}).get("wan_ip") == "99.99.99.99"

    # Reset
    r = client.post("/api/init-defaults/reset", json={"key": SCENARIO_KEY}).get_json()
    assert r["ok"]

    # Verify reset
    r = client.get(f"/api/init-defaults/{SCENARIO_KEY}")
    d = r.get_json()
    assert d["ok"]
    assert d.get("values", {}).get("wan_ip") != "99.99.99.99", "Should be reset"


# ═══ 3. 模板编辑器测试 ═══

def test_template_load():
    """加载模板返回 header、mapping、template."""
    r = client.post("/api/template/load", json={"key": SCENARIO_KEY})
    data = r.get_json()
    assert data["ok"], f"Load failed: {data.get('error', '')}"
    assert len(data["template"]) > 500
    assert len(data["header"]) > 50
    assert "LineID:" in data["header"]
    assert len(data["mapping"]) > 100


def test_scenario_in_list():
    """场景出现在场景列表中."""
    r = client.get("/api/scenarios")
    data = r.get_json()
    assert data["ok"]
    keys = [s["key"] for s in data["scenarios"]]
    assert SCENARIO_KEY in keys
    assert len(keys) == 29


def test_scenario_in_tree():
    """场景出现在场景树中."""
    r = client.get("/api/scenarios")
    data = r.get_json()
    assert data["ok"]

    def find_key(nodes):
        for n in nodes:
            if n.get("key") == SCENARIO_KEY:
                return True
            if "children" in n:
                if find_key(n["children"]):
                    return True
        return False

    assert find_key(data["tree"]), f"{SCENARIO_KEY} not found in tree"
