"""E2E test: 5.0 ER domain split web endpoint — updated output format."""
import json, sys, os, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "web"))
from app import app as flask_app


class Test5DomainSplitWebAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        flask_app.config["TESTING"] = True
        cls.client = flask_app.test_client()

    def _post(self, variant, network, header_text=""):
        return self.client.post("/api/generate/epoch_fastip5",
            data=json.dumps({"variant": variant, "network": network, "header_text": header_text}),
            content_type="application/json")

    def test_returns_200_with_defaults(self):
        net = {"ER5_DS_DOMAINS_DEFAULT": "google.com", "ER5_DS_DNS1_DEFAULT": "8.8.8.8"}
        resp = self._post("domain_split", net)
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data.get("ok"))
        out = data.get("output", "")
        self.assertIn("domain-list", out)
        self.assertIn("name-server 8.8.8.8", out)

    def test_failover2_no_source_address(self):
        """failover2 track must NOT have source-address."""
        net = {
            "ER5_DS_DOMAINS_DEFAULT": "google.com",
            "ER5_DS_ADDR_GROUP_DEFAULT": "togemini", "ER5_DS_DNS1_DEFAULT": "8.8.8.8",
            "ER5_DS_TRACK_NAME_DEFAULT": "tooutbound1",
            "ER5_DS_STATIC32_PRIMARY_NH_DEFAULT": "10.22.15.185",
            "ER5_DS_FNET_NAT_RULE_DEFAULT": "123",
            "ER5_DS_EXIT_TUNNEL_DEFAULT": "tun1111",
            "ER5_DS_EXIT_SNAT_IP_DEFAULT": "5.5.5.5",
            "ER5_DS_FNET_PROBE_DEFAULT": "100.100.100.1",
        }
        resp = self._post("domain_split", net)
        self.assertEqual(resp.status_code, 200)
        out = json.loads(resp.data).get("output", "")
        self.assertIn("failover2 route", out)
        self.assertIn("failover2 track tooutbound1 type 'icmp'", out)
        self.assertNotIn("source-address", out)
        # /32 routes use failover2
        self.assertIn("failover2 route 2.2.2.2/32", out)

    def test_empty_domains_error(self):
        net = {"ER5_DS_DOMAINS_DEFAULT": ""}
        resp = self._post("domain_split", net)
        self.assertEqual(resp.status_code, 400)

    def test_no_4_dot_0_syntax(self):
        net = {"ER5_DS_DOMAINS_DEFAULT": "google.com", "ER5_DS_DNS1_DEFAULT": "8.8.8.8"}
        resp = self._post("domain_split", net)
        out = json.loads(resp.data).get("output", "")
        self.assertNotIn(" domainlist ", out)


if __name__ == "__main__":
    unittest.main()
