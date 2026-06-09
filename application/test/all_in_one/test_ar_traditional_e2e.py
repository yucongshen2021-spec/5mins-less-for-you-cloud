"""AR 传统组网 — Playwright E2E tests (real browser)"""
import pytest
import _bootstrap  # noqa: F401

SAMPLE_HEADER = """LineID:609498A1
PE:szd-upe3
Tunnel:Tunnel0/0/1978
wanip:10.55.19.236/30
PE 对接:10.200.200.37
CE 对接:10.50.86.18
PE AS号:65510
CE AS号:65201
自环网段：100.100.100.0/30

拨号PE:szd-upe3
对接IP:10.200.200.37
LoopIP:10.50.86.18
拨号ip:183.56.161.86
秘钥:both-win

LineID:609498A2
PE:szc-upe1
Tunnel:Tunnel0/0/1136
wanip:10.30.36.216/30
PE 对接:10.200.200.27
CE 对接:10.50.118.34
PE AS号:65107
CE AS号:65201
自环网段：备 100.100.101.0/30

拨号PE:szc-upe1
对接IP:10.200.200.27
LoopIP:10.50.118.34
拨号ip:120.133.134.72
秘钥:both-win"""


@pytest.mark.playwright
def test_ar_traditional_tab_visible(page):
    """Nav tab 'AR 传统组网' should be visible and clickable."""
    tab = page.locator(".nav-tab", has_text="AR 传统组网")
    assert tab.is_visible()
    tab.click()
    page.wait_for_timeout(500)
    panel = page.locator("#panel-ar-traditional")
    assert panel.is_visible()


@pytest.mark.playwright
def test_ar_traditional_variant_pill(page):
    """Variant pill '双线' should be visible and active."""
    page.locator(".nav-tab", has_text="AR 传统组网").click()
    page.wait_for_timeout(500)
    pill = page.locator('[data-tool="ar-traditional"] .variant-pill.active')
    assert pill.is_visible()
    assert pill.text_content() == "双线"


@pytest.mark.playwright
def test_ar_traditional_generate_button(page):
    """Click generate with sample data should produce output."""
    page.locator(".nav-tab", has_text="AR 传统组网").click()
    page.wait_for_timeout(500)

    header_ta = page.locator("#ar-traditional-header")
    header_ta.fill(SAMPLE_HEADER)

    page.locator("button", has_text="生成配置").click()
    page.wait_for_timeout(3000)

    output_ta = page.locator("#ar-traditional-output")
    output = output_ta.input_value()
    assert len(output) > 500, f"Output too short: {len(output)}"
    assert "bgp 65201" in output
    assert "ipsec policy S2S-IPSEC" in output


@pytest.mark.playwright
def test_ar_traditional_bypass_toggle(page):
    """Bypass checkbox should toggle and affect output."""
    page.locator(".nav-tab", has_text="AR 传统组网").click()
    page.wait_for_timeout(500)

    page.locator("#ar-traditional-header").fill(SAMPLE_HEADER)
    page.locator("#ar-traditional-bypass").check()
    page.locator("button", has_text="生成配置").click()
    page.wait_for_timeout(3000)

    output = page.locator("#ar-traditional-output").input_value()
    assert "bgp 65201" in output


@pytest.mark.playwright
def test_ar_traditional_return_route_toggle(page):
    """Return route checkbox should add tag 8888 routes."""
    page.locator(".nav-tab", has_text="AR 传统组网").click()
    page.wait_for_timeout(500)

    page.locator("#ar-traditional-header").fill(SAMPLE_HEADER)
    page.locator("#ar-traditional-gen-rr").check()
    page.locator("button", has_text="生成配置").click()
    page.wait_for_timeout(3000)

    output = page.locator("#ar-traditional-output").input_value()
    assert "tag 8888" in output


@pytest.mark.playwright
def test_ar_traditional_clear_button(page):
    """Clear button should clear header and output."""
    page.locator(".nav-tab", has_text="AR 传统组网").click()
    page.wait_for_timeout(500)

    page.locator("#ar-traditional-header").fill("test data")
    page.locator("button", has_text="清除数据头").click()
    page.wait_for_timeout(300)

    header_val = page.locator("#ar-traditional-header").input_value()
    assert header_val == ""


@pytest.mark.playwright
def test_ar_traditional_copy_button(page):
    """Copy button should be visible."""
    page.locator(".nav-tab", has_text="AR 传统组网").click()
    page.wait_for_timeout(500)

    copy_btn = page.locator("button", has_text="复制输出")
    assert copy_btn.is_visible()


@pytest.mark.playwright
def test_ar_traditional_no_dhcp_buttons(page):
    """There should be NO DHCP checkboxes for WAN/LAN."""
    page.locator(".nav-tab", has_text="AR 传统组网").click()
    page.wait_for_timeout(500)

    panel = page.locator("#panel-ar-traditional")
    checkboxes = panel.locator("input[type=checkbox]")
    count = checkboxes.count()
    assert count == 2, f"Expected 2 checkboxes (回程路由 + 旁挂), found {count}"

    # Verify the 2 checkboxes are gen-rr and bypass, NOT dhcp
    gen_rr = page.locator("#ar-traditional-gen-rr")
    bypass = page.locator("#ar-traditional-bypass")
    assert gen_rr.is_visible()
    assert bypass.is_visible()

    # No DHCP labels
    labels = panel.text_content()
    assert "DHCP" not in labels
    assert "dhcp" not in labels


@pytest.mark.playwright
def test_ar_traditional_template_editor_integration(page):
    """Template editor should list AR 传统组网 scenario."""
    page.locator(".nav-tab", has_text="我来定模板").click()
    page.wait_for_timeout(500)

    trigger = page.locator("#tpl-cascade-trigger")
    trigger.click()
    page.wait_for_timeout(500)

    dropdown = page.locator("#tpl-cascade-dropdown")
    assert dropdown.is_visible()
    assert "AR 传统组网" in dropdown.text_content()


@pytest.mark.playwright
def test_ar_traditional_no_crash(page):
    """Generation with sample data should not crash or produce errors."""
    page.locator(".nav-tab", has_text="AR 传统组网").click()
    page.wait_for_timeout(500)

    page.locator("#ar-traditional-header").fill(SAMPLE_HEADER)
    page.locator("button", has_text="生成配置").click()
    page.wait_for_timeout(3000)

    output = page.locator("#ar-traditional-output").input_value()
    assert not output.startswith("// Error")
    assert not output.startswith("// 错误")
