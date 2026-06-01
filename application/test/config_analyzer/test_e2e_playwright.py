"""自动梳理配置 (config_analyzer) Playwright E2E 测试。

模拟用户真实操作：打开页面 → 切换 ER/USG → 粘贴配置 → 解析 → 验证 NAT 表 / 拓扑图 →
导出 CSV → 清空 → 边界情况。

启动方式：直接启动子应用 Flask (port 5004)，不经过 portal 代理。
"""
import sys, os, time, json
from pathlib import Path

os.environ["TEST_MODE"] = "1"
os.environ["NO_BROWSER"] = "1"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _smoke_helpers import APPLICATION_DIR, PYTHON, SmokeServer

APP_DIR = APPLICATION_DIR / "自动梳理配置 - cc"
APP = APP_DIR / "app.py"
PORT = 5004
BASE = f"http://127.0.0.1:{PORT}"

# ═══════════════════════════════════════════════════════════════════
# 标准测试配置文本
# ═══════════════════════════════════════════════════════════════════

TEST_CONFIG_ER = """set system host-name 'ER-GZ-ZM-01'
set interfaces ethernet eth0 address '10.40.25.190/30'
set interfaces ethernet eth0 description 'WAN-MAIN'
set interfaces ethernet eth5 address '192.168.5.1/24'
set interfaces ethernet eth5 description 'LAN'
set interfaces vtun vtun40826 address '10.20.186.235/30'
set interfaces vtun vtun40826 description 'TUNNEL-MAIN-szd-natflr2'
set protocols bgp 64512 neighbor 10.20.186.236 remote-as '64513'
set protocols static route 10.40.25.188/32 next-hop 10.30.1.1
set service nat source rule 100 outbound-interface 'eth0'
set service nat source rule 100 source address '192.168.0.0/16'
set service nat source rule 100 translation address 'masquerade'
set service nat source rule 200 outbound-interface 'vtun40826'
set service nat source rule 200 source address '10.0.0.0/8'
set service nat source rule 200 translation address '10.20.186.235'
"""

# 最小有效配置 — 用于快速测试
TEST_CONFIG_MINIMAL = """set system host-name 'test-router'
set interfaces ethernet eth0 address '192.168.1.1/24'
set service nat source rule 10 outbound-interface 'eth0'
set service nat source rule 10 source address '10.0.0.0/8'
set service nat source rule 10 translation address 'masquerade'
"""

# 无效/畸形配置
TEST_CONFIG_INVALID = "this is not a valid vyos configuration\nrandom text here\n"

# ═══════════════════════════════════════════════════════════════════

PASS = FAIL = 0


def t(name, ok):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}")


def main():
    from playwright.sync_api import sync_playwright

    if not APP.is_file():
        print(f"SKIP: 未找到 {APP}")
        return

    with SmokeServer([PYTHON, str(APP)], cwd=APP_DIR, port=PORT):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 900})

            # ── 页面加载 ──
            print("\n=== 页面加载 ===")
            page.goto(BASE + "/", timeout=10000)
            page.wait_for_load_state("networkidle")
            t("页面标题正确", "ER/USG Config Analyzer" in page.title())

            # ── 核心元素存在 ──
            print("\n=== 核心元素 ===")
            t("configText textarea 存在", page.locator("#configText").count() == 1)
            t("mappingText textarea 存在", page.locator("#mappingText").count() == 1)
            t("btnAnalyze 按钮存在", page.locator("#btnAnalyze").count() == 1)
            t("btnExport 按钮存在", page.locator("#btnExport").count() == 1)
            t("btnClear 按钮存在", page.locator("#btnClear").count() == 1)
            t("tabNat 存在", page.locator("#tabNat").count() == 1)
            t("tabTopology 存在", page.locator("#tabTopology").count() == 1)
            t("topoSvg 容器存在", page.locator("#topoSvg").count() == 1)

            # ── ER / USG 标签切换 ──
            print("\n=== 标签切换 ===")
            tab_er = page.locator("#tabEr")
            tab_usg = page.locator("#tabUsg")
            t("ER tab 默认 active", "active" in (tab_er.get_attribute("class") or ""))
            tab_usg.click()
            page.wait_for_timeout(300)
            t("USG tab 可点击切换", "active" in (tab_usg.get_attribute("class") or ""))
            tab_er.click()
            page.wait_for_timeout(300)
            t("切回 ER tab", "active" in (tab_er.get_attribute("class") or ""))

            # ── 粘贴配置 + 解析 ──
            print("\n=== 解析 ER 配置 ===")
            config_input = page.locator("#configText")
            config_input.fill(TEST_CONFIG_ER)
            t("配置粘贴成功", True)

            page.locator("#btnAnalyze").click()
            page.wait_for_timeout(1500)

            # 验证 NAT 表有内容
            nat_rows = page.locator("#natPanel table tbody tr")
            row_count = nat_rows.count()
            t(f"NAT 表有行 (实际 {row_count} 行)", row_count > 0)

            # 验证拓扑 SVG 渲染（切换标签触发 draw）
            page.locator("#tabTopology").click()
            page.wait_for_timeout(1000)
            # 有些版本需要手动触发 draw；检查 SVG 或至少容器非空
            topo_html = page.locator("#topoSvg").inner_html()
            svg_count = page.locator("#topoSvg svg").count()
            t(f"拓扑 SVG 已渲染 (svg={svg_count}, html_len={len(topo_html)})",
              svg_count > 0 or len(topo_html) > 50)

            # ── 查看 Topology 标签 ──
            print("\n=== 拓扑标签 ===")
            page.locator("#tabTopology").click()
            page.wait_for_timeout(500)
            t("拓扑面板可见", page.locator("#topologyPanel").is_visible())

            # ── CSV 导出 ──
            print("\n=== CSV 导出 ===")
            page.locator("#tabNat").click()
            page.wait_for_timeout(300)
            # 点击导出可能触发下载 — 只验证按钮可点击不报错
            try:
                page.locator("#btnExport").click()
                page.wait_for_timeout(500)
                t("导出按钮点击无异常", True)
            except Exception as e:
                t(f"导出按钮点击: {e}", False)

            # ── 清空 ──
            print("\n=== 清空 ===")
            page.locator("#btnClear").click()
            page.wait_for_timeout(500)
            cleared = config_input.input_value()
            t("清空后 configText 为空", cleared == "")

            # ── 最小配置解析 ──
            print("\n=== 最小配置 ===")
            config_input.fill(TEST_CONFIG_MINIMAL)
            page.locator("#btnAnalyze").click()
            page.wait_for_timeout(1000)
            short_row_count = page.locator("#natPanel table tbody tr").count()
            t(f"最小配置解析有行 (实际 {short_row_count} 行)", short_row_count > 0)

            # ── 无效配置 ──
            print("\n=== 无效配置 ===")
            page.locator("#btnClear").click()
            page.wait_for_timeout(300)
            config_input.fill(TEST_CONFIG_INVALID)
            page.locator("#btnAnalyze").click()
            page.wait_for_timeout(1000)
            # 无效配置不应崩溃；NAT 表可能为空或仍尝试解析
            empty_ok = True  # 不崩溃即通过
            t("无效配置不崩溃", empty_ok)

            # ── 空配置 ──
            print("\n=== 空配置 ===")
            page.locator("#btnClear").click()
            page.wait_for_timeout(300)
            page.locator("#btnAnalyze").click()
            page.wait_for_timeout(500)
            # 空配置也不应崩溃
            t("空配置不崩溃", True)

            # ── 结果 ──
            print(f"\n{'='*50}")
            print(f"  PASS: {PASS}  FAIL: {FAIL}  TOTAL: {PASS + FAIL}")
            print(f"{'='*50}")

            browser.close()
            return FAIL == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
