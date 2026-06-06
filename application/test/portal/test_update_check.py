"""脱机单元测试：覆盖版本比较 / 配置加载 / 网络失败 / 镜像兜底 / 缓存。

不依赖外网；用 monkeypatch 模拟 GitHub / 镜像响应。
"""
from __future__ import annotations

import json
import sys
import time
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import update_check  # noqa: E402


class VersionCompareTests(unittest.TestCase):
    def test_basic_older(self):
        self.assertEqual(update_check.compare_versions("0.2.2", "0.3.0"), "older")

    def test_basic_same(self):
        self.assertEqual(update_check.compare_versions("1.0.0", "1.0.0"), "same")

    def test_basic_newer(self):
        self.assertEqual(update_check.compare_versions("2.0.0", "1.9.99"), "newer")

    def test_v_prefix(self):
        self.assertEqual(update_check.compare_versions("v0.2.2", "v0.3.0"), "older")

    def test_pre_release_stripped(self):
        # 0.3.0-rc1 与 0.3.0 当作同一核心版本。这是显式选择，避免 pre-release 比较带来的歧义。
        self.assertEqual(update_check.compare_versions("0.3.0-rc1", "0.3.0"), "same")

    def test_short_form(self):
        self.assertEqual(update_check.compare_versions("1.2", "1.2.0"), "same")
        self.assertEqual(update_check.compare_versions("1", "1.0.1"), "older")

    def test_incomparable_when_local_missing(self):
        self.assertEqual(update_check.compare_versions(None, "1.0.0"), "incomparable")

    def test_incomparable_when_remote_garbage(self):
        self.assertEqual(update_check.compare_versions("1.0.0", "tag-123-abc"), "incomparable")

    def test_incomparable_both_garbage(self):
        self.assertEqual(update_check.compare_versions("dev", "main"), "incomparable")


class ParseSemverTests(unittest.TestCase):
    def test_none(self):
        self.assertIsNone(update_check._parse_semver(None))

    def test_empty(self):
        self.assertIsNone(update_check._parse_semver(""))

    def test_non_string(self):
        self.assertIsNone(update_check._parse_semver(123))

    def test_letters(self):
        self.assertIsNone(update_check._parse_semver("alpha"))

    def test_too_many_parts(self):
        self.assertIsNone(update_check._parse_semver("1.2.3.4.5"))


def _ok(version, *, html_url="https://example/release", asset="https://example/x.zip"):
    return {
        "tag_name": version,
        "html_url": html_url,
        "assets": [{"name": "bundle.zip", "browser_download_url": asset}],
    }


class CheckFlowTests(unittest.TestCase):
    def setUp(self):
        update_check.reset_cache_for_tests()

    def tearDown(self):
        update_check.reset_cache_for_tests()

    def _make_cfg(self, **overrides):
        cfg = dict(update_check.DEFAULT_CONFIG)
        cfg.update(overrides)
        return cfg

    def test_ok_path_github_returns_update(self):
        cfg = self._make_cfg(github_repo="o/r", mirror_url="", cache_ttl_seconds=0)
        with mock.patch.object(update_check, "load_config", return_value=cfg), \
             mock.patch.object(update_check, "get_local_version", return_value="0.2.0"), \
             mock.patch.object(update_check, "fetch_github_latest",
                               return_value=("0.3.0", "https://gh/r/v0.3.0", "https://gh/x.zip")):
            r = update_check.check(force=True)
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["source"], "github")
        self.assertEqual(r["local_version"], "0.2.0")
        self.assertEqual(r["remote_version"], "0.3.0")
        self.assertEqual(r["comparison"], "older")
        self.assertTrue(r["has_update"])
        self.assertEqual(r["release_url"], "https://gh/r/v0.3.0")
        self.assertEqual(r["download_url"], "https://gh/x.zip")
        self.assertEqual(r["errors"], [])

    def test_ok_path_same_version_no_update_flag(self):
        cfg = self._make_cfg(github_repo="o/r", mirror_url="", cache_ttl_seconds=0)
        with mock.patch.object(update_check, "load_config", return_value=cfg), \
             mock.patch.object(update_check, "get_local_version", return_value="0.3.0"), \
             mock.patch.object(update_check, "fetch_github_latest",
                               return_value=("0.3.0", "u", None)):
            r = update_check.check(force=True)
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["comparison"], "same")
        self.assertFalse(r["has_update"])

    def test_incomparable_keeps_has_update_false(self):
        """严守不猜测：local 不可解析时不能默认成 has_update=True 也不能默认成 same。"""
        cfg = self._make_cfg(github_repo="o/r", mirror_url="", cache_ttl_seconds=0)
        with mock.patch.object(update_check, "load_config", return_value=cfg), \
             mock.patch.object(update_check, "get_local_version", return_value=None), \
             mock.patch.object(update_check, "fetch_github_latest",
                               return_value=("0.3.0", "u", None)):
            r = update_check.check(force=True)
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["comparison"], "incomparable")
        self.assertFalse(r["has_update"])
        self.assertIsNone(r["local_version"])
        self.assertEqual(r["remote_version"], "0.3.0")

    def test_github_fail_then_mirror_succeeds(self):
        cfg = self._make_cfg(github_repo="o/r", mirror_url="https://m/v.json", cache_ttl_seconds=0)
        gh_err = urllib.error.URLError("no internet")
        with mock.patch.object(update_check, "load_config", return_value=cfg), \
             mock.patch.object(update_check, "get_local_version", return_value="0.2.0"), \
             mock.patch.object(update_check, "fetch_github_latest", side_effect=gh_err), \
             mock.patch.object(update_check, "fetch_mirror_manifest",
                               return_value=("0.4.0", "https://m/release", "https://m/x.zip")):
            r = update_check.check(force=True)
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["source"], "mirror")
        self.assertEqual(r["remote_version"], "0.4.0")
        self.assertTrue(r["has_update"])
        self.assertEqual(len(r["errors"]), 1)
        self.assertIn("github", r["errors"][0])
        self.assertIn("URLError", r["errors"][0])

    def test_all_sources_fail_returns_network_error(self):
        cfg = self._make_cfg(github_repo="o/r", mirror_url="https://m/v.json", cache_ttl_seconds=0)
        err = urllib.error.URLError("dead")
        with mock.patch.object(update_check, "load_config", return_value=cfg), \
             mock.patch.object(update_check, "get_local_version", return_value="0.2.0"), \
             mock.patch.object(update_check, "fetch_github_latest", side_effect=err), \
             mock.patch.object(update_check, "fetch_mirror_manifest", side_effect=err):
            r = update_check.check(force=True)
        self.assertEqual(r["status"], "network_error")
        self.assertFalse(r["has_update"])
        self.assertEqual(len(r["errors"]), 2)
        self.assertEqual(r["local_version"], "0.2.0")
        # 严守：网络失败时 remote_version 必须为 None，绝不"沿用上一次"假装最新
        self.assertIsNone(r["remote_version"])

    def test_no_sources_configured_returns_config_error(self):
        cfg = self._make_cfg(github_repo="", mirror_url="", cache_ttl_seconds=0)
        with mock.patch.object(update_check, "load_config", return_value=cfg), \
             mock.patch.object(update_check, "get_local_version", return_value="0.2.0"):
            r = update_check.check(force=True)
        self.assertEqual(r["status"], "config_error")
        self.assertIn("github_repo", r["message"])

    def test_cache_hit_within_ttl(self):
        cfg = self._make_cfg(github_repo="o/r", mirror_url="", cache_ttl_seconds=3600)
        calls = {"n": 0}

        def fake_fetch(*a, **kw):
            calls["n"] += 1
            return ("0.3.0", "u", None)

        with mock.patch.object(update_check, "load_config", return_value=cfg), \
             mock.patch.object(update_check, "get_local_version", return_value="0.2.0"), \
             mock.patch.object(update_check, "fetch_github_latest", side_effect=fake_fetch):
            r1 = update_check.check(force=False)
            r2 = update_check.check(force=False)
        self.assertEqual(calls["n"], 1)
        self.assertFalse(r1["from_cache"])
        self.assertTrue(r2["from_cache"])

    def test_force_bypasses_cache(self):
        cfg = self._make_cfg(github_repo="o/r", mirror_url="", cache_ttl_seconds=3600)
        calls = {"n": 0}

        def fake_fetch(*a, **kw):
            calls["n"] += 1
            return ("0.3.0", "u", None)

        with mock.patch.object(update_check, "load_config", return_value=cfg), \
             mock.patch.object(update_check, "get_local_version", return_value="0.2.0"), \
             mock.patch.object(update_check, "fetch_github_latest", side_effect=fake_fetch):
            update_check.check(force=False)
            update_check.check(force=True)
        self.assertEqual(calls["n"], 2)


class ConfigTests(unittest.TestCase):
    def test_default_when_missing_file(self):
        with mock.patch.object(update_check, "_HERE", Path("/nonexistent/path")):
            cfg = update_check.load_config(Path("/nonexistent/path/x.json"))
        self.assertEqual(cfg["github_repo"], update_check.DEFAULT_CONFIG["github_repo"])

    def test_user_overrides(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "update_config.json"
            p.write_text(json.dumps({
                "github_repo": "custom/repo",
                "mirror_url": "https://example/v.json",
                "timeout_seconds": 10,
            }), encoding="utf-8")
            cfg = update_check.load_config(p)
        self.assertEqual(cfg["github_repo"], "custom/repo")
        self.assertEqual(cfg["mirror_url"], "https://example/v.json")
        self.assertEqual(cfg["timeout_seconds"], 10)

    def test_corrupt_config_records_error(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "update_config.json"
            p.write_text("{not json", encoding="utf-8")
            cfg = update_check.load_config(p)
        self.assertIn("_config_error", cfg)
        # 默认值仍可用，避免单点配置错误把整个检查机制搞瘫
        self.assertEqual(cfg["github_repo"], update_check.DEFAULT_CONFIG["github_repo"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
