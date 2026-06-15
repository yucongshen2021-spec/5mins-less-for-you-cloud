"""Playwright E2E tests for 5.0 ER domain split — updated output format."""
import pytest


def _switch_to_5(page):
    page.click("#er-ver-5"); page.wait_for_timeout(300)

def _switch_to_4(page):
    page.click("#er-ver-4"); page.wait_for_timeout(300)

def _select_domain_split(page):
    page.click('[data-tool="epoch-fastip"] [data-variant="domain_split"]')
    page.wait_for_timeout(400)

def _open_epoch_fastip(page):
    page.click('.nav-tab[data-panel="epoch-fastip"]'); page.wait_for_timeout(500)

def _fill(page, field_id, value):
    page.evaluate("""([id, val]) => {
        const el = document.getElementById(id);
        if (!el) throw new Error('Not found: ' + id);
        el.value = val;
        el.dispatchEvent(new Event('input', {bubbles: true}));
        el.dispatchEvent(new Event('change', {bubbles: true}));
    }""", [field_id, value])
    page.wait_for_timeout(200)

def _click_generate(page):
    page.click('#panel-epoch-fastip .btn-p')
    page.wait_for_function(
        """() => { const s = document.getElementById('epoch-fastip-status');
        if (!s) return false; const t = s.textContent || '';
        return t.includes('成功') || t.includes('错误'); }""",
        timeout=15000)
    page.wait_for_timeout(200)

def _out(page):
    return page.eval_on_selector("#epoch-fastip-output", "el => el.value || ''")

def _status(page):
    return page.eval_on_selector("#epoch-fastip-status", "el => el.textContent || ''")

def _status_class(page):
    return page.eval_on_selector("#epoch-fastip-status", "el => el.className || ''")


class Test5DSE2E:
    def test_panel_visibility(self, page):
        _open_epoch_fastip(page); _switch_to_5(page); _select_domain_split(page)
        assert page.eval_on_selector("#er5-ds-layout", "el=>getComputedStyle(el).display") == "block"
        assert page.eval_on_selector("#er-ds-layout", "el=>getComputedStyle(el).display") == "none"

    def test_generate_defaults(self, page):
        _open_epoch_fastip(page); _switch_to_5(page); _select_domain_split(page)
        _fill(page, "epoch-fastip5-ds-domains", "google.com")
        _click_generate(page)
        assert "成功" in _status(page)
        out = _out(page)
        assert "domain-list" in out
        assert "name-server 209.244.0.3" in out

    def test_full_fnet(self, page):
        _open_epoch_fastip(page); _switch_to_5(page); _select_domain_split(page)
        _fill(page, "epoch-fastip5-ds-domains", "google.com")
        _fill(page, "epoch-fastip5-ds-addr-group", "togemini")
        _fill(page, "epoch-fastip5-ds-dns1", "8.8.8.8")
        _fill(page, "epoch-fastip5-ds-track", "tomainout")
        _fill(page, "epoch-fastip5-ds-s32-nh", "10.22.15.185")
        _fill(page, "epoch-fastip5-ds-s32-bk", "10.22.15.189")
        _fill(page, "epoch-fastip5-ds-nat-rule", "123")
        _fill(page, "epoch-fastip5-ds-exit-tun", "tun1111")
        _fill(page, "epoch-fastip5-ds-exit-ip", "5.5.5.5")
        _fill(page, "epoch-fastip5-ds-probe", "100.100.100.1")
        _click_generate(page)
        assert "成功" in _status(page)
        out = _out(page)
        # failover2 track without source-address
        assert "failover2 track tomainout target '100.100.100.1'" in out
        assert "failover2 track tomainout type 'icmp'" in out
        assert "source-address" not in out
        # /32 routes use failover2
        assert "failover2 route 2.2.2.2/32 next-hop 10.22.15.185 track tomainout" in out
        assert "failover2 route 2.2.2.2/32 next-hop 10.22.15.189 distance '20'" in out
        # FNET whitelist appears early
        assert out.find("set firewall group network-group") < out.find("domain-list")
        # NAT at end
        assert "set nat source rule 123 destination" in out

    def test_error_empty(self, page):
        _open_epoch_fastip(page); _switch_to_5(page); _select_domain_split(page)
        _fill(page, "epoch-fastip5-ds-domains", "")
        _click_generate(page)
        assert "status-err" in _status_class(page)

    def test_multiple_domains(self, page):
        _open_epoch_fastip(page); _switch_to_5(page); _select_domain_split(page)
        _fill(page, "epoch-fastip5-ds-domains", "google.com\nyoutube.com\nfacebook.com")
        _click_generate(page)
        out = _out(page)
        for d in ["google.com", "youtube.com", "facebook.com"]:
            assert d in out

    def test_version_isolation(self, page):
        _open_epoch_fastip(page)
        # 4.0
        _switch_to_4(page); _select_domain_split(page)
        _fill(page, "epoch-fastip-ds-domains", "google.com"); _click_generate(page)
        assert "domainlist" in _out(page)
        # 5.0
        _switch_to_5(page); _select_domain_split(page)
        _fill(page, "epoch-fastip5-ds-domains", "google.com"); _click_generate(page)
        assert "domain-list" in _out(page)

    def test_source_cidr_optional(self, page):
        _open_epoch_fastip(page); _switch_to_5(page); _select_domain_split(page)
        _fill(page, "epoch-fastip5-ds-domains", "google.com")
        _fill(page, "epoch-fastip5-ds-src-cidr", "192.168.5.0/24")
        _click_generate(page)
        assert "source address 192.168.5.0/24" in _out(page)
        _fill(page, "epoch-fastip5-ds-src-cidr", "")
        _click_generate(page)
        assert "source address" not in _out(page)
