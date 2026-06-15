"""Playwright E2E tests for 5.0 ER domain split — full browser flow.

Tests the complete chain: UI interaction → form param collection → API call → output rendering.
Uses conftest.py fixtures (flask_server + page).
"""
import pytest


# ── Helpers ──────────────────────────────────────────────────────────────

def _switch_to_5(page):
    """Switch ER version to 5.0."""
    page.click("#er-ver-5")
    page.wait_for_timeout(300)


def _switch_to_4(page):
    """Switch ER version to 4.0."""
    page.click("#er-ver-4")
    page.wait_for_timeout(300)


def _select_domain_split(page):
    """Select the 域名分流 variant pill."""
    page.click('[data-tool="epoch-fastip"] [data-variant="domain_split"]')
    page.wait_for_timeout(400)


def _open_epoch_fastip(page):
    """Navigate to the Epoch FastIP tab."""
    page.click('.nav-tab[data-panel="epoch-fastip"]')
    page.wait_for_timeout(500)


def _fill_field(page, field_id, value):
    """Fill a form field by setting value directly via JS, then dispatch input event."""
    page.evaluate(
        """([id, val]) => {
            const el = document.getElementById(id);
            if (!el) throw new Error('Element not found: ' + id);
            el.value = val;
            el.dispatchEvent(new Event('input', {bubbles: true}));
            el.dispatchEvent(new Event('change', {bubbles: true}));
            return el.value;
        }""",
        [field_id, value],
    )
    page.wait_for_timeout(200)


def _click_generate(page):
    """Click the 生成配置 button and wait for completion."""
    page.click('#panel-epoch-fastip .btn-p')
    # Wait for status to show success or error
    page.wait_for_function(
        """() => {
            const s = document.getElementById('epoch-fastip-status');
            if (!s) return false;
            const t = s.textContent || '';
            return t.includes('成功') || t.includes('错误') || t.includes('Error') || t.includes('网络错误');
        }""",
        timeout=15000,
    )
    page.wait_for_timeout(200)


def _get_output(page):
    """Read the output textarea value."""
    return page.eval_on_selector("#epoch-fastip-output", "el => el.value || ''")


def _get_status(page):
    """Read the status text."""
    return page.eval_on_selector("#epoch-fastip-status", "el => el.textContent || ''")


def _get_status_class(page):
    """Read the status CSS class."""
    return page.eval_on_selector("#epoch-fastip-status", "el => el.className || ''")


def _get_display(page, elem_id):
    """Get computed display style of an element."""
    return page.eval_on_selector(f"#{elem_id}", "el => getComputedStyle(el).display")


# ── Test Cases ───────────────────────────────────────────────────────────


class Test5DomainSplitPanelVisibility:
    """Test 1: UI panel visibility when switching to 5.0 + domain_split."""

    def test_panel_visibility_when_5_ds_selected(self, page):
        _open_epoch_fastip(page)
        _switch_to_5(page)
        _select_domain_split(page)

        # 5.0 domain split panel visible
        assert _get_display(page, "er5-ds-layout") == "block", \
            "er5-ds-layout should be visible"
        # 4.0 domain split panel hidden
        assert _get_display(page, "er-ds-layout") == "none", \
            "er-ds-layout should be hidden"
        # Normal layout hidden
        assert _get_display(page, "er-normal-layout") == "none", \
            "er-normal-layout should be hidden"
        # Version 5 button active
        active = page.eval_on_selector("#er-ver-5", "el => el.classList.contains('active')")
        assert active, "#er-ver-5 should have .active class"


class Test5DomainSplitGenerate:
    """Test 2: Generate with default values."""

    def test_generate_with_defaults(self, page):
        _open_epoch_fastip(page)
        _switch_to_5(page)
        _select_domain_split(page)

        # Fill minimal domain
        _fill_field(page, "epoch-fastip5-ds-domains", "google.com")
        _click_generate(page)

        status = _get_status(page)
        assert "成功" in status, f"Expected success, got status: {status}"

        out = _get_output(page)
        # 5.0-specific syntax
        assert "domain-list" in out, "Output must contain 'domain-list' (5.0 syntax)"
        assert " domainlist " not in out, "Output must NOT contain 'domainlist' (4.0 syntax)"
        assert "name-server 209.244.0.3" in out, \
            "Output must use 'name-server' without quotes (5.0 syntax)"
        assert "server '209.244.0.3'" not in out, \
            "Output must NOT use 'server' with quotes (4.0 syntax)"
        assert "set policy route LAN-MAP-to-US interface 'eth0'" in out, \
            "Output must have separate policy route interface line (5.0 syntax)"


class Test5DomainSplitFullFNET:
    """Test 3: Full FNET block + failover2 syntax."""

    def test_generate_full_fnet_failover2(self, page):
        _open_epoch_fastip(page)
        _switch_to_5(page)
        _select_domain_split(page)

        # Fill all FNET fields
        _fill_field(page, "epoch-fastip5-ds-domains", "google.com")
        _fill_field(page, "epoch-fastip5-ds-addr-group", "togemini")
        _fill_field(page, "epoch-fastip5-ds-dns1", "8.8.8.8")
        _fill_field(page, "epoch-fastip5-ds-track", "tooutbound1")
        _fill_field(page, "epoch-fastip5-ds-s32-nh", "10.22.15.185")
        _fill_field(page, "epoch-fastip5-ds-s32-bk", "10.22.15.189")
        _fill_field(page, "epoch-fastip5-ds-nat-rule", "123")
        _fill_field(page, "epoch-fastip5-ds-exit-tun", "tun1111")
        _fill_field(page, "epoch-fastip5-ds-exit-ip", "5.5.5.5")
        _fill_field(page, "epoch-fastip5-ds-probe", "100.100.100.1")
        _fill_field(page, "epoch-fastip5-ds-failover-src", "10.22.15.186")

        _click_generate(page)

        status = _get_status(page)
        assert "成功" in status, f"Expected success, got status: {status}"

        out = _get_output(page)
        # failover2 syntax
        assert "failover2 route 100.100.100.1/32" in out, \
            "Output must contain failover2 route"
        assert "failover2 track tooutbound1 source-address '10.22.15.186'" in out, \
            "Output must contain failover2 track source-address"
        assert "failover2 track tooutbound1 type 'icmp'" in out, \
            "Output must contain failover2 track type icmp"
        # NAT rules
        assert "set nat source rule 123 destination address 100.100.100.1/32" in out, \
            "Output must contain NAT rule 123"
        assert "set nat source rule 123 outbound-interface 'tun1111'" in out, \
            "Output must contain NAT outbound-interface"
        # FNET whitelist
        assert "set firewall group network-group GROUP-FNET-Whitelist network 100.100.100.0/24" in out


class Test5DomainSplitErrors:
    """Test 4: Empty domains error handling."""

    def test_error_empty_domains(self, page):
        _open_epoch_fastip(page)
        _switch_to_5(page)
        _select_domain_split(page)

        # Clear domains
        _fill_field(page, "epoch-fastip5-ds-domains", "")
        _click_generate(page)

        status = _get_status(page)
        assert "错误" in status or "Error" in status, \
            f"Expected error status, got: {status}"

        status_class = _get_status_class(page)
        assert "status-err" in status_class, \
            f"Status should have status-err class, got: {status_class}"


class Test5DomainSplitMultipleDomains:
    """Test 5: Multiple domains in heredoc."""

    def test_multiple_domains(self, page):
        _open_epoch_fastip(page)
        _switch_to_5(page)
        _select_domain_split(page)

        _fill_field(page, "epoch-fastip5-ds-domains", "google.com\nyoutube.com\nfacebook.com")
        _click_generate(page)

        status = _get_status(page)
        assert "成功" in status, f"Expected success, got: {status}"

        out = _get_output(page)
        assert "google.com" in out
        assert "youtube.com" in out
        assert "facebook.com" in out
        assert "sudo tee" in out, "Output must contain heredoc tee command"
        assert "EOF" in out, "Output must contain heredoc EOF marker"


class Test5DomainSplitVersionIsolation:
    """Test 6: Version switching produces correct syntax."""

    def test_4_vs_5_syntax_isolation(self, page):
        _open_epoch_fastip(page)

        # 4.0 first
        _switch_to_4(page)
        _select_domain_split(page)
        _fill_field(page, "epoch-fastip-ds-domains", "google.com")
        _click_generate(page)

        status_4 = _get_status(page)
        assert "成功" in status_4, f"4.0 should succeed, got: {status_4}"
        out_4 = _get_output(page)
        assert "domainlist" in out_4, "4.0 must use 'domainlist' (no hyphen)"

        # Switch to 5.0
        _switch_to_5(page)
        _select_domain_split(page)
        _fill_field(page, "epoch-fastip5-ds-domains", "google.com")
        _click_generate(page)

        status_5 = _get_status(page)
        assert "成功" in status_5, f"5.0 should succeed, got: {status_5}"
        out_5 = _get_output(page)
        assert "domain-list" in out_5, "5.0 must use 'domain-list' (with hyphen)"

        # Switch back to 4.0
        _switch_to_4(page)
        _select_domain_split(page)
        _fill_field(page, "epoch-fastip-ds-domains", "google.com")
        _click_generate(page)

        status_4b = _get_status(page)
        assert "成功" in status_4b, f"4.0 second time should succeed, got: {status_4b}"
        out_4b = _get_output(page)
        assert "domainlist" in out_4b, "4.0 after 5.0 must still use 'domainlist'"


class Test5DomainSplitCustomValues:
    """Test 7: Custom values reflected in output."""

    def test_custom_values_reflected(self, page):
        _open_epoch_fastip(page)
        _switch_to_5(page)
        _select_domain_split(page)

        _fill_field(page, "epoch-fastip5-ds-domains", "test.com")
        _fill_field(page, "epoch-fastip5-ds-addr-group", "mygroup")
        _fill_field(page, "epoch-fastip5-ds-dns1", "1.1.1.1")
        _fill_field(page, "epoch-fastip5-ds-eth", "eth2")
        _fill_field(page, "epoch-fastip5-ds-rule-num", "200")
        _fill_field(page, "epoch-fastip5-ds-table-num", "99")
        _click_generate(page)

        status = _get_status(page)
        assert "成功" in status, f"Expected success, got: {status}"

        out = _get_output(page)
        # Address group derivation: A + group name
        assert "domain-list Amygroup" in out, "domain-list should be A+groupname"
        assert "name-server 1.1.1.1" in out
        assert "set policy route LAN-MAP-mygroup interface 'eth2'" in out
        assert "set policy route LAN-MAP-mygroup rule 200" in out
        assert "set protocols static table 99 route" in out


class Test5DomainSplitSourceCIDR:
    """Test 8: Source CIDR optional behavior."""

    def test_source_cidr_optional(self, page):
        _open_epoch_fastip(page)
        _switch_to_5(page)
        _select_domain_split(page)

        # Scenario A: with source CIDR
        _fill_field(page, "epoch-fastip5-ds-domains", "google.com")
        _fill_field(page, "epoch-fastip5-ds-src-cidr", "192.168.5.0/24")
        _click_generate(page)

        status = _get_status(page)
        assert "成功" in status, f"With CIDR should succeed, got: {status}"
        out_a = _get_output(page)
        assert "source address 192.168.5.0/24" in out_a, \
            "Output should contain source address when CIDR is set"

        # Scenario B: without source CIDR
        _fill_field(page, "epoch-fastip5-ds-src-cidr", "")
        _click_generate(page)

        status_b = _get_status(page)
        assert "成功" in status_b, f"Without CIDR should succeed, got: {status_b}"
        out_b = _get_output(page)
        assert "source address" not in out_b, \
            "Output should NOT contain source address when CIDR is empty"
