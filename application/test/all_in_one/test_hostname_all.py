"""所有正式页面 Hostname 行为回归：
- 用户在 Hostname 输入框填了值 → 必须以用户填的为准
- 用户没填 → 沿用原有兜底（不为空、不等于占位符）
- USG FastIP UI 上不再显示 Hostname 输入框（无落脚点）
"""
from common import *
import common as cm
from pathlib import Path

ER5_HK_HEADER = """MAIN
lineid: 603642Ar3
PE: szd-natflr2
WANIP: 10.40.25.188/30
TUNNEL: vtun40826
Docking: 121.12.81.3
CE LOIP: 10.20.186.235
HKIP: 10.60.241.250
BGPSERVER IP: 10.10.99.168,10.10.99.169

BACKUP
PE: szc-natbk10
WANIP: 10.41.25.188/30
TUNNEL: vtun50826
Docking: 120.133.129.72
BGPSERVER IP: 10.10.99.198,10.10.99.199"""

ER5_US_HEADER = (
    "LineID:609169A1\nPE:gzd-upe5\nTunnel:Tunnel0/0/1165\nwanip:10.55.14.64/30\n"
    "PE 对接:192.168.247.17\n海外出口ip:\n10.60.44.28-218.32.88.83\n\n"
    "LineID:609169A5\nPE:twb-natpe2\nWANIP:10.21.32.124/30\nTUNNEL:tun1267\n"
    "PE Docking:192.168.239.12\nBGPSERVER IP:103.252.19.25,43.229.117.226\n"
    "海外出口ip:\n10.60.44.28-218.32.88.83"
)


def _gen(c, api, variant, header, network):
    return c.post(f"/api/generate/{api}", json={
        "variant": variant,
        "header_text": header,
        "network": network,
    }).get_json()


def _must_contain(output, needle, label):
    if needle not in output:
        raise AssertionError(f"{label}: 输出缺少 {needle!r}")


def _must_not_contain(output, needle, label):
    if needle in output:
        raise AssertionError(f"{label}: 输出不应包含 {needle!r}")


def _hostname_lines(output):
    return [ln for ln in output.splitlines() if "host-name" in ln or "endpoint-name" in ln]


def test():
    custom = "CUSTOM-CE-X1"
    with app.test_client() as c:
        cases = [
            # api,           variant, header,           label
            ("epoch_fastip",  "hk",  ER_HK,           "ER 4.0 HK"),
            ("epoch_fastip",  "us",  ER_US,           "ER 4.0 US"),
            ("epoch_fastip5", "hk",  ER5_HK_HEADER,   "ER 5.0 HK"),
            ("epoch_fastip5", "us",  ER5_US_HEADER,   "ER 5.0 US"),
            ("epoch_mpls",    "domestic", MPLS_CN,    "MPLS 国内"),
            ("epoch_mpls",    "overseas", MPLS_OV,    "MPLS 海外"),
            ("epoch_mpls",    "ipsec",    MPLS_CN,    "MPLS IPSec"),
        ]
        for api, variant, header, label in cases:
            # 1) 用户填了 → 输出必含用户值
            r = _gen(c, api, variant, header, {"hostname": custom})
            t(f"{label} 自定义 Hostname ok", lambda r=r, l=label: (
                ok(r) or (_ for _ in ()).throw(AssertionError(f"{l}: {r.get('error', '')}"))))
            o = r.get("output", "")
            t(f"{label} 采用自定义 Hostname",
              lambda o=o, c=custom, l=label: _must_contain(o, f"set system host-name '{c}'", l))

            # 2) 用户没填 → 输出仍含某个非空 hostname，且不是自定义值
            r2 = _gen(c, api, variant, header, {})
            t(f"{label} 默认 Hostname ok", lambda r=r2, l=label: (
                ok(r) or (_ for _ in ()).throw(AssertionError(f"{l}: {r.get('error', '')}"))))
            o2 = r2.get("output", "")
            t(f"{label} 未填时不应误用自定义",
              lambda o=o2, c=custom, l=label: _must_not_contain(o, f"set system host-name '{c}'", l))
            t(f"{label} 未填时仍有兜底 hostname",
              lambda o=o2, l=label: (any("set system host-name '" in ln and "''" not in ln
                                          for ln in _hostname_lines(o))
                                      or (_ for _ in ()).throw(AssertionError(f"{l}: 未找到有效 host-name"))))

    # UI: USG FastIP Hostname 输入框已移除
    from _bootstrap import WEB_DIR
    html_path = WEB_DIR / "templates" / "index.html"
    html = html_path.read_text(encoding="utf-8")
    t("UI 上 USG FastIP 不再含 Hostname 输入框",
      lambda h=html: ('id="usg-fastip-hostname"' not in h) or
                     (_ for _ in ()).throw(AssertionError("仍然存在 usg-fastip-hostname")))


if __name__ == "__main__":
    test()
    total = cm.PASS + cm.FAIL
    print(f"\nHostname 回归: {cm.PASS}/{total} 通过, {cm.FAIL} 失败")
    save_report("hostname_all")
