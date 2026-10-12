"""自动做测试报告 — CE 命令 ER/USG 差异单元测试。

覆盖:
- build_ce_commands: ER 与 USG 的 01-04 CE 命令应不同
  (ER 全 ping 64/1500；USG 02/04=tracert, 03=ping1500)
- assert_ce_cmd_allowed: 生成的所有命令必须通过白名单
- fill_docx: 报告模板描述根据 product_type 区分
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

from PIL import Image

_APP_PARENT = Path(__file__).resolve().parents[2]  # .../application
sys.path.insert(0, str(_APP_PARENT / "自动做测试报告 - cc" / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

APP_DIR = _APP_PARENT / "自动做测试报告 - cc"

from make_report import (  # noqa: E402
    Config,
    assert_ce_cmd_allowed,
    build_ce_commands,
    fill_docx,
)


def _cfg(product_type: str) -> Config:
    return Config(
        customer="测试", line_id="C1", bandwidth="100M", engineer="tester",
        test_date="2026-08-17", ce_host="10.0.0.1", ce_port=2707, ce_user="bothwin",
        main_ip="10.60.1.1", backup_ip="10.60.2.2",
        local_site="www.baidu.com", accel_site="www.google.com",
        product_type=product_type,
        ce_ping_interval_i="0.01", ce_ping_interval_m="1",
    )


def test_er_commands_all_ping():
    """ER: 01-04 全部为 ping，大小 64/1500。"""
    cmds = dict(build_ce_commands(_cfg("er")))
    assert cmds["01_ce_main_small"] == "sudo ping -c 500 -i 0.01 -s 64 10.60.1.1"
    assert cmds["02_ce_main_large"] == "sudo ping -c 500 -i 0.01 -s 1500 10.60.1.1"
    assert cmds["03_ce_backup_small"] == "sudo ping -c 500 -i 0.01 -s 64 10.60.2.2"
    assert cmds["04_ce_backup_large"] == "sudo ping -c 500 -i 0.01 -s 1500 10.60.2.2"


def test_usg_commands_differ_from_er():
    """USG: 02/04=tracert，03=ping1500，与 ER 不同。"""
    usg = dict(build_ce_commands(_cfg("usg")))
    er = dict(build_ce_commands(_cfg("er")))
    # 01 相同：主线 ping 64
    assert "ping -s 64" in usg["01_ce_main_small"]
    # 02 不同：USG=tracert，ER=ping1500
    assert "tracert" in usg["02_ce_main_large"]
    assert "ping" not in usg["02_ce_main_large"]
    assert "1500" in er["02_ce_main_large"]
    # 03 不同：USG=ping1500，ER=ping64
    assert "-s 1500" in usg["03_ce_backup_small"]
    assert "-s 64" in er["03_ce_backup_small"]
    # 04 不同：USG=tracert，ER=ping1500
    assert "tracert" in usg["04_ce_backup_large"]
    assert "ping" not in usg["04_ce_backup_large"]


def test_all_commands_pass_whitelist():
    """生成的 ER 与 USG 命令都必须通过白名单。"""
    for ptype in ("er", "usg"):
        cfg = _cfg(ptype)
        for _tag, cmd in build_ce_commands(cfg):
            # 不应抛 RuntimeError
            assert_ce_cmd_allowed(cfg, cmd)


def test_usg_tracert_rejected_for_er():
    """USG 的 tracert 命令不应通过 ER 白名单（跨产品误用防护）。"""
    er = _cfg("er")
    with pytest.raises(RuntimeError):
        assert_ce_cmd_allowed(er, "tracert -d 10.60.1.1")


def _dummy_shots() -> Path:
    d = Path(tempfile.mkdtemp())
    for name in ["01_ce_main_small", "02_ce_main_large", "03_ce_backup_small", "04_ce_backup_large",
                 "06_ping", "06_tracert", "07_ping", "07_tracert", "08_ping", "08_tracert"]:
        Image.new("RGB", (100, 30), "white").save(d / f"{name}.png")
    return d


def test_fill_docx_description_differs_by_product():
    """报告模板描述按 product_type 区分（ER/USG）。"""
    from docx import Document
    template = APP_DIR / "script" / "FASTIP-测试报告.docx"
    if not template.is_file():
        template = APP_DIR / "script" / "FASTIP-测试报告-结果.docx"
    if not template.is_file():
        pytest.skip("未找到报告模板")
    shots = _dummy_shots()

    for ptype, expect in [
        ("er", {5: "主线 ping（小包64）", 14: "主线 ping（大包1500）", 23: "备线 ping（小包64）", 32: "备线 ping（大包1500）"}),
        ("usg", {5: "主线 ping（小包64）", 14: "主线 tracert", 23: "备线 ping（1500）", 32: "备线 tracert"}),
    ]:
        out = Path(tempfile.mkdtemp()) / f"report_{ptype}.docx"
        fill_docx(template, out, _cfg(ptype), shots)
        doc = Document(str(out))
        t = doc.tables[0]
        for ri, needle in expect.items():
            assert needle in t.rows[ri].cells[0].text, \
                f"{ptype} R{ri} 应含 {needle!r}, 实际 {t.rows[ri].cells[0].text!r}"
