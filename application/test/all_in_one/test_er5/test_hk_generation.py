#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Integration tests for Epoch FastIP 5.0 HK generation.

Usage:
    python test_hk_generation.py          # run all tests
    pytest test_hk_generation.py -v       # run with pytest
"""

import json
import os
import sys
import unittest

# ── Path setup: bootstrap shared with siblings ──
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _bootstrap  # noqa: F401
from app import app, _snapshot_factory_defaults


# ── Shared test data ──

VALID_HEADER_MAIN_BACKUP = """MAIN
lineid: 603642Ar3
PE： szd-natflr2
WANIP: 10.40.25.188/30
TUNNEL: vtun40826
Docking：121.12.81.3
CE LOIP: 10.20.186.235
HKIP：10.60.241.250
BGPSERVER IP： 10.10.99.168,10.10.99.169

BACKUP
PE：szc-natbk10
WANIP: 10.41.25.188/30
TUNNEL: vtun50826
Docking： 120.133.129.72
BGPSERVER IP：10.10.99.198,10.10.99.199"""

VALID_HEADER_MAIN_ONLY = """MAIN
PE： test-pe-only
WANIP: 10.1.1.2/30
TUNNEL: vtun100
Docking：1.1.1.1
CE LOIP: 10.99.99.1
HKIP：10.88.88.1
BGPSERVER IP： 10.10.10.1,10.10.10.2"""

VALID_US_HEADER = (
    "LineID:609169A1\nPE:gzd-upe5\nTunnel:Tunnel0/0/1165\nwanip:10.55.14.64/30\n"
    "PE 对接:192.168.247.17\n海外出口ip:\n10.60.44.28-218.32.88.83\n\n"
    "LineID:609169A5\nPE:twb-natpe2\nWANIP:10.21.32.124/30\nTUNNEL:tun1267\n"
    "PE Docking:192.168.239.12\nBGPSERVER IP:103.252.19.25,43.229.117.226\n"
    "海外出口ip:\n10.60.44.28-218.32.88.83"
)

VALID_FLINK_HEADER = (
    "PE: szd-vupe6  FPE: F-ShenZhen4  预留IP: 100.94.10.216/29\n"
    "PE: bja-vupe6  FPE: F-BeiJing4  预留IP: 100.93.10.216/29\n"
    "PE: sha-vupe6  FPE: F-ShangHai4  预留IP: 100.92.10.216/29"
)

VALID_NEW_EXIT_HEADER = (
    "LineID:609430B5\nPE: lax1-natpe7\nWANIP: 10.22.113.36/30\n"
    "TUNNEL: tun2209\nPE Docking: 192.168.215.12\nCE Docking: 10.22.242.223\n"
    "海外出口ip:\n10.60.52.46-8.3.6.111\n\n"
    "LineID:609430B6\nPE: sjc1-natpe3\nWANIP: 10.22.115.28/30\n"
    "TUNNEL: tun1080\nPE Docking: 10.33.54.118\nCE Docking: 10.22.242.223\n"
    "海外出口ip:\n10.60.79.99-172.16.212.58"
)


# ── Test case classes ──

class TestEpochFastIP5HKBasic(unittest.TestCase):
    """Basic HK generation tests — status codes and output structure."""

    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()
        _snapshot_factory_defaults()
        _snapshot_factory_defaults()

    def test_empty_header_returns_400(self):
        """Empty header should return 400 with error about missing PE/data."""
        resp = self.client.post("/api/generate/epoch_fastip5", json={
            "variant": "hk",
            "header_text": "",
            "network": {},
        })
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertFalse(data.get("ok"))
        err = data.get("error", "")
        self.assertIn("parse", err, f"Expected parse error, got: {err}")

    def test_whitespace_only_header_returns_400(self):
        """Header with only whitespace should also return 400."""
        resp = self.client.post("/api/generate/epoch_fastip5", json={
            "variant": "hk",
            "header_text": "   \n  ",
            "network": {},
        })
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertFalse(data.get("ok"))


class TestEpochFastIP5HKWithHeader(unittest.TestCase):
    """Tests with a valid MAIN+BACKUP header."""

    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()
        _snapshot_factory_defaults()

    def test_valid_header_returns_200(self):
        """Valid MAIN+BACKUP header returns 200 with expected output."""
        resp = self.client.post("/api/generate/epoch_fastip5", json={
            "variant": "hk",
            "header_text": VALID_HEADER_MAIN_BACKUP,
            "network": {},
        })
        self.assertEqual(resp.status_code, 200, f"Expected 200, got {resp.status_code}: {resp.data[:500]}")
        data = resp.get_json()
        self.assertTrue(data.get("ok"), f"Expected ok=True, got: {data}")

    def test_output_contains_system_host_name(self):
        """Output should contain 'set system host-name'."""
        resp = self.client.post("/api/generate/epoch_fastip5", json={
            "variant": "hk",
            "header_text": VALID_HEADER_MAIN_BACKUP,
            "network": {},
        })
        data = resp.get_json()
        output = data.get("output", "")
        self.assertIn("set system host-name", output)

    def test_output_contains_protocols_bgp(self):
        """Output should contain 'set protocols bgp'."""
        resp = self.client.post("/api/generate/epoch_fastip5", json={
            "variant": "hk",
            "header_text": VALID_HEADER_MAIN_BACKUP,
            "network": {},
        })
        data = resp.get_json()
        output = data.get("output", "")
        self.assertIn("set protocols bgp", output)

    def test_output_does_not_contain_template_literal(self):
        """Output must NOT contain the literal variable name TEMPLATE_EPOCH5_HK."""
        resp = self.client.post("/api/generate/epoch_fastip5", json={
            "variant": "hk",
            "header_text": VALID_HEADER_MAIN_BACKUP,
            "network": {},
        })
        data = resp.get_json()
        output = data.get("output", "")
        self.assertNotIn("TEMPLATE_EPOCH5_HK", output)

    def test_hostname_from_lineid(self):
        """Hostname should be extracted from lineid field."""
        resp = self.client.post("/api/generate/epoch_fastip5", json={
            "variant": "hk",
            "header_text": VALID_HEADER_MAIN_BACKUP,
            "network": {},
        })
        data = resp.get_json()
        output = data.get("output", "")
        self.assertIn("host-name '603642Ar3'", output)


class TestEpochFastIP5HKMainOnly(unittest.TestCase):
    """HK generation with only MAIN block (no BACKUP)."""

    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()
        _snapshot_factory_defaults()

    def test_main_only_returns_200(self):
        """HK generation with only MAIN block should still work."""
        resp = self.client.post("/api/generate/epoch_fastip5", json={
            "variant": "hk",
            "header_text": VALID_HEADER_MAIN_ONLY,
            "network": {},
        })
        self.assertEqual(resp.status_code, 200, f"Expected 200, got {resp.status_code}: {resp.data[:500]}")
        data = resp.get_json()
        self.assertTrue(data.get("ok"), f"Expected ok=True, got: {data}")

    def test_main_only_contains_host_name(self):
        """Output should contain 'set system host-name'."""
        resp = self.client.post("/api/generate/epoch_fastip5", json={
            "variant": "hk",
            "header_text": VALID_HEADER_MAIN_ONLY,
            "network": {},
        })
        data = resp.get_json()
        output = data.get("output", "")
        self.assertIn("set system host-name", output)

    def test_main_only_no_template_literal(self):
        """Output must NOT contain TEMPLATE_EPOCH5_HK."""
        resp = self.client.post("/api/generate/epoch_fastip5", json={
            "variant": "hk",
            "header_text": VALID_HEADER_MAIN_ONLY,
            "network": {},
        })
        data = resp.get_json()
        output = data.get("output", "")
        self.assertNotIn("TEMPLATE_EPOCH5_HK", output)


class TestEpochFastIP5OtherVariants(unittest.TestCase):
    """Implemented non-HK variants should generate, while domain split remains unavailable."""

    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()
        _snapshot_factory_defaults()

    def _post(self, variant: str, header_text: str, network: dict | None = None):
        return self.client.post("/api/generate/epoch_fastip5", json={
            "variant": variant,
            "header_text": header_text,
            "network": network or {},
        })

    def test_us_generation_returns_200(self):
        resp = self._post("us", VALID_US_HEADER)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("ok"), data.get("error"))
        output = data.get("output", "")
        self.assertIn("set protocols bgp", output)
        self.assertIn("nat source rule", output)

    def test_flink_generation_returns_200(self):
        resp = self._post("flink", VALID_FLINK_HEADER, {
            "ER5_FL_MAIN_NH_DEFAULT": "10.40.165.249",
            "ER5_FL_BACKUP_NH_DEFAULT": "10.40.165.253",
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("ok"), data.get("error"))
        output = data.get("output", "")
        self.assertIn("set protocols failover2 track tomain source-address '10.40.165.250'", output)
        self.assertIn("set firewall group network-group LAN-NET network 100.94.10.216/29", output)

    def test_new_exit_generation_returns_200(self):
        resp = self._post("new_exit", VALID_NEW_EXIT_HEADER, {
            "ER5_NE_FNET_NAT_RULE_DEFAULT": "345",
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("ok"), data.get("error"))
        output = data.get("output", "")
        self.assertIn("set interfaces tunnel tun2209", output)
        self.assertIn("set nat source rule", output)

    def test_new_exit_fnet_generates_100_100_failover2_config(self):
        resp = self._post("new_exit", VALID_NEW_EXIT_HEADER, {
            "ER5_NE_MAIN_PE_NH_DEFAULT": "10.40.165.249",
            "ER5_NE_BK_PE_NH_DEFAULT": "10.40.165.253",
            "ER5_NE_FNET_PROBE_DEFAULT": "100.100.100.1",
            "ER5_NE_FNET_EXIT_TUNNEL_DEFAULT": "tun2209",
            "ER5_NE_FNET_NAT_RULE_DEFAULT": "345",
        })

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("ok"), data.get("error"))
        output = data.get("output", "")

        self.assertIn("set firewall group network-group GROUP-FNET-Whitelist network '100.100.100.0/24'", output)
        self.assertIn("set protocols failover2 track tooutbound1 source-address '10.40.165.250'", output)
        self.assertIn("set protocols failover2 track tooutbound1 target '10.40.165.249'", output)
        self.assertIn("set protocols failover2 track tooutbound1 type 'icmp'", output)
        self.assertIn("set protocols failover2 route 100.100.100.0/24 next-hop 10.40.165.249 track 'tooutbound1'", output)
        self.assertIn("set firewall group network-group LAN-NET1 network '192.168.0.0/24'", output)
        self.assertIn("set nat source rule 1001 source group network-group 'LAN-NET1'", output)
        self.assertIn("set nat source rule 2001 source group network-group 'LAN-NET1'", output)
        self.assertIn("set nat source rule 345 outbound-interface name 'tun2209'", output)
        self.assertIn("set nat source rule 345 destination address 100.100.100.1", output)
        self.assertIn("set nat source rule 345 translation address '10.60.52.46'", output)

    def test_new_exit_requires_complete_100_100_init(self):
        resp = self._post("new_exit", VALID_NEW_EXIT_HEADER)

        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertFalse(data.get("ok"))
        self.assertIn("NAT Rule", data.get("error", ""))

    def test_new_exit_fnet_tunnel_defaults_to_main_tunnel(self):
        resp = self._post("new_exit", VALID_NEW_EXIT_HEADER, {
            "ER5_NE_FNET_EXIT_TUNNEL_DEFAULT": "tun",
            "ER5_NE_FNET_NAT_RULE_DEFAULT": "345",
        })

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("ok"), data.get("error"))
        output = data.get("output", "")
        self.assertIn("set nat source rule 345 outbound-interface name 'tun2209'", output)

    def test_new_exit_rejects_overlapping_nat_rules(self):
        resp = self._post("new_exit", VALID_NEW_EXIT_HEADER, {
            "ER5_NE_MAIN_NAT_RULE_DEFAULT": "1001",
            "ER5_NE_BK_NAT_RULE_DEFAULT": "1001",
            "ER5_NE_FNET_EXIT_TUNNEL_DEFAULT": "tun2209",
            "ER5_NE_FNET_NAT_RULE_DEFAULT": "345",
        })

        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertFalse(data.get("ok"))
        self.assertIn("NAT rule", data.get("error", ""))

    def test_new_exit_template_editor_defaults_include_100_100_probe(self):
        resp = self.client.get("/api/init-defaults/Epoch%20FastIP%205.0%20%C2%B7%20ER%20%E6%96%B0%E5%A2%9E%E5%87%BA%E5%8F%A3")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("ok"), data.get("error"))
        values = data.get("values", {})

        self.assertEqual(values.get("ER5_NE_FNET_PROBE_DEFAULT"), "100.100.100.1")
        self.assertEqual(values.get("ER5_NE_NAT_GROUP_DEFAULT"), "LAN-NET1")
        self.assertEqual(values.get("ER5_NE_NAT_SOURCE_CIDR_DEFAULT"), "192.168.0.0/24")
        self.assertEqual(values.get("ER5_NE_MAIN_PE_NH_DEFAULT"), "10.1.1.1")
        self.assertEqual(values.get("ER5_NE_BK_PE_NH_DEFAULT"), "10.2.1.1")
        self.assertEqual(values.get("ER5_NE_FNET_EXIT_TUNNEL_DEFAULT"), "tun")
        self.assertNotIn("ER5_NE_MAIN_MTU_DEFAULT", values)
        self.assertNotIn("ER5_NE_BK_MTU_DEFAULT", values)
        self.assertNotIn("ER5_NE_MAIN_MSS_DEFAULT", values)
        self.assertNotIn("ER5_NE_BK_MSS_DEFAULT", values)

    def test_domain_split_unimplemented(self):
        resp = self.client.post("/api/generate/epoch_fastip5", json={
            "variant": "domain_split",
            "header_text": VALID_HEADER_MAIN_BACKUP,
            "network": {},
        })
        self.assertEqual(resp.status_code, 400,
                         f"Expected 400 for variant 'domain_split', got {resp.status_code}")
        data = resp.get_json()
        self.assertFalse(data.get("ok"),
                         "Expected ok=False for variant 'domain_split'")
        err = data.get("error", "")
        self.assertIn("尚未实现", err,
                      f"Expected '尚未实现' in error for domain_split, got: {err}")

    def test_unknown_variant_returns_400(self):
        """An unknown variant should return 400."""
        resp = self.client.post("/api/generate/epoch_fastip5", json={
            "variant": "nonexistent_variant",
            "header_text": VALID_HEADER_MAIN_BACKUP,
            "network": {},
        })
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertFalse(data.get("ok"))


class TestEpochFastIP5HKNetworkParams(unittest.TestCase):
    """Custom network parameters should be reflected in output."""

    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()

    def test_custom_wan_cidr_in_output(self):
        """Custom WAN CIDR should appear in the generated output."""
        resp = self.client.post("/api/generate/epoch_fastip5", json={
            "variant": "hk",
            "header_text": VALID_HEADER_MAIN_BACKUP,
            "network": {
                "wan_cidr": "99.88.77.66/30",
            },
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        output = data.get("output", "")
        self.assertIn("address '99.88.77.66/30'", output)

    def test_custom_inner_nets_in_output(self):
        """Custom inner nets should appear in firewall network-group block."""
        resp = self.client.post("/api/generate/epoch_fastip5", json={
            "variant": "hk",
            "header_text": VALID_HEADER_MAIN_BACKUP,
            "network": {
                "inner_nets": "172.99.0.0/16\n10.99.0.0/24",
            },
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        output = data.get("output", "")
        self.assertIn("172.99.0.0/16", output)
        self.assertIn("10.99.0.0/24", output)

    def test_different_wan_cidr_produce_different_output(self):
        """Two generations with different WAN CIDRs should differ."""
        resp1 = self.client.post("/api/generate/epoch_fastip5", json={
            "variant": "hk",
            "header_text": VALID_HEADER_MAIN_BACKUP,
            "network": {"wan_cidr": "1.1.1.1/30"},
        })
        resp2 = self.client.post("/api/generate/epoch_fastip5", json={
            "variant": "hk",
            "header_text": VALID_HEADER_MAIN_BACKUP,
            "network": {"wan_cidr": "2.2.2.2/30"},
        })
        out1 = resp1.get_json().get("output", "")
        out2 = resp2.get_json().get("output", "")
        self.assertNotEqual(out1, out2)

    def test_default_dns_address_group_present(self):
        """DNS-NET address group should contain hardcoded DNS IPs."""
        resp = self.client.post("/api/generate/epoch_fastip5", json={
            "variant": "hk",
            "header_text": VALID_HEADER_MAIN_BACKUP,
            "network": {},
        })
        data = resp.get_json()
        output = data.get("output", "")
        self.assertIn("DNS-NET address 8.8.8.8", output)
        self.assertIn("DNS-NET address 8.8.4.4", output)


# ── Runner ──

if __name__ == "__main__":
    unittest.main(verbosity=2)
