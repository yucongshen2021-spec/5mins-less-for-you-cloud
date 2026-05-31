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

OPENVPN_HDR = """LineID:609430B1
PE:szd-natflr2
WANIP:10.40.25.188/30
TUNNEL:vtun40826
Docking:121.12.81.3
CE LOIP:10.20.186.235
HKIP:10.60.241.250 --> 103.48.141.157
BGPSERVER IP:10.10.99.168,10.10.99.169
海外出口ip:10.60.52.46-8.3.6.111
BACKUP
PE:szc-natbk10
WANIP:10.41.25.188/30
TUNNEL:vtun50826
Docking:120.133.129.72
CE LOIP:10.20.186.235
HKIP:10.60.241.250 --> 103.48.141.157
BGPSERVER IP:10.10.99.198,10.10.99.199
海外出口ip:10.60.79.99-172.16.212.58
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
    """HK IPSec → 占位符 "正在开发中"。"""
    network = dict(_BASE_NETWORK)
    network["tunnel_type"] = "ipsec"
    resp = client.post(
        "/api/generate/epoch_fastip5",
        json={"variant": "hk", "header_text": FULL_IPSEC_HDR, "network": network},
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["ok"] is False
    assert "正在开发" in data["error"]
