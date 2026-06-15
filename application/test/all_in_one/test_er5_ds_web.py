"""E2E test: 5.0 ER domain split web endpoint."""
import json
import os
import sys
import unittest
import urllib.request
import urllib.error

# Start the Flask app for testing
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "web"))

# Import the app
from app import app as flask_app

BASE = "http://127.0.0.1:5002"


class Test5DomainSplitWebAPI(unittest.TestCase):
    """Test the /api/generate/epoch_fastip5 endpoint for domain_split."""

    @classmethod
    def setUpClass(cls):
        flask_app.config["TESTING"] = True
        cls.client = flask_app.test_client()

    def _post(self, variant, network, header_text=""):
        return self.client.post(
            "/api/generate/epoch_fastip5",
            data=json.dumps({"variant": variant, "network": network, "header_text": header_text}),
            content_type="application/json",
        )

    def test_domain_split_returns_200_with_defaults(self):
        """With default form values, should return 200 and output."""
        net = {
            "ER5_DS_DOMAINS_DEFAULT": "google.com",
            "ER5_DS_ADDR_GROUP_DEFAULT": "to-US",
            "ER5_DS_RULE_NUM_DEFAULT": "100",
            "ER5_DS_TABLE_NUM_DEFAULT": "139",
            "ER5_DS_DNS1_DEFAULT": "8.8.8.8",
            "ER5_DS_ETH_DEFAULT": "eth0",
            "ER5_DS_TABLE_NH_PRIMARY_DEFAULT": "2.2.2.2",
            "ER5_DS_STATIC32_PRIMARY_NH_DEFAULT": "10.22.15.185",
        }
        resp = self._post("domain_split", net)
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data.get("ok"), f"Expected ok=true, got: {data}")
        out = data.get("output", "")
        self.assertIn("domain-list", out)
        self.assertIn("name-server 8.8.8.8", out)
        self.assertIn("google.com", out)

    def test_domain_split_with_fnet_failover2(self):
        """With full FNET params, should include failover2 syntax."""
        net = {
            "ER5_DS_DOMAINS_DEFAULT": "google.com",
            "ER5_DS_ADDR_GROUP_DEFAULT": "togemini",
            "ER5_DS_RULE_NUM_DEFAULT": "100",
            "ER5_DS_TABLE_NUM_DEFAULT": "139",
            "ER5_DS_DNS1_DEFAULT": "8.8.8.8",
            "ER5_DS_ETH_DEFAULT": "eth0",
            "ER5_DS_TABLE_NH_PRIMARY_DEFAULT": "2.2.2.2",
            "ER5_DS_STATIC32_PRIMARY_NH_DEFAULT": "10.22.15.185",
            "ER5_DS_STATIC32_BACKUP_NH_DEFAULT": "10.22.15.189",
            "ER5_DS_TRACK_NAME_DEFAULT": "tooutbound1",
            "ER5_DS_FNET_NAT_RULE_DEFAULT": "123",
            "ER5_DS_EXIT_TUNNEL_DEFAULT": "tun1111",
            "ER5_DS_EXIT_SNAT_IP_DEFAULT": "5.5.5.5",
            "ER5_DS_FNET_PROBE_DEFAULT": "100.100.100.1",
            "ER5_DS_FAILOVER_SRC_DEFAULT": "10.22.15.186",
        }
        resp = self._post("domain_split", net)
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data.get("ok"), f"Expected ok=true, got: {data.get('error', data)}")
        out = data.get("output", "")
        self.assertIn("failover2 route", out)
        self.assertIn("failover2 track tooutbound1 type 'icmp'", out)
        self.assertIn("set nat source rule 123 destination", out)

    def test_domain_split_empty_domains_returns_error(self):
        """Empty domain list should return 400 with error."""
        net = {
            "ER5_DS_DOMAINS_DEFAULT": "",
            "ER5_DS_ADDR_GROUP_DEFAULT": "to-US",
            "ER5_DS_DNS1_DEFAULT": "8.8.8.8",
        }
        resp = self._post("domain_split", net)
        self.assertEqual(resp.status_code, 400)
        data = json.loads(resp.data)
        self.assertFalse(data.get("ok"))
        self.assertIn("域名", data.get("error", ""))

    def test_domain_split_no_4_dot_0_remnants(self):
        """Output must NOT contain 4.0-specific syntax."""
        net = {
            "ER5_DS_DOMAINS_DEFAULT": "google.com",
            "ER5_DS_DNS1_DEFAULT": "8.8.8.8",
        }
        resp = self._post("domain_split", net)
        self.assertEqual(resp.status_code, 200)
        out = json.loads(resp.data).get("output", "")
        self.assertNotIn(" domainlist ", out)  # 4.0 syntax
        self.assertNotIn("server '8.8.8.8'", out)  # 4.0 syntax

    def test_domain_split_multiple_domains(self):
        """Multiple domains should all appear in heredoc."""
        net = {
            "ER5_DS_DOMAINS_DEFAULT": "google.com\nyoutube.com\nfacebook.com",
            "ER5_DS_DNS1_DEFAULT": "8.8.8.8",
        }
        resp = self._post("domain_split", net)
        self.assertEqual(resp.status_code, 200)
        out = json.loads(resp.data).get("output", "")
        self.assertIn("google.com", out)
        self.assertIn("youtube.com", out)
        self.assertIn("facebook.com", out)

    def test_domain_split_source_cidr(self):
        """Source CIDR should appear when set."""
        net = {
            "ER5_DS_DOMAINS_DEFAULT": "google.com",
            "ER5_DS_SOURCE_CIDR_DEFAULT": "192.168.5.0/24",
            "ER5_DS_DNS1_DEFAULT": "8.8.8.8",
        }
        resp = self._post("domain_split", net)
        self.assertEqual(resp.status_code, 200)
        out = json.loads(resp.data).get("output", "")
        self.assertIn("source address 192.168.5.0/24", out)


class Test5DomainSplitInitDefaults(unittest.TestCase):
    """Test that defaults API returns ER5_DS_* keys."""

    @classmethod
    def setUpClass(cls):
        flask_app.config["TESTING"] = True
        cls.client = flask_app.test_client()

    def test_init_defaults_returns_er5_ds_keys(self):
        from urllib.parse import quote
        key = quote("Epoch FastIP 5.0 · ER 域名分流", safe="")
        resp = self.client.get(f"/api/init-defaults/{key}")
        self.assertIn(resp.status_code, (200, 404))  # 404 if not in snapshot yet
        data = json.loads(resp.data)
        if data.get("ok"):
            values = data.get("values", {})
            # When populated, should have the DS keys
            for k in ("ER5_DS_DOMAINS_DEFAULT", "ER5_DS_ADDR_GROUP_DEFAULT", "ER5_DS_DNS1_DEFAULT"):
                if values:
                    self.assertIn(k, values, f"Missing key {k} in init defaults")


if __name__ == "__main__":
    unittest.main()
