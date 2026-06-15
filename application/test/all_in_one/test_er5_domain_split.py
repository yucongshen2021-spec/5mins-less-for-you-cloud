"""Tests for 5.0 ER domain split — updated output format."""
import os, sys, unittest
SRC = os.path.join(os.path.dirname(__file__), "..", "..", "src")
sys.path.insert(0, SRC)

def _fresh_er5(**overrides):
    for k in list(sys.modules):
        if "er_fastip_5in1_v1" in k: del sys.modules[k]
    import er_fastip_5in1_v1 as er5
    for k, v in overrides.items():
        setattr(er5, k, v)
    return er5


class Test5DomainSplitDefaults(unittest.TestCase):
    def test_defaults_generate_output(self):
        er5 = _fresh_er5()
        out, err = er5.build_epoch5_domain_split_format_dict("google.com")
        self.assertIsNone(err, f"Expected no error, got: {err}")
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

    def test_policy_route_interface(self):
        er5 = _fresh_er5()
        out, err = er5.build_epoch5_domain_split_format_dict("google.com")
        self.assertIsNone(err)
        self.assertIn("set policy route LAN-MAP-to-US interface 'eth0'", out)

    def test_failover2_syntax(self):
        """With track+FNET: routes use failover2, track has target+type only."""
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
        # failover2 track: target + type only (no source-address)
        self.assertIn("set protocols failover2 track tooutbound1 target '100.100.100.1'", out)
        self.assertIn("set protocols failover2 track tooutbound1 type 'icmp'", out)
        self.assertNotIn("source-address", out)
        # /32 routes use failover2 route
        self.assertIn("set protocols failover2 route 2.2.2.2/32 next-hop 10.22.15.185 track tooutbound1", out)
        # FNET whitelist early
        self.assertLess(out.find("set firewall group network-group"), out.find("domain-list"))
        # NAT at end
        self.assertIn("set nat source rule 123 destination", out)

    def test_no_fnet_no_failover2(self):
        """Without FNET: no failover2, use static routes."""
        er5 = _fresh_er5(ER5_DS_TRACK_NAME_DEFAULT="")
        out, err = er5.build_epoch5_domain_split_format_dict("google.com")
        self.assertIsNone(err)
        self.assertIn("set protocols static route 2.2.2.2/32 next-hop 10.22.15.185", out)
        self.assertNotIn("failover2", out)

    def test_heredoc_contains_domains(self):
        er5 = _fresh_er5()
        out, err = er5.build_epoch5_domain_split_format_dict("google.com\nyoutube.com")
        self.assertIsNone(err)
        self.assertIn("google.com", out)
        self.assertIn("youtube.com", out)

    def test_source_cidr(self):
        er5 = _fresh_er5(ER5_DS_SOURCE_CIDR_DEFAULT="192.168.5.0/24")
        out, err = er5.build_epoch5_domain_split_format_dict("google.com")
        self.assertIsNone(err)
        self.assertIn("source address 192.168.5.0/24", out)


class Test5DomainSplitErrors(unittest.TestCase):
    def test_empty_header(self):
        er5 = _fresh_er5()
        out, err = er5.build_epoch5_domain_split_format_dict("")
        self.assertIsNone(out)

    def test_illegal_chars(self):
        er5 = _fresh_er5()
        out, err = er5.build_epoch5_domain_split_format_dict("google.com; rm")
        self.assertIsNone(out)


class Test5DomainSplitAgainstUserExample(unittest.TestCase):
    def test_full_output_matches_user_format(self):
        er5 = _fresh_er5(
            ER5_DS_ADDR_GROUP_DEFAULT="togemini",
            ER5_DS_DNS1_DEFAULT="8.8.8.8",
            ER5_DS_ETH_DEFAULT="eth0",
            ER5_DS_TABLE_NH_PRIMARY_DEFAULT="2.2.2.2",
            ER5_DS_STATIC32_PRIMARY_NH_DEFAULT="10.22.15.185",
            ER5_DS_STATIC32_BACKUP_NH_DEFAULT="10.22.15.189",
            ER5_DS_TRACK_NAME_DEFAULT="tomainout",
            ER5_DS_FNET_NAT_RULE_DEFAULT="123",
            ER5_DS_EXIT_TUNNEL_DEFAULT="tun1111",
            ER5_DS_EXIT_SNAT_IP_DEFAULT="5.5.5.5",
            ER5_DS_FNET_PROBE_DEFAULT="100.100.100.1",
        )
        out, err = er5.build_epoch5_domain_split_format_dict("google.com")
        self.assertIsNone(err, f"Error: {err}")

        # Check user's output order
        patterns = [
            "set firewall group address-group togemini",
            "set firewall group network-group GROUP-FNET-Whitelist network 100.100.100.0/24",
            "domain-list Atogemini address-group 'togemini'",
            "name-server 8.8.8.8",
            "set policy route LAN-MAP-togemini interface 'eth0'",
            "set protocols static table 139 route 0.0.0.0/0 next-hop  2.2.2.2",
            "set protocols failover2 track tomainout target '100.100.100.1'",
            "set protocols failover2 track tomainout type 'icmp'",
            "set protocols failover2 route 2.2.2.2/32 next-hop 10.22.15.185 track tomainout",
            "set protocols failover2 route 2.2.2.2/32 next-hop 10.22.15.189 distance '20'",
            "set nat source rule 123 destination address 100.100.100.1/32",
            "set nat source rule 123 outbound-interface 'tun1111'",
            "set nat source rule 123 translation address '5.5.5.5'",
            "set protocols static route 100.100.100.1/32 next-hop 10.22.15.185",
        ]
        for pat in patterns:
            self.assertIn(pat, out, f"Missing: {pat!r}")

        # Verify order: FNET whitelist before domain-list
        self.assertLess(out.find("set firewall group network-group"), out.find("domain-list"))
        # NAT rules at end
        nat_pos = out.find("set nat source rule")
        last_pos = out.rfind("set protocols static route 100")
        self.assertGreater(last_pos, nat_pos)


if __name__ == "__main__":
    unittest.main()
