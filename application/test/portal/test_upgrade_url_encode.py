"""Regression test for the URL encoding contract in the upgrade pipeline.

Locks down log/mistake.txt #47 + #54:
  - serve_mirror must emit a percent-encoded download_url (no raw 中文).
  - upgrade._encode_url_idempotent must be IDEMPOTENT: a raw URL and an
    already-encoded URL produce the same result, and no `%` ever becomes `%25`.
  - perform_upgrade must catch ValueError (covers UnicodeEncodeError) so a
    bad URL can never escape as an uncaught 500.
"""
from __future__ import annotations

import sys
import urllib.parse
import urllib.request
from pathlib import Path
from unittest import mock

import pytest

_HERE = Path(__file__).resolve().parents[2] / "portal"
sys.path.insert(0, str(_HERE))

import upgrade  # noqa: E402

PORTAL_DIR = _HERE
ROOT = _HERE.parent.parent


# ── _encode_url_idempotent ──────────────────────────────────────────────

class TestEncodeIdempotent:
    def _enc(self, url):
        return upgrade._encode_url_idempotent(url)

    def test_raw_chinese_filename_is_encoded(self):
        """Raw 中文 in path → percent-encoded (would crash urllib otherwise)."""
        url = "http://192.168.5.10:8000/api/update/download/帮你节省5分钟-1.1.18.zip"
        out = self._enc(url)
        assert "帮你节省" not in out
        assert "%E5%B8%AE" in out  # 帮 = U+5E2E = UTF-8 E5 B8 AE

    def test_already_encoded_url_is_not_double_encoded(self):
        """Pre-encoded URL must round-trip: no % → %25."""
        url = "http://192.168.5.10:8000/api/update/download/%E5%B8%AE%E4%BD%A0-1.1.18.zip"
        out = self._enc(url)
        assert out == url, f"double-encoded: {out}"
        assert "%25" not in out

    def test_idempotent_raw_equals_encoded(self):
        """Calling the encoder on the raw URL then on the encoded URL gives the same result."""
        raw = "http://host/d/帮你节省5分钟-1.1.18.zip"
        once = self._enc(raw)
        twice = self._enc(once)
        assert once == twice

    def test_github_asset_with_spaces_not_broken(self):
        """GitHub asset URLs commonly carry %20 (space); must not become %2520."""
        url = "https://github.com/o/r/releases/download/v1.0.0/my%20bundle.zip"
        assert self._enc(url) == url

    def test_port_preserved(self):
        url = "http://192.168.72.219:8000/api/update/download/x.zip"
        assert self._enc(url) == url  # nothing to encode, port intact

    def test_query_string_preserved(self):
        url = "https://host/d/file.zip?token=abc%20def&x=1"
        out = self._enc(url)
        # query stays as-is (we only encode path)
        assert "token=abc%20def" in out
        assert "%25" not in out

    def test_no_path(self):
        url = "http://host"
        assert self._enc(url) == "http://host"


# ── serve_mirror.build_manifest emits encoded download_url ──────────────

class TestMirrorManifestEncoding:
    def test_manifest_download_url_is_percent_encoded(self, tmp_path):
        """serve_mirror.build_manifest must return an encoded download_url."""
        sys.path.insert(0, str(ROOT / "tools"))
        import serve_mirror  # noqa: E402
        # Build a fake zip with a 中文 name + RELEASE_INFO.json
        import json
        import zipfile
        zip_path = tmp_path / "帮你节省5分钟-9.9.9.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("帮你节省5分钟/RELEASE_INFO.json",
                        json.dumps({"version": "9.9.9"}))
        manifest = serve_mirror.build_manifest(zip_path, "http://h:8000")
        dl = manifest["download_url"]
        assert "帮你节省5分钟" not in dl, "download_url still contains raw 中文"
        assert "%E5%B8%AE" in dl
        # The encoded filename, when unquoted, must equal the original filename
        tail = dl.rsplit("/", 1)[-1]
        assert urllib.parse.unquote(tail) == zip_path.name


# ── perform_upgrade catches ValueError (UnicodeEncodeError) ─────────────

class TestPerformUpgradeErrorHandling:
    def test_unicodeencodeerror_is_caught(self, tmp_path, monkeypatch):
        """A raw non-ASCII URL that somehow bypasses encoding must not bubble as 500."""
        # Force _download_with_progress to raise UnicodeEncodeError directly
        def _boom(url, dest, timeout=120):
            raise UnicodeEncodeError("ascii", "帮你", 0, 2, "no ascii")
            yield  # pragma: no cover  (make it a generator)
        monkeypatch.setattr(upgrade, "_download_with_progress", _boom)
        # Redirect _PROJECT_ROOT so no real files are touched
        monkeypatch.setattr(upgrade, "_PROJECT_ROOT", tmp_path)
        result = upgrade.perform_upgrade("http://h/d/raw-中文.zip")
        assert result["ok"] is False
        assert "stage" in result and result["stage"] == "download"
        assert "UnicodeEncodeError" in result["error"]
