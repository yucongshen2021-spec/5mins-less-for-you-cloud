#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Integration tests for Epoch FastIP 5.0 Flink generation."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _bootstrap  # noqa: F401
from app import app, _snapshot_factory_defaults


FLINK_HEADER = (
    "PE: szd-vupe6  FPE: F-ShenZhen4  预留IP: 100.94.10.216/29\n"
    "PE: bja-vupe6  FPE: F-BeiJing4  预留IP: 100.93.10.216/29\n"
    "PE: sha-vupe6  FPE: F-ShangHai4  预留IP: 100.92.10.216/29"
)


class TestEpochFastIP5FlinkFailover(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()
        _snapshot_factory_defaults()

    def test_failover_source_is_derived_from_main_next_hop(self):
        resp = self.client.post("/api/generate/epoch_fastip5", json={
            "variant": "flink",
            "header_text": FLINK_HEADER,
            "network": {
                "ER5_FL_MAIN_NH_DEFAULT": "10.40.165.249",
                "ER5_FL_BACKUP_NH_DEFAULT": "10.40.165.253",
                "ER5_FL_FAILOVER_SRC_DEFAULT": "10.99.99.99",
            },
        })

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("ok"), data.get("error"))
        output = data.get("output", "")

        self.assertIn("set protocols failover2 track tomain source-address '10.40.165.250'", output)
        self.assertIn("set protocols failover2 track tomain target '10.40.165.249'", output)
        self.assertNotIn("10.99.99.99", output)

    def test_template_editor_init_defaults_do_not_expose_failover_source(self):
        resp = self.client.get("/api/init-defaults/Epoch%20FastIP%205.0%20%C2%B7%20ER%20%E9%A3%9E%E8%BF%9E",
                               headers={"X-User-Id": "test-user-1"})

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("ok"), data.get("error"))
        values = data.get("values", {})

        self.assertIn("ER5_FL_MAIN_NH_DEFAULT", values)
        self.assertIn("ER5_FL_BACKUP_NH_DEFAULT", values)
        self.assertEqual(values["ER5_FL_MAIN_NH_DEFAULT"], "10.1.1.1")
        self.assertEqual(values["ER5_FL_BACKUP_NH_DEFAULT"], "10.2.1.1")
        self.assertNotIn("ER5_FL_FAILOVER_SRC_DEFAULT", values)

    def test_epoch4_template_editor_init_defaults_use_new_next_hops(self):
        resp = self.client.get("/api/init-defaults/Epoch%20FastIP%20%C2%B7%20ER%20%E9%A3%9E%E8%BF%9E",
                               headers={"X-User-Id": "test-user-1"})

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("ok"), data.get("error"))
        values = data.get("values", {})

        self.assertEqual(values.get("ER_FL_MAIN_NH_DEFAULT"), "10.1.1.1")
        self.assertEqual(values.get("ER_FL_BACKUP_NH_DEFAULT"), "10.2.1.1")

    def test_epoch4_flink_generation_uses_new_default_next_hops(self):
        resp = self.client.post("/api/generate/epoch_fastip", json={
            "variant": "flink",
            "header_text": FLINK_HEADER,
            "network": {},
        })

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("ok"), data.get("error"))
        output = data.get("output", "")

        self.assertIn("set track name flink test 0 target 10.1.1.1", output)
        self.assertIn("next-hop 10.1.1.1 track flink", output)
        self.assertIn("next-hop 10.2.1.1 distance 5", output)

    def test_epoch5_flink_generation_uses_new_default_next_hops(self):
        resp = self.client.post("/api/generate/epoch_fastip5", json={
            "variant": "flink",
            "header_text": FLINK_HEADER,
            "network": {},
        })

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("ok"), data.get("error"))
        output = data.get("output", "")

        self.assertIn("set protocols failover2 track tomain source-address '10.1.1.2'", output)
        self.assertIn("set protocols failover2 track tomain target '10.1.1.1'", output)
        self.assertIn("next-hop 10.1.1.1 track 'tomain'", output)
        self.assertIn("next-hop 10.2.1.1 distance 10", output)


if __name__ == "__main__":
    unittest.main()
