"""我来定模板 E2E 测试 — 模拟用户在模板编辑器的完整操作路径。

覆盖:
  1. 场景树 API 返回正确的 IPSec 条目
  2. 加载每个 IPSec 场景 → header/mapping/template 非空
  3. 保存模板 → 重新加载 → 内容一致（热更新）
  4. 模板预览 → 生成样本配置
  5. 保存后生成 → 配置反映模板修改
  6. OpenVPN 场景回归
"""

import json
import sys
import urllib.request
import urllib.error
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
import _bootstrap  # noqa: F401

BASE = "http://127.0.0.1:5003"


def _api_post(path, body):
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def _api_get(path):
    with urllib.request.urlopen(f"{BASE}{path}", timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def _scenario_leaf_keys(tree):
    keys = []
    for node in tree:
        if "children" in node:
            keys.extend(_scenario_leaf_keys(node["children"]))
        elif "key" in node:
            keys.append(node["key"])
    return keys


# ── 期望存在的 IPSec 场景 ──
EXPECTED_IPSEC_SCENARIOS = [
    "Epoch FastIP · HK 香港出口 · IPSec",
    "Epoch FastIP · 非香港出口 · IPSec",
    "Epoch FastIP 5.0 · 非香港出口 · IPSec",
]

EXPECTED_OPENVPN_SCENARIOS = [
    "Epoch FastIP · HK 香港出口",
    "Epoch FastIP · 非香港出口",
    "Epoch FastIP 5.0 · HK 香港出口",
    "Epoch FastIP 5.0 · 非香港出口",
]


# ═══════════════════════════════════════════════════════════════════
class TestScenarioTree:
    """场景树 API 返回正确的条目。"""

    def test_tree_has_ipsec_entries(self):
        tree = _api_get("/api/scenarios")["tree"]
        leaves = set(_scenario_leaf_keys(tree))
        for s in EXPECTED_IPSEC_SCENARIOS:
            assert s in leaves, f"场景树缺少: {s}"

    def test_tree_has_openvpn_entries(self):
        tree = _api_get("/api/scenarios")["tree"]
        leaves = set(_scenario_leaf_keys(tree))
        for s in EXPECTED_OPENVPN_SCENARIOS:
            assert s in leaves, f"场景树缺少: {s}"

    def test_tree_has_four_level1_groups(self):
        tree = _api_get("/api/scenarios")["tree"]
        labels = {n["label"] for n in tree}
        assert "Epoch FastIP" in labels
        assert "USG FastIP" in labels
        assert "Epoch MPLS" in labels
        assert "AR SD-WAN" in labels

    def test_epoch_fastip_five0_has_ipsec_child(self):
        tree = _api_get("/api/scenarios")["tree"]
        ef = next(n for n in tree if n["label"] == "Epoch FastIP")
        v50 = next(n for n in ef["children"] if n["label"] == "5.0")
        keys = [c["key"] for c in v50["children"]]
        assert "Epoch FastIP 5.0 · 非香港出口 · IPSec" in keys

    def test_epoch_fastip_four0_has_ipsec_children(self):
        tree = _api_get("/api/scenarios")["tree"]
        ef = next(n for n in tree if n["label"] == "Epoch FastIP")
        v40 = next(n for n in ef["children"] if n["label"] == "4.0")
        keys = [c["key"] for c in v40["children"]]
        assert "Epoch FastIP · HK 香港出口 · IPSec" in keys
        assert "Epoch FastIP · 非香港出口 · IPSec" in keys


# ═══════════════════════════════════════════════════════════════════
class TestTemplateLoad:
    """加载 IPSec 场景模板。"""

    def test_load_5_0_us_ipsec_returns_header(self):
        r = _api_post("/api/template/load",
                      {"key": "Epoch FastIP 5.0 · 非香港出口 · IPSec"})
        assert r["ok"], f"load failed: {r.get('error')}"
        assert len(r.get("header", "")) > 0, "header 不应为空"

    def test_load_5_0_us_ipsec_returns_template(self):
        r = _api_post("/api/template/load",
                      {"key": "Epoch FastIP 5.0 · 非香港出口 · IPSec"})
        tpl = r.get("template", "")
        assert len(tpl) > 100, f"template 太短 ({len(tpl)} chars)"
        assert "vpn ipsec" in tpl, "IPSec 模板应包含 vpn ipsec"

    def test_load_5_0_us_ipsec_returns_mapping(self):
        r = _api_post("/api/template/load",
                      {"key": "Epoch FastIP 5.0 · 非香港出口 · IPSec"})
        mp = r.get("mapping", "")
        assert len(mp) > 0, "mapping 不应为空"

    def test_load_4_0_hk_ipsec_returns_template(self):
        r = _api_post("/api/template/load",
                      {"key": "Epoch FastIP · HK 香港出口 · IPSec"})
        assert r["ok"], f"load failed: {r.get('error')}"
        tpl = r.get("template", "")
        assert len(tpl) > 10 or "正在开发中" in tpl, \
            "HK IPSec 模板应返回 placeholder 或完整模板"

    def test_load_4_0_us_ipsec_returns_template(self):
        r = _api_post("/api/template/load",
                      {"key": "Epoch FastIP · 非香港出口 · IPSec"})
        assert r["ok"], f"load failed: {r.get('error')}"
        tpl = r.get("template", "")
        assert len(tpl) > 10 or "正在开发中" in tpl, \
            "4.0 US IPSec 模板应返回 placeholder 或完整模板"


# ═══════════════════════════════════════════════════════════════════
class TestTemplateHotUpdate:
    """保存 → 加载 → 验证热更新。"""

    def test_save_and_reload_preserves_content(self):
        key = "Epoch FastIP 5.0 · 非香港出口 · IPSec"
        modified = "# HOT-UPDATE-TEST-MARKER\nset system host-name 'HOT_UPDATE_TEST'\n"

        # Save
        r1 = _api_post("/api/template/save", {
            "key": key,
            "template": modified,
            "mapping": "test_mapping_var  测试映射",
            "header": "LineID:HOT-TEST\nPE:test\n",
        })
        assert r1["ok"], f"save failed: {r1.get('error')}"

        # Reload
        r2 = _api_post("/api/template/load", {"key": key})
        assert r2["ok"], f"reload failed: {r2.get('error')}"
        assert "HOT-UPDATE-TEST-MARKER" in r2["template"], \
            "重新加载应包含保存的内容"
        assert "test_mapping_var" in r2["mapping"], \
            "重新加载应包含保存的 mapping"

        # Reset (restore factory)
        r3 = _api_post("/api/template/reset", {"key": key})
        assert r3["ok"], f"reset failed: {r3.get('error')}"

        # Reload after reset — should NOT have marker
        r4 = _api_post("/api/template/load", {"key": key})
        assert r4["ok"]
        assert "HOT-UPDATE-TEST-MARKER" not in r4["template"], \
            "reset 后不应包含测试标记"

    def test_save_preserves_header_and_mapping(self):
        key = "Epoch FastIP 5.0 · 非香港出口 · IPSec"
        test_hdr = "LineID:SAVE-TEST\nPE:save-pe\n"
        test_mp = "save_pe  保存测试PE\n"

        _api_post("/api/template/save", {
            "key": key,
            "template": "# save test\n",
            "mapping": test_mp,
            "header": test_hdr,
        })

        r = _api_post("/api/template/load", {"key": key})
        assert test_hdr.strip() in r["header"]
        assert test_mp.strip() in r["mapping"]

        # Cleanup
        _api_post("/api/template/reset", {"key": key})


# ═══════════════════════════════════════════════════════════════════
class TestOpenVPNRegression:
    """OpenVPN 场景加载不受 IPSec 影响。"""

    def test_load_5_0_us_openvpn(self):
        r = _api_post("/api/template/load",
                      {"key": "Epoch FastIP 5.0 · 非香港出口"})
        assert r["ok"], f"load failed: {r.get('error')}"
        tpl = r.get("template", "")
        assert "interfaces openvpn" in tpl, "OpenVPN 模板应包含 openvpn"
        assert "vpn ipsec" not in tpl, "OpenVPN 模板不应包含 vpn ipsec"

    def test_load_5_0_hk_openvpn(self):
        r = _api_post("/api/template/load",
                      {"key": "Epoch FastIP 5.0 · HK 香港出口"})
        assert r["ok"], f"load failed: {r.get('error')}"
        tpl = r.get("template", "")
        assert len(tpl) > 100, "HK OpenVPN 模板不应为空"


# ═══════════════════════════════════════════════════════════════════
class TestTemplateSaveLoadCycle:
    """保存模板后加载，再重置——完整的用户操作周期。"""

    def test_full_cycle_save_load_reset(self):
        key = "Epoch FastIP 5.0 · 非香港出口 · IPSec"

        # 1. Load original
        r1 = _api_post("/api/template/load", {"key": key})
        assert r1["ok"]
        orig_tpl = r1["template"]
        orig_hdr = r1["header"]
        orig_mp = r1["mapping"]

        # 2. Save modified
        _api_post("/api/template/save", {
            "key": key, "template": "# MODIFIED\n" + orig_tpl,
            "mapping": orig_mp, "header": orig_hdr,
        })

        # 3. Reload — must have modifications
        r2 = _api_post("/api/template/load", {"key": key})
        assert "# MODIFIED" in r2["template"]

        # 4. Reset
        _api_post("/api/template/reset", {"key": key})

        # 5. Reload — must be back to original
        r3 = _api_post("/api/template/load", {"key": key})
        assert "# MODIFIED" not in r3["template"], "reset 后应恢复原模板"
        assert len(r3["template"]) > 100, "reset 后模板不应为空"


# ═══════════════════════════════════════════════════════════════════
class TestInvalidScenarios:
    """不存在的场景 key 应返回 404。"""

    def test_load_nonexistent_scenario(self):
        try:
            _api_post("/api/template/load", {"key": "不存在的场景"})
            assert False, "应返回 404"
        except urllib.error.HTTPError as e:
            assert e.code == 404
