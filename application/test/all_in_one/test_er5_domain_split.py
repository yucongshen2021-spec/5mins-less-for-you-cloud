"""Tests for 5.0 ER domain split — verify VyOS set syntax output."""
import os
import sys
import unittest

SRC = os.path.join(os.path.dirname(__file__), "..", "..", "src")
sys.path.insert(0, SRC)


def _fresh_er5(**overrides):
    """Load a fresh er_fastip_5in1_v1 module with overridden defaults."""
    for k in list(sys.modules):
        if "er_fastip_5in1_v1" in k:
            del sys.modules[k]
    import er_fastip_5in1_v1 as er5
    for k, v in overrides.items():
        setattr(er5, k, v)
    return er5


class Test5DomainSplitDefaults(unittest.TestCase):
    """Test output with factory defaults."""

    def test_defaults_generate_output(self):
        er5 = _fresh_er5()
        out, err = er5.build_epoch5_domain_split_format_dict("google.com")
        self.assertIsNone(err, f"Expected no error, got: {err}")
        self.assertIsNotNone(out)
        self.assertIn("google.com", out)
        self.assertIn("domain-list", out)

    def test_5_dot_0_key_syntax(self):
        er5 = _fresh_er5()
        out, err = er5.build_epoch5_domain_split_format_dict("google.com")
        self.assertIsNone(err)
        self.assertIn("domain-list", out)
        self.assertNotIn(" domainlist ", out)

    def test_name_server_no_quotes(self):
        er5 = _fresh_er5()
        out, err = er5.build_epoch5_domain_split_format_dict("google.com")
        self.assertIsNone(err)
        self.assertIn("name-server 209.244.0.3", out)
        self.assertNotIn("server '209.244.0.3'", out)

    def test_policy_route_interface(self):
        er5 = _fresh_er5()
        out, err = er5.build_epoch5_domain_split_format_dict("google.com")
        self.assertIsNone(err)
        self.assertIn("set policy route LAN-MAP-to-US interface 'eth0'", out)
        self.assertIn("set policy route LAN-MAP-to-US rule 100 destination", out)

    def test_failover2_syntax_when_fnet_configured(self):
        er5 = _fresh_er5(
            ER5_DS_FNET_NAT_RULE_DEFAULT="123",
            ER5_DS_EXIT_TUNNEL_DEFAULT="tun1111",
            ER5_DS_EXIT_SNAT_IP_DEFAULT="5.5.5.5",
            ER5_DS_TRACK_NAME_DEFAULT="tooutbound1",
            ER5_DS_STATIC32_PRIMARY_NH_DEFAULT="10.22.15.185",
            ER5_DS_FNET_PROBE_DEFAULT="100.100.100.1",
        )
        out, err = er5.build_epoch5_domain_split_format_dict("google.com")
        self.assertIsNone(err, f"Error: {err}")
        self.assertIn("failover2 route", out)
        self.assertIn("failover2 track", out)
        self.assertIn("failover2 track tooutbound1 type 'icmp'", out)

    def test_failover2_not_generated_without_track_name(self):
        er5 = _fresh_er5(
            ER5_DS_FNET_NAT_RULE_DEFAULT="123",
            ER5_DS_EXIT_TUNNEL_DEFAULT="tun1111",
            ER5_DS_EXIT_SNAT_IP_DEFAULT="5.5.5.5",
            ER5_DS_TRACK_NAME_DEFAULT="",
            ER5_DS_STATIC32_PRIMARY_NH_DEFAULT="10.22.15.185",
            ER5_DS_FNET_PROBE_DEFAULT="100.100.100.1",
        )
        out, err = er5.build_epoch5_domain_split_format_dict("google.com")
        self.assertIsNone(err, f"Error: {err}")
        self.assertIn("set nat source rule 123 destination", out)
        self.assertNotIn("failover2", out)

    def test_heredoc_contains_domains(self):
        er5 = _fresh_er5()
        out, err = er5.build_epoch5_domain_split_format_dict("google.com\nyoutube.com")
        self.assertIsNone(err)
        self.assertIn("google.com", out)
        self.assertIn("youtube.com", out)
        self.assertIn("sudo tee", out)
        self.assertIn("sudo chmod 777", out)

    def test_multiple_dns(self):
        er5 = _fresh_er5(ER5_DS_DNS2_DEFAULT="8.8.4.4")
        out, err = er5.build_epoch5_domain_split_format_dict("google.com")
        self.assertIsNone(err, f"Error: {err}")
        self.assertIn("name-server 8.8.4.4", out)


class Test5DomainSplitErrors(unittest.TestCase):

    def test_empty_header(self):
        er5 = _fresh_er5()
        out, err = er5.build_epoch5_domain_split_format_dict("")
        self.assertIsNone(out)
        self.assertIsNotNone(err)

    def test_whitespace_only(self):
        er5 = _fresh_er5()
        out, err = er5.build_epoch5_domain_split_format_dict("   \n  \n   ")
        self.assertIsNone(out)
        self.assertIsNotNone(err)

    def test_illegal_chars_in_domain(self):
        er5 = _fresh_er5()
        out, err = er5.build_epoch5_domain_split_format_dict("google.com; rm -rf /")
        self.assertIsNone(out)
        self.assertIn("非法", err or "")


class Test5DomainSplitSourceCIDR(unittest.TestCase):

    def test_source_cidr_in_output(self):
        er5 = _fresh_er5(ER5_DS_SOURCE_CIDR_DEFAULT="192.168.5.0/24")
        out, err = er5.build_epoch5_domain_split_format_dict("google.com")
        self.assertIsNone(err, f"Error: {err}")
        self.assertIn("source address 192.168.5.0/24", out)

    def test_no_source_cidr(self):
        er5 = _fresh_er5(ER5_DS_SOURCE_CIDR_DEFAULT="")
        out, err = er5.build_epoch5_domain_split_format_dict("google.com")
        self.assertIsNone(err, f"Error: {err}")
        self.assertNotIn("source address", out)


class Test5DomainSplitAgainstUserExample(unittest.TestCase):
    """Verify output matches the user-provided 5.0 syntax patterns."""

    def test_full_output_matches_5_dot_0_patterns(self):
        er5 = _fresh_er5(
            ER5_DS_ADDR_GROUP_DEFAULT="togemini",
            ER5_DS_DOMAINS_DEFAULT="google.com",
            ER5_DS_RULE_NUM_DEFAULT="100",
            ER5_DS_TABLE_NUM_DEFAULT="139",
            ER5_DS_DNS1_DEFAULT="8.8.8.8",
            ER5_DS_ETH_DEFAULT="eth0",
            ER5_DS_TABLE_NH_PRIMARY_DEFAULT="2.2.2.2",
            ER5_DS_STATIC32_PRIMARY_NH_DEFAULT="10.22.15.185",
            ER5_DS_STATIC32_BACKUP_NH_DEFAULT="10.22.15.189",
            ER5_DS_TRACK_NAME_DEFAULT="tooutbound1",
            ER5_DS_FNET_NAT_RULE_DEFAULT="123",
            ER5_DS_EXIT_TUNNEL_DEFAULT="tun1111",
            ER5_DS_EXIT_SNAT_IP_DEFAULT="5.5.5.5",
            ER5_DS_FNET_PROBE_DEFAULT="100.100.100.1",
            ER5_DS_FAILOVER_SRC_DEFAULT="10.22.15.186",
        )
        out, err = er5.build_epoch5_domain_split_format_dict("google.com")
        self.assertIsNone(err, f"Error: {err}")

        # Check all 5.0-specific patterns
        expected = [
            "domain-list Atogemini address-group 'togemini'",
            "name-server 8.8.8.8",
            "set policy route LAN-MAP-togemini interface 'eth0'",
            "set policy route LAN-MAP-togemini rule 100 destination",
            "set protocols static table 139 route 0.0.0.0/0 next-hop  2.2.2.2",
            "set protocols static route 2.2.2.2/32 next-hop 10.22.15.185 track tooutbound1",
            "set protocols static route 2.2.2.2/32 next-hop 10.22.15.189 distance '20'",
            "set nat source rule 123 destination address 100.100.100.1/32",
            "set nat source rule 123 outbound-interface 'tun1111'",
            "set nat source rule 123 translation address '5.5.5.5'",
            "set protocols failover2 route 100.100.100.1/32 next-hop 10.22.15.185 track 'tooutbound1'",
            "set protocols failover2 track tooutbound1 source-address '10.22.15.186'",
            "set protocols failover2 track tooutbound1 target '100.100.100.1'",
            "set protocols failover2 track tooutbound1 type 'icmp'",
            "set firewall group network-group GROUP-FNET-Whitelist network 100.100.100.0/24",
        ]
        for exp in expected:
            self.assertIn(exp, out, f"Missing expected output: {exp!r}")


if __name__ == "__main__":
    unittest.main()
