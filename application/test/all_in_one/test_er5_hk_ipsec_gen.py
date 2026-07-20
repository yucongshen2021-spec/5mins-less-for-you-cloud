"""ER 5.0 香港出口 IPSec - 生成 + 初始化默认值测试"""
import _bootstrap  # noqa: F401
import app as app_mod
from app import app, _load_module, init_worker

init_worker()

client = app.test_client()
client.environ_base["HTTP_X_USER_ID"] = "test-user-1"
client.environ_base["HTTP_X_USERNAME"] = "tester"
SCENARIO_KEY = "Epoch FastIP 5.0 · HK 香港出口 · IPSec"

SAMPLE_HEADER = """\
MAIN
LineID: 609884A1
主PE: szd-flr3
WANIP: 10.40.146.88/30
TUNNEL: tun42451
PE 对接: 10.20.247.227
CE 对接: 10.50.49.6
HKIP: 61.244.14.63;
建BGP邻居: 10.20.180.193
BGPSERVER IP: 10.10.99.168,10.10.99.169

拨号PE: szd-upe2
Docking: 10.20.247.227
LoopIP: 10.50.49.6
拨号IP: 116.31.80.174
秘钥: both-win

BACKUP
PE: szc-bk2
WANIP: 10.41.146.88/30
TUNNEL: tun52451
PE 对接: 10.30.43.229
CE 对接: 10.50.150.28
HKIP: 61.244.14.63;
建BGP邻居: 10.20.180.193
BGPSERVER IP: 10.10.99.168,10.10.99.199

拨号PE: szc-upe2
Docking: 10.30.43.229
LoopIP: 10.50.150.28
拨号IP: 120.133.134.66
秘钥: both-win
"""

NET = {"wan_eth": "0", "wan_cidr": "192.168.1.190/24", "wan_gw": "192.168.1.1",
       "lan_eth": "5", "lan_cidr": "192.168.15.1/24", "lan_gw": "192.168.15.1",
       "inner_nets": "10.0.0.0/8\n172.16.0.0/12\n192.168.0.0/16"}


# ═══ 1. 基础生成测试 ═══

def test_generate_success():
    r = client.post("/api/generate/epoch_fastip5", json={
        "variant": "hk_ipsec", "header_text": SAMPLE_HEADER,
        "network": {**NET, "gen_return_route": False, "bypass": False}
    })
    data = r.get_json()
    assert data["ok"], f"Generation failed: {data.get('error', '')}"
    output = data["output"]
    assert len(output) > 500
    assert "tun42451" in output
    assert "61.244.14.63" in output
    assert "site-to-site peer main" in output
    assert "10.20.180.193" in output  # bgp_neighbor


def test_wan_dhcp_mode():
    """WAN DHCP=True -> WAN 接口用 dhcp，不生成默认路由。"""
    r = client.post("/api/generate/epoch_fastip5", json={
        "variant": "hk_ipsec", "header_text": SAMPLE_HEADER,
        "network": {**NET, "wan_dhcp": True}
    })
    data = r.get_json()
    assert data["ok"], data.get("error", "")
    output = data["output"]
    assert "eth0 address 'dhcp'" in output
    # 默认路由不应生成
    assert "0.0.0.0/0 next-hop 1.1.1.1 distance '222'" not in output


def test_bypass_mode():
    """旁挂(单臂)模式 -> 不生成 LAN 接口和 DHCP server。"""
    r = client.post("/api/generate/epoch_fastip5", json={
        "variant": "hk_ipsec", "header_text": SAMPLE_HEADER,
        "network": {**NET, "bypass": True}
    })
    data = r.get_json()
    assert data["ok"], data.get("error", "")
    output = data["output"]
    assert "旁挂" in output
    assert "eth5 address" not in output  # LAN 接口不生成
    assert "NAT_LAN subnet" not in output  # DHCP server 不生成


def test_return_routes():
    """回程路由=True -> 生成内网段回程路由，next-hop 用 LAN 网关。"""
    r = client.post("/api/generate/epoch_fastip5", json={
        "variant": "hk_ipsec", "header_text": SAMPLE_HEADER,
        "network": {**NET, "gen_return_route": True, "bypass": False}
    })
    data = r.get_json()
    assert data["ok"], data.get("error", "")
    output = data["output"]
    # 回程路由 next-hop 应该是 LAN IP（192.168.15.1），不是旧的模块默认 192.168.5.1
    assert "set protocols static route 10.0.0.0/8 next-hop 192.168.15.1" in output
    assert "192.168.5.1" not in output  # 不应出现旧默认网关


def test_bypass_return_routes():
    """旁挂 + 回程路由 -> 回程路由 next-hop 用 WAN 网关。"""
    r = client.post("/api/generate/epoch_fastip5", json={
        "variant": "hk_ipsec", "header_text": SAMPLE_HEADER,
        "network": {**NET, "bypass": True, "gen_return_route": True}
    })
    data = r.get_json()
    assert data["ok"], data.get("error", "")
    output = data["output"]
    assert "set protocols static route 10.0.0.0/8 next-hop 192.168.1.1" in output


def test_lan_dhcp_off():
    """LAN DHCP=False -> 不生成 DHCP server 块。"""
    r = client.post("/api/generate/epoch_fastip5", json={
        "variant": "hk_ipsec", "header_text": SAMPLE_HEADER,
        "network": {**NET, "lan_dhcp": False}
    })
    data = r.get_json()
    assert data["ok"], data.get("error", "")
    output = data["output"]
    assert "NAT_LAN subnet" not in output


def test_nat_exclude_rules():
    """NAT exclude rule 5/6 让 192.168.55.250 不被 NAT。"""
    r = client.post("/api/generate/epoch_fastip5", json={
        "variant": "hk_ipsec", "header_text": SAMPLE_HEADER,
        "network": NET
    })
    data = r.get_json()
    assert data["ok"], data.get("error", "")
    output = data["output"]
    assert "set nat source rule 5 destination address '192.168.55.250/32'" in output
    assert "set nat source rule 5 exclude" in output
    assert "set nat source rule 6 destination address '192.168.55.250/32'" in output
    assert "set nat source rule 6 exclude" in output


def test_dial_ip_routes():
    """拨号 IP 路由都走 1.1.1.1（不走 wan_gw）。"""
    r = client.post("/api/generate/epoch_fastip5", json={
        "variant": "hk_ipsec", "header_text": SAMPLE_HEADER,
        "network": NET
    })
    data = r.get_json()
    assert data["ok"], data.get("error", "")
    output = data["output"]
    assert "set protocols static route 116.31.80.174/32 next-hop 1.1.1.1" in output
    assert "set protocols static route 120.133.134.66/32 next-hop 1.1.1.1" in output


def test_generate_empty_header():
    r = client.post("/api/generate/epoch_fastip5", json={
        "variant": "hk_ipsec", "header_text": "", "network": {}
    })
    assert not r.get_json()["ok"]


def test_generate_missing_field_error():
    r = client.post("/api/generate/epoch_fastip5", json={
        "variant": "hk_ipsec",
        "header_text": "MAIN\nLineID: 609884A1\n主PE: szd-flr3\n",
        "network": {}
    })
    assert not r.get_json()["ok"]


def test_generate_no_backup_block():
    r = client.post("/api/generate/epoch_fastip5", json={
        "variant": "hk_ipsec",
        "header_text": "MAIN\nLineID: 609884A1\n主PE: szd-flr3\nWANIP: 10.40.146.88/30\nTUNNEL: tun42451\nPE 对接: 10.20.247.227\nCE 对接: 10.50.49.6\nHKIP: 61.244.14.63;\n建BGP邻居: 10.20.180.193\nBGPSERVER IP: 10.10.99.168,10.10.99.169\n\n拨号PE: szd-upe2\nDocking: 10.20.247.227\nLoopIP: 10.50.49.6\n拨号IP: 116.31.80.174\n秘钥: both-win\n",
        "network": {}
    })
    assert not r.get_json()["ok"]


def test_example_api():
    r = client.get("/api/examples/epoch_fastip5/hk_ipsec")
    assert r.get_json()["ok"]


def test_notes_api():
    r = client.get("/api/notes/epoch_fastip5?variant=hk_ipsec")
    assert r.get_json()["ok"]


# ═══ 2. 初始化默认值 ═══

def test_init_defaults_factory():
    app_mod._snapshot_factory_defaults()
    r = client.get(f"/api/init-defaults/{SCENARIO_KEY}")
    d = r.get_json()
    assert d["ok"]
    vals = d["values"]
    assert "DEFAULT_WAN_CIDR" in vals
    assert "DEFAULT_LAN_CIDR" in vals


def test_init_defaults_save_and_generate():
    r = client.post("/api/init-defaults/save", json={
        "key": SCENARIO_KEY,
        "values": {"DEFAULT_WAN_CIDR": "10.99.99.10/24", "DEFAULT_WAN_GW": "10.99.99.1"}
    }).get_json()
    assert r["ok"]
    r = client.post("/api/generate/epoch_fastip5", json={
        "variant": "hk_ipsec", "header_text": SAMPLE_HEADER,
        "network": {"wan_cidr": "10.99.99.10/24", "wan_gw": "10.99.99.1",
                    "lan_cidr": "192.168.15.1/24", "lan_gw": "192.168.15.1",
                    "inner_nets": "10.0.0.0/8"}
    }).get_json()
    assert r["ok"]
    assert "10.99.99.10" in r["output"]
    client.post("/api/init-defaults/reset", json={"key": SCENARIO_KEY})


# ═══ 3. 模板与场景注册 ═══

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
