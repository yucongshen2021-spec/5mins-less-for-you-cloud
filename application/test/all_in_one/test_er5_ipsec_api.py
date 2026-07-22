"""ER 5.0 IPSec — Web API 端到端测试。

直接打 Flask app 的 /api/generate/epoch_fastip5 端点，
模拟前端 UI 真实路径：选择 5.0 → us → IPSec → 点生成。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
import _bootstrap  # noqa: F401

# _bootstrap 已把 web/src 加入 sys.path
import app as web_app  # noqa: E402


@pytest.fixture
def client():
    web_app.app.config["TESTING"] = True
    return web_app.app.test_client()


FULL_IPSEC_HDR = """LineID:609430B1
PE:szd-upe3
Tunnel:Tunnel0/0/2013
wanip:10.40.129.148/30
PE 对接:10.200.200.37
CE 对接:10.50.86.74
PE AS号:65510
客户内网路由:10.22.242.223
拨号PE:szd-upe3
对接IP:10.200.200.37
LoopIP:10.50.86.74
拨号ip:183.56.161.86
秘钥:both-win
--- IKE (ike-peer IPSEC) ---
key-exchange: ikev1/ikev2
proposal 1:
  dh-group: 2
  encryption: aes128 3des
  hash: sha1
dead-peer-detection: no
--- IPsec proposal (IPSEC) ---
proposal 1:
  encryption: aes128 3des
  hash: sha1

LineID:609430B2
PE:szc-upe1
Tunnel:Tunnel0/0/1163
wanip:10.30.37.168/30
PE 对接:10.200.200.27
CE 对接:10.50.118.76
PE AS号:65107
客户内网路由:10.22.242.223
拨号PE:szc-upe1
对接IP:10.200.200.27
LoopIP:10.50.118.76
拨号ip:120.133.134.72
秘钥:both-win

LineID:609430B5
PE： lax1-natpe7
WANIP: 10.22.113.36/30
TUNNEL: tun2209
PE Docking：192.168.215.12
CE Docking：: 10.22.242.223
BGPSERVER IP：103.252.19.25,43.229.117.226
海外出口ip：
10.60.52.46-8.3.6.111

LineID:609430B6
PE： sjc1-natpe3
WANIP: 10.22.115.28/30
TUNNEL: tun1080
PE Docking：10.33.54.118
CE Docking：: 10.22.242.223
BGPSERVER IP：103.252.19.99,43.229.119.251
海外出口ip：
10.60.79.99-172.16.212.58
"""

OPENVPN_HDR = """LineID:609169A1
PE:gzd-upe5
Tunnel:Tunnel0/0/1165
wanip:10.55.14.64/30
PE 对接:192.168.247.17
PE:gzd-acvpnpe2
Tunnel:vtun17953
wanip:10.23.0.120/30
PE 对接:183.63.68.171

LineID:609169A2
PE:dgb-upebk2
Tunnel:Tunnel0/0/1998
wanip:10.40.209.220/30
PE 对接:192.168.251.100
PE:dgb-acvpnpe2
Tunnel:vtun50057
wanip:10.30.167.200/30
PE 对接:121.12.128.254

LineID:609169A5
PE： twb-natpe2
WANIP: 10.21.32.124/30
TUNNEL: tun1267
PE Docking：192.168.239.12
CE Docking：10.22.241.232
BGPSERVER IP：103.252.19.25,43.229.117.226
海外出口ip：
10.60.44.28-218.32.88.83

LineID:609169A6
PE： twb-natpe1
WANIP: 10.21.31.120/30
TUNNEL: tun2366
PE Docking：192.168.239.14
CE Docking：10.22.241.232
BGPSERVER IP：103.252.19.99,43.229.119.251
海外出口ip：
10.60.18.22-150.116.112.236
"""

HK_IPSEC_HDR = """MAIN
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

_BASE_NETWORK = {
    "wan_cidr": "111.111.115.2/30",
    "lan_cidr": "192.168.5.105/24",
    "wan_gw": "111.111.115.1",
    "wan_eth": "0",
    "lan_eth": "5",
    "wan_dhcp": False,
    "lan_dhcp": True,
    "inner_nets": "10.0.0.0/8\n172.16.0.0/12\n192.168.0.0/16",
}


def test_ipsec_api_returns_vpn_block(client):
    """POST /api/generate/epoch_fastip5 with tunnel_type=ipsec → 返回 IPSec 配置。"""
    network = dict(_BASE_NETWORK)
    network["tunnel_type"] = "ipsec"
    resp = client.post(
        "/api/generate/epoch_fastip5",
        json={
            "variant": "us",
            "header_text": FULL_IPSEC_HDR,
            "network": network,
        },
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    data = resp.get_json()
    assert data["ok"] is True
    out = data["output"]
    assert "set vpn ipsec" in out
    assert "site-to-site peer main" in out
    assert "etheth" not in out  # 回归: bug 已修
    assert "set interfaces ethernet eth0 " in out


def test_ipsec_api_no_openvpn_interface(client):
    """IPSec 模式 → 输出不应包含 OpenVPN 接口。"""
    network = dict(_BASE_NETWORK)
    network["tunnel_type"] = "ipsec"
    resp = client.post(
        "/api/generate/epoch_fastip5",
        json={"variant": "us", "header_text": FULL_IPSEC_HDR, "network": network},
    )
    out = resp.get_json()["output"]
    assert "interfaces openvpn" not in out


def test_openvpn_api_keeps_old_behavior(client):
    """tunnel_type=openvpn → 行为与现在一致，含 openvpn 接口块。"""
    network = dict(_BASE_NETWORK)
    network["tunnel_type"] = "openvpn"
    resp = client.post(
        "/api/generate/epoch_fastip5",
        json={"variant": "us", "header_text": OPENVPN_HDR, "network": network},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    out = data["output"]
    assert "interfaces openvpn" in out
    assert "set vpn ipsec" not in out


def test_openvpn_default_when_tunnel_type_omitted(client):
    """请求体不带 tunnel_type 字段 → 走 OpenVPN（默认）。"""
    network = dict(_BASE_NETWORK)
    # 故意不设 tunnel_type
    resp = client.post(
        "/api/generate/epoch_fastip5",
        json={"variant": "us", "header_text": OPENVPN_HDR, "network": network},
    )
    out = resp.get_json()["output"]
    assert "interfaces openvpn" in out


def test_hk_ipsec_returns_dev_in_progress(client):
    """HK IPSec 已实现，应返回 200 + ipsec 配置。"""
    network = dict(_BASE_NETWORK)
    network["tunnel_type"] = "ipsec"
    resp = client.post(
        "/api/generate/epoch_fastip5",
        json={"variant": "hk", "header_text": HK_IPSEC_HDR, "network": network},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert "vpn ipsec" in data["output"]
