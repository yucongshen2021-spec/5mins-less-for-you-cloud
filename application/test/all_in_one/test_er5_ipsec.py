"""ER 5.0 IPSec 隧道类型 — 用户视角测试。

模拟用户在 Web UI 的操作路径：
  1. 选择 IPSec 隧道类型 → 粘贴数据头 → 点击生成
  2. 选择 OpenVPN → 粘贴数据头 → 点击生成（回归）
  3. 修改初始化变量（WAN/LAN IP）→ 观察输出变化
  4. 无 IKE 参数的数据头 → 验证警告提示
  5. 修改 IKE 参数 → 验证参数正确传递
"""

import json
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
import _bootstrap  # noqa: F401

APP_DIR = _bootstrap.APP_DIR
SRC_DIR = _bootstrap.SRC_DIR
sys.path.insert(0, str(SRC_DIR))

import er_fastip_5in1_v1 as er5


# ── 测试数据头（4 LineID：B1/B2 IPSec + B5/B6 NAT，含 IKE/IPSec 参数）──
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
  prf: hmac-sha2-256
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
--- IKE (ike-peer IPSEC) ---
key-exchange: ikev1/ikev2
proposal 1:
  dh-group: 2
  encryption: aes128 3des
  hash: sha1
dead-peer-detection: yes
  type: ondemand
  idle-time: 10
--- IPsec proposal (IPSEC) ---
proposal 1:
  encryption: aes128 3des
  hash: sha1

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

# 无 IKE/IPSec 参数块（4 LineID 结构完整）
NO_IPSEC_HDR = """LineID:609430B1
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

# OpenVPN 格式数据头（用于回归测试）
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


def _set_net_vars(**kwargs):
    """模拟 all_in_one_v2 注入网络参数到模块 globals()。"""
    defaults = {
        "DEFAULT_WAN_CIDR": "192.168.1.10/24",
        "DEFAULT_LAN_CIDR": "192.168.5.1/24",
        "DEFAULT_WAN_GW": "192.168.1.1",
        "DEFAULT_WAN_ETH": "0",
        "DEFAULT_LAN_ETH": "5",
        "DEFAULT_WAN_DHCP": False,
        "DEFAULT_LAN_DHCP": True,
        "DEFAULT_INNER_NETS": "10.0.0.0/8\n172.16.0.0/12\n192.168.0.0/16",
    }
    defaults.update(kwargs)
    g = er5.__dict__
    for k, v in defaults.items():
        g[k] = v


def _generate(tunnel_type, hdr_text, **net_overrides):
    """模拟 gen('epoch-fastip') → POST /api/generate/epoch_fastip5 的完整路径。"""
    _set_net_vars(**net_overrides)
    er5.DEFAULT_TUNNEL_TYPE = tunnel_type
    if tunnel_type == "ipsec":
        d, warning = er5.build_epoch5_us_ipsec_format_dict(hdr_text)
    else:
        result = er5.build_epoch5_us_format_dict(hdr_text)
        if isinstance(result, tuple):
            d, _err = result
            if d is None:
                return None, _err
        else:
            d = result
        warning = ""

    if d is None:
        return None, warning

    tpl = er5.TEMPLATE_EPOCH5_US_IPSEC if tunnel_type == "ipsec" else er5.TEMPLATE_EPOCH5_US
    if isinstance(d, dict) and tpl:
        output = tpl.format(**d)
        if warning:
            output = "# " + warning + "\n" + output
        return output, warning
    return str(d), warning


# ═══════════════════════════════════════════════════════════════════
# Test 1: IPSec 全参数生成
# ═══════════════════════════════════════════════════════════════════
class TestIPSecFullGeneration:
    def test_generates_ipsec_vpn_block(self):
        """选择 IPSec → 生成输出应包含 vpn ipsec 配置块。"""
        output, _ = _generate("ipsec", FULL_IPSEC_HDR)
        assert output is not None
        assert "vpn ipsec" in output
        assert "ike-group IKE-FNET-1" in output
        assert "esp-group ESP-FNET-1" in output
        assert "site-to-site peer main" in output

    def test_ethernet_interface_name_not_doubled(self):
        """回归: WAN/LAN 接口名应是 'eth0'/'eth5'，不能是 'etheth0'/'etheth5'。

        历史 bug: 模板写 `eth{wan_if}` 而 builder 已把 wan_if 设为 'eth0'，
        导致输出 'etheth0'。这条测试守住接口名只能出现一个 'eth' 前缀。
        """
        output, _ = _generate("ipsec", FULL_IPSEC_HDR)
        assert "etheth" not in output
        assert "set interfaces ethernet eth0 " in output
        assert "set interfaces ethernet eth5 " in output

    def test_ethernet_eth_param_changes_propagate(self):
        """改 DEFAULT_WAN_ETH/DEFAULT_LAN_ETH 应反映到接口名上，无双前缀。"""
        output, _ = _generate("ipsec", FULL_IPSEC_HDR,
                              DEFAULT_WAN_ETH="2", DEFAULT_LAN_ETH="3")
        assert "etheth" not in output
        assert "set interfaces ethernet eth2 " in output
        assert "set interfaces ethernet eth3 " in output
        assert "set vpn ipsec interface 'eth2'" in output

    def test_ike_params_extracted(self):
        """IKE 参数从数据头正确提取并填入模板。"""
        output, _ = _generate("ipsec", FULL_IPSEC_HDR)
        assert "key-exchange 'ikev1'" in output
        assert "dh-group '2'" in output

    def test_esp_params_extracted(self):
        """IPSec proposal 参数正确提取。"""
        output, _ = _generate("ipsec", FULL_IPSEC_HDR)
        assert "proposal 1 encryption 'aes128'" in output
        assert "proposal 1 hash 'sha1'" in output

    def test_contains_gre_tunnels(self):
        """IPSec 模式包含 IPSec GRE 与 NAT GRE 共 4 条隧道。"""
        output, _ = _generate("ipsec", FULL_IPSEC_HDR)
        assert output.count("encapsulation 'gre'") >= 4
        assert "tun2013" in output
        assert "tun2209" in output
        assert "tun1080" in output

    def test_dum_numbering(self):
        """dum0=CE loopback; IPSec=dum1/dum2; NAT=dum101/dum201。"""
        output, _ = _generate("ipsec", FULL_IPSEC_HDR)
        assert "dummy dum0 address '10.22.242.223/32'" in output
        assert "dummy dum1 address '10.50.86.74/32'" in output
        assert "dummy dum2 address '10.50.118.76/32'" in output
        assert "dummy dum101 address '10.60.52.46/32'" in output
        assert "dummy dum201 address '10.60.79.99/32'" in output
        assert "dummy dum100 " not in output
        assert "dummy dum52 " not in output

    def test_router_id_is_main_nat_usip(self):
        """BGP router-id = 主线 NAT 海外出口 IP。"""
        output, _ = _generate("ipsec", FULL_IPSEC_HDR)
        assert "parameters router-id '10.60.52.46'" in output

    def test_contains_bgp(self):
        output, _ = _generate("ipsec", FULL_IPSEC_HDR)
        assert "protocols bgp" in output
        assert "103.252.19.25" in output
        assert "43.229.119.251" in output

    def test_contains_nat(self):
        output, _ = _generate("ipsec", FULL_IPSEC_HDR)
        assert "nat source rule 1001" in output
        assert "nat source rule 2001" in output

    def test_contains_pbr_and_filesync(self):
        output, _ = _generate("ipsec", FULL_IPSEC_HDR)
        assert "policy local-route rule 2180" in output
        assert "service file-sync task 1" in output

    def test_hostname_from_lineid(self):
        """Hostname 从 LineID 自动提取。"""
        output, _ = _generate("ipsec", FULL_IPSEC_HDR)
        assert "609430B1" in output

    def test_no_openvpn_in_ipsec_output(self):
        """IPSec 模式下不应出现 openvpn 接口。"""
        output, _ = _generate("ipsec", FULL_IPSEC_HDR)
        assert "interfaces openvpn" not in output


class TestIPSecMtuMss:
    def test_ipsec_upe_gre_mtu_1476_mss_1300(self):
        """IPSec(upe) 主备 GRE 隧道 MTU=1476、MSS=1300。"""
        output, _ = _generate("ipsec", FULL_IPSEC_HDR)
        for tun in ("tun2013", "tun1163"):
            assert f"set interfaces tunnel {tun} mtu '1476'" in output
            assert f"set interfaces tunnel {tun} ip adjust-mss '1300'" in output

    def test_nat_natpe_gre_mtu_1452_mss_1300(self):
        """NAT(natpe) 主备 GRE 隧道 MTU=1452、MSS=1300。"""
        output, _ = _generate("ipsec", FULL_IPSEC_HDR)
        for tun in ("tun2209", "tun1080"):
            assert f"set interfaces tunnel {tun} mtu '1452'" in output
            assert f"set interfaces tunnel {tun} ip adjust-mss '1300'" in output


class TestIPSecInnerNetsSync:
    def test_default_inner_nets_three_segments(self):
        """默认 inner_nets 三段，LAN-NET 与防泄漏路由两处都同步。"""
        output, _ = _generate("ipsec", FULL_IPSEC_HDR)
        for net in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"):
            assert f"set firewall group network-group LAN-NET network '{net}'" in output
            assert f"set protocols static route {net} next-hop 1.1.1.1" in output

    def test_custom_inner_nets_propagate(self):
        """改 DEFAULT_INNER_NETS 后 LAN-NET 和防泄漏路由同步变化。"""
        custom = "10.50.0.0/16\n192.168.100.0/24"
        output, _ = _generate("ipsec", FULL_IPSEC_HDR, DEFAULT_INNER_NETS=custom)
        for net in ("10.50.0.0/16", "192.168.100.0/24"):
            assert f"set firewall group network-group LAN-NET network '{net}'" in output
            assert f"set protocols static route {net} next-hop 1.1.1.1" in output
        # 旧默认值不应出现
        assert "LAN-NET network '172.16.0.0/12'" not in output
        assert "static route 172.16.0.0/12" not in output

    def test_invalid_inner_nets_rejected(self):
        """非法内网段必须报错，不允许猜测。"""
        _set_net_vars(DEFAULT_INNER_NETS="not-a-cidr")
        d, err = er5.build_epoch5_us_ipsec_format_dict(FULL_IPSEC_HDR)
        assert d is None
        assert err[0] == "network"


class TestIPSecRouteSections:
    def test_route_sections_have_headers(self):
        """静态路由按 OpenVPN 风格分类，每段都有中文注释头。"""
        output, _ = _generate("ipsec", FULL_IPSEC_HDR)
        for header in (
            "# ── 默认路由 ──",
            "# ── IPSec 上游路由",
            "# ── NAT/GRE 上游路由",
            "# ── BGP 服务器路由",
            "# ── 内网防泄漏",
            "# ── PBR 分表默认路由 ──",
        ):
            assert header in output

    def test_default_route_blackhole_via_1_1_1_1(self):
        """默认路由 0.0.0.0/0 走 1.1.1.1（黑洞触发）；1.1.1.1/32 才指向真实 wan_gw。"""
        output, _ = _generate("ipsec", FULL_IPSEC_HDR,
                              DEFAULT_WAN_GW="111.111.115.1")
        assert "set protocols static route 0.0.0.0/0 next-hop 1.1.1.1 distance '220'" in output
        assert "set protocols static route 1.1.1.1/32 next-hop 111.111.115.1" in output


# ═══════════════════════════════════════════════════════════════════
# Test 2: 无 IPSec 参数 → 警告
# ═══════════════════════════════════════════════════════════════════
class TestIPSecNoParams:
    def test_warning_when_no_ike_params(self):
        """数据头无 IKE/IPSec 参数时，输出带有警告。"""
        output, warning = _generate("ipsec", NO_IPSEC_HDR)
        assert output is not None
        assert "未检测到IKE/IPSec参数" in warning or "默认参数" in output

    def test_still_generates_config(self):
        """即使无 IPSec 参数，仍生成可用的配置文件。"""
        output, _ = _generate("ipsec", NO_IPSEC_HDR)
        assert "vpn ipsec" in output
        assert "set system host-name" in output


# ═══════════════════════════════════════════════════════════════════
# Test 3: OpenVPN 回归
# ═══════════════════════════════════════════════════════════════════
class TestOpenVPNRegression:
    def test_openvpn_generates_openvpn_interface(self):
        """选择 OpenVPN → 生成 openvpn 接口配置。"""
        output, _ = _generate("openvpn", OPENVPN_HDR)
        assert output is not None
        assert "interfaces openvpn" in output

    def test_openvpn_no_ipsec_vpn_block(self):
        """OpenVPN 模式下不应出现 vpn ipsec。"""
        output, _ = _generate("openvpn", OPENVPN_HDR)
        assert "vpn ipsec" not in output


# ═══════════════════════════════════════════════════════════════════
# Test 4: 修改初始化变量
# ═══════════════════════════════════════════════════════════════════
class TestInitVariableChanges:
    def test_wan_ip_change_reflected(self):
        """修改 WAN IP 后输出反映新值。"""
        output, _ = _generate("ipsec", FULL_IPSEC_HDR,
                              DEFAULT_WAN_CIDR="10.0.0.1/24")
        assert "10.0.0.1" in output

    def test_lan_ip_change_reflected(self):
        """修改 LAN IP 后输出反映新值。"""
        output, _ = _generate("ipsec", FULL_IPSEC_HDR,
                              DEFAULT_LAN_CIDR="172.16.0.1/24")
        assert "172.16.0.1" in output


# ═══════════════════════════════════════════════════════════════════
# Test 5: 数据头修改影响输出
# ═══════════════════════════════════════════════════════════════════
class TestDataHeaderChanges:
    def test_different_lineid_changes_hostname(self):
        """不同 LineID → hostname 变化。"""
        hdr = FULL_IPSEC_HDR.replace("609430B1", "TEST-LINE-01")
        output, _ = _generate("ipsec", hdr)
        assert "TEST-LINE-01" in output

    def test_different_secret_changes_psk(self):
        """不同秘钥 → PSK 变化。"""
        hdr = FULL_IPSEC_HDR.replace("both-win", "new-secret-123")
        output, _ = _generate("ipsec", hdr)
        assert "new-secret-123" in output

    def test_different_ike_version(self):
        """ikev2 vs ikev1（取 key-exchange 第一个 token）。"""
        hdr = FULL_IPSEC_HDR.replace("ikev1/ikev2", "ikev2/ikev1")
        output, _ = _generate("ipsec", hdr)
        assert "key-exchange 'ikev2'" in output


class TestIPSecParseErrors:
    def test_rejects_incomplete_lineid_count(self):
        """只有 2 个 LineID 时必须报错，不允许猜测。"""
        hdr = FULL_IPSEC_HDR.split("LineID:609430B5")[0].strip()
        _set_net_vars()
        d, err = er5.build_epoch5_us_ipsec_format_dict(hdr)
        assert d is None
        assert err[0] == "parse"
        assert "NAT/GRE" in err[1]
