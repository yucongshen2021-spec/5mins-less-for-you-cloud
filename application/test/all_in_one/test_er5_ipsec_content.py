"""ER 5.0 IPSec 输出内容精确验证 — 反"糖衣测试"。

每条测试验证输出的具体值，不只是结构。错误的路由 next-hop、残留的垃圾规则
都必须被精确抓到。
"""

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
import _bootstrap  # noqa: F401

SRC_DIR = _bootstrap.SRC_DIR
sys.path.insert(0, str(SRC_DIR))

import er_fastip_5in1_v1 as er5


# ── 用户真实数据（LineID:609650A1-A4，含 IPSec + NAT 4 组）──
REAL_USER_HDR = """LineID:609650A1
PE:szd-upe3
Tunnel:Tunnel0/0/2026
wanip:10.40.211.120/30
PE 对接:10.200.200.37
CE 对接:10.50.149.3
PE AS号:65510
客户内网路由:10.22.241.147

拨号PE:szd-upe3
对接IP:10.200.200.37
LoopIP:10.50.149.3
拨号ip:116.31.80.167
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


LineID:609650A2
PE:szc-upe2
Tunnel:Tunnel0/0/1612
wanip:10.70.84.36/30
PE 对接:10.200.200.35
CE 对接:10.50.150.2
PE AS号:65157
客户内网路由:10.22.241.147

拨号PE:szc-upe2
对接IP:10.200.200.35
LoopIP:10.50.150.2
拨号ip:120.133.134.66
秘钥:both-win

--- IKE (ike-peer IPSEC) ---
key-exchange: ikev1/ikev2
proposal 1:
  dh-group: 2
  encryption: aes256 aes128 3des
  hash: sha1
  prf: hmac-sha2-256
dead-peer-detection: yes
  type: ondemand
  idle-time: 10

--- IPsec proposal (IPSEC) ---
proposal 1:
  encryption: aes256 aes128 3des
  hash: sha1

LineID:609650A3
PE： sin4-natpe1
WANIP: 10.21.44.120/30
TUNNEL: tun2284
PE Docking：10.40.229.118
CE Docking：: 10.22.241.147
BGPSERVER IP：103.252.19.25,43.229.117.226
海外出口ip：
10.60.75.106-203.127.181.74

LineID:609650A4
PE： sin2-natpe6
WANIP: 10.22.109.244/30
TUNNEL: tun1287
PE Docking：10.33.54.26
CE Docking：: 10.22.241.147
BGPSERVER IP：103.252.19.99,43.229.119.251
海外出口ip：
10.60.78.118-172.16.220.102-192.9.244.177
"""

# 预计算一下 tun_pe_ip，用来做「不应出现」的断言
# 主 IPSec: 10.40.211.120/30 → tun_ce_ip=10.40.211.122, tun_pe_ip=10.40.211.121
# 备 IPSec: 10.70.84.36/30  → tun_ce_ip=10.70.84.38,   tun_pe_ip=10.70.84.37
MAIN_IPSEC_PE_IP = "10.40.211.121"
BK_IPSEC_PE_IP = "10.70.84.37"


def _set_net_vars(**kwargs):
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


def _generate(hdr):
    """用用户真实数据生成 IPSec 配置。"""
    _set_net_vars()
    er5.DEFAULT_TUNNEL_TYPE = "ipsec"
    d, warning = er5.build_epoch5_us_ipsec_format_dict(hdr)
    if d is None:
        raise RuntimeError(f"生成失败: {warning}")
    tpl = er5.TEMPLATE_EPOCH5_US_IPSEC
    return tpl.format(**d)


# ═══════════════════════════════════════════════════════════════════
# Section A: 路由内容精确验证
# ═══════════════════════════════════════════════════════════════════

class TestNATRoutesContent:
    """NAT/GRE 上游路由的精确内容验证。

    拓扑: CE → IPSec tunnel → UPE → NAT PE
    NAT PE docking IP 的下一跳必须是 UPE 对端 IP (IPSec tunnel PE IP)，
    因为 GRE 隧道承载在 IPSec 之上，必须先到达 UPE 才能转发到 NAT PE。
    """

    def test_nat_pe_docking_routes_use_upe_peer_ip(self):
        """两条 NAT PE docking 路由的 next-hop 必须是对应侧 UPE (IPSec PE) 对端 IP。

        主 NAT PE → 主 IPSec PE: 10.40.229.118/32 → 10.40.211.121
        备 NAT PE → 备 IPSec PE: 10.33.54.26/32  → 10.70.84.37
        """
        output = _generate(REAL_USER_HDR)
        assert "set protocols static route 10.40.229.118/32 next-hop 10.40.211.121" in output
        assert "set protocols static route 10.33.54.26/32 next-hop 10.70.84.37" in output

    def test_nat_routes_must_use_correct_upe_ip(self):
        """NAT 路由必须使用 IPSec PE tunnel IP，主备严格对应。

        主线 NAT PE docking 走主线 IPSec PE (不能走到备线)。
        备线 NAT PE docking 走备线 IPSec PE (不能走到主线)。
        """
        output = _generate(REAL_USER_HDR)
        nat_start = output.find("# ── NAT/GRE 上游路由")
        next_section = output.find("# ── BGP 服务器路由", nat_start)
        nat_section = output[nat_start:next_section]

        # 主线必须出现 (主 NAT → 主 UPE)
        assert f"next-hop {MAIN_IPSEC_PE_IP}" in nat_section, (
            f"NAT 段缺少主线路由: 主 NAT PE docking → 主 UPE ({MAIN_IPSEC_PE_IP})"
        )
        # 备线必须出现 (备 NAT → 备 UPE)
        assert f"next-hop {BK_IPSEC_PE_IP}" in nat_section, (
            f"NAT 段缺少备线路由: 备 NAT PE docking → 备 UPE ({BK_IPSEC_PE_IP})"
        )

        # 不应出现线路错配：主线 NAT PE docking 绝不走备 UPE
        assert f"10.40.229.118/32 next-hop {BK_IPSEC_PE_IP}" not in output, (
            "主线 NAT PE docking 错配到备 UPE"
        )
        # 不应出现线路错配：备线 NAT PE docking 绝不走主 UPE
        assert f"10.33.54.26/32 next-hop {MAIN_IPSEC_PE_IP}" not in output, (
            "备线 NAT PE docking 错配到主 UPE"
        )

    def test_nat_section_has_exactly_two_routes(self):
        """NAT/GRE 段应有且仅有 2 条路由（主线 + 备线 NAT PE docking）。

        注意: 模板注释尾部的 \\n 是 literal text，第一条路由会拼接在注释行尾。
        因此不能用换行符分割来计行数，必须用子串出现次数。
        """
        output = _generate(REAL_USER_HDR)
        nat_start = output.find("# ── NAT/GRE 上游路由")
        next_section = output.find("# ── BGP 服务器路由", nat_start)
        if next_section < 0:
            next_section = len(output)
        nat_section = output[nat_start:next_section]
        count = nat_section.count("set protocols static route")
        assert count == 2, (
            f"NAT 段应有 2 条路由，实际 {count}\nNAT 段内容:\n{nat_section[:400]}"
        )


class TestIPSecRoutesContent:
    """IPSec 上游路由的精确内容验证。"""

    def test_ipsec_docking_routes_use_1111(self):
        """IPSec main/bk docking IP 走 1.1.1.1（黑洞触发器模式）。"""
        output = _generate(REAL_USER_HDR)
        assert "set protocols static route 10.200.200.37/32 next-hop 1.1.1.1" in output
        assert "set protocols static route 10.200.200.35/32 next-hop 1.1.1.1" in output

    def test_ipsec_dial_routes_use_1111(self):
        """IPSec 拨号 IP 也走 1.1.1.1 模式。"""
        output = _generate(REAL_USER_HDR)
        assert "set protocols static route 116.31.80.167/32 next-hop 1.1.1.1" in output

    def test_ipsec_section_has_no_ce_loip_route(self):
        """IPSec 段不应包含 ce_loip 的独立路由（已被 bypass 覆盖）。

        曾出现的 bug: 模板里有一条 {ce_loip}/32 next-hop {ib['tun_pe_ip']}，
        导致 10.22.241.147/32 → 10.70.84.37 这样的错误路由。
        """
        output = _generate(REAL_USER_HDR)
        ipsec_start = output.find("# ── IPSec 上游路由")
        next_section = output.find("# ── NAT/GRE 上游路由", ipsec_start)
        ipsec_section = output[ipsec_start:next_section]
        assert "10.22.241.147/32" not in ipsec_section, (
            "IPSec 段不应包含 ce_loip 独立路由（已被 bypass 覆盖）"
        )


# ═══════════════════════════════════════════════════════════════════
# Section B: 不应出现的内容（负向断言）
# ═══════════════════════════════════════════════════════════════════

class TestAbsentContent:
    """验证不应该出现在输出中的内容。"""

    def test_no_dnat_port53_rules(self):
        """DNAT rule 20/25 (port 53 DNS 劫持) 不应出现。

        用户明确要求移除。这些规则属于其他场景，IPSec 不需要。
        """
        output = _generate(REAL_USER_HDR)
        assert "nat destination rule 20" not in output, "DNAT rule 20 不应出现"
        assert "nat destination rule 25" not in output, "DNAT rule 25 不应出现"
        assert "destination port '53'" not in output, "port 53 DNAT 不应出现"

    def test_no_4221_probe_route(self):
        """4.2.2.1/32 探测路由不应出现。

        用户明确要求移除。
        """
        output = _generate(REAL_USER_HDR)
        assert "4.2.2.1" not in output, "4.2.2.1 探测路由不应出现"

    def test_no_openvpn_interface(self):
        """IPSec 模式下不应出现 openvpn 接口。"""
        output = _generate(REAL_USER_HDR)
        assert "interfaces openvpn" not in output


# ═══════════════════════════════════════════════════════════════════
# Section C: 内网段三段的精确验证
# ═══════════════════════════════════════════════════════════════════

class TestInnerNetsExact:
    """内网段三大段精确验证 — LAN-NET 和 bypass 必须同步。"""

    THREE_NETS = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")

    def test_lan_net_has_three_segments(self):
        """LAN-NET firewall group 包含三大内网段。"""
        output = _generate(REAL_USER_HDR)
        for net in self.THREE_NETS:
            assert f"set firewall group network-group LAN-NET network '{net}'" in output, (
                f"LAN-NET 缺少 {net}"
            )

    def test_bypass_has_three_segments(self):
        """内网防泄漏路由包含三大段 → 1.1.1.1。"""
        output = _generate(REAL_USER_HDR)
        for net in self.THREE_NETS:
            assert f"set protocols static route {net} next-hop 1.1.1.1" in output, (
                f"防泄漏路由缺少 {net}"
            )

    def test_lan_net_and_bypass_match(self):
        """LAN-NET 和 bypass 的内网段集合必须一致。"""
        output = _generate(REAL_USER_HDR)
        import re
        lan_nets = set(re.findall(
            r"LAN-NET network '([^']+)'", output
        ))
        bypass_nets = set(re.findall(
            r"内网防泄漏[\s\S]*?(?=# ── PBR)",
            output
        ))
        # 从 bypass 段提取网络
        bypass_start = output.find("# ── 内网防泄漏")
        bypass_end = output.find("# ── PBR", bypass_start)
        bypass_section = output[bypass_start:bypass_end]
        bypass_networks = set(re.findall(
            r"static route (\S+) next-hop 1.1.1.1", bypass_section
        ))
        assert lan_nets == bypass_networks, (
            f"LAN-NET: {lan_nets} != bypass: {bypass_networks}"
        )


# ═══════════════════════════════════════════════════════════════════
# Section D: GROUP-FNET-Whitelist 包含三大内网段
# ═══════════════════════════════════════════════════════════════════

class TestWhitelistNetworks:
    """白名单网络组包含必需的内网段。"""

    def test_whitelist_has_three_private_ranges(self):
        """GROUP-FNET-Whitelist 包含 RFC 1918 三大段 + CGNAT + 组播 + 回环。"""
        output = _generate(REAL_USER_HDR)
        for net in ("192.168.0.0/16", "172.16.0.0/12", "10.0.0.0/8",
                    "100.64.0.0/10", "224.0.0.0/4", "127.0.0.0/8"):
            assert f"GROUP-FNET-Whitelist network '{net}'" in output, (
                f"Whitelist 缺少 {net}"
            )


# ═══════════════════════════════════════════════════════════════════
# Section E: 与现有测试数据头的兼容验证
# ═══════════════════════════════════════════════════════════════════

class TestBackwardCompat:
    """现有测试数据头 (609430B1-B6) 同样受新断言约束。"""

    OLD_HDR = """LineID:609430B1
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
  prf: hmac-sha2-256
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

    def test_no_dnat_on_old_hdr(self):
        """老数据头也不应有 DNAT rule 20/25。"""
        output = _generate(self.OLD_HDR)
        assert "nat destination rule 20" not in output
        assert "nat destination rule 25" not in output

    def test_no_4221_on_old_hdr(self):
        """老数据头也不应有 4.2.2.1 路由。"""
        output = _generate(self.OLD_HDR)
        assert "4.2.2.1" not in output

    def test_nat_routes_upe_ip_on_old_hdr(self):
        """老数据头的 NAT PE docking 路由使用对应 IPSec PE tunnel IP。

        主 IPSec PE IP = 10.40.129.149 (10.40.129.148/30 的 PE 侧)
        备 IPSec PE IP = 10.30.37.169 (10.30.37.168/30 的 PE 侧)
        """
        output = _generate(self.OLD_HDR)
        assert "set protocols static route 192.168.215.12/32 next-hop 10.40.129.149" in output
        assert "set protocols static route 10.33.54.118/32 next-hop 10.30.37.169" in output

    def test_old_hdr_nat_routes_correct_upe_ip(self):
        """老数据头的 NAT 段不出现线路错配。"""
        output = _generate(self.OLD_HDR)
        nat_start = output.find("# ── NAT/GRE 上游路由")
        next_section = output.find("# ── BGP 服务器路由", nat_start)
        nat_section = output[nat_start:next_section]
        # 主 UPE IP 在 NAT 段必须有（主线路由）
        assert "next-hop 10.40.129.149" in nat_section
        # 备 UPE IP 在 NAT 段必须有（备线路由）
        assert "next-hop 10.30.37.169" in nat_section
        # 主线不应错配到备 UPE
        assert "192.168.215.12/32 next-hop 10.30.37.169" not in output
        # 备线不应错配到主 UPE
        assert "10.33.54.118/32 next-hop 10.40.129.149" not in output
