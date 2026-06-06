#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FASTIP SD-WAN 线路测试报告自动生成。
仅执行白名单内的 ping / tracert；禁止任何配置类命令。
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import socket
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, fields
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Literal

_INTERACTIVE = True  # False when --no-manual-pause or --smoke; prevents blocking prompts

import paramiko
from docx import Document
from docx.shared import Inches
from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# 常量：与 FASTIP-测试报告.docx 表格结构严格对应（勿猜）
# ---------------------------------------------------------------------------

TEMPLATE_NAME = "FASTIP-测试报告.docx"

# 每个测试项截图区首行（0-based），与 _table_dump.txt 一致；插入到该行的第 0 列
SCREENSHOT_BLOCK_FIRST_ROW: dict[str, tuple[int, str]] = {
    "01_ce_main_small": (6, "ping -c 500 -s 64 主线PEWANIP"),
    "02_ce_main_large": (15, "ping -c 500 -s 1500 主线PEWANIP"),
    "03_ce_backup_small": (24, "ping -c 500 -s 64 备线PEWANIP"),
    "04_ce_backup_large": (33, "ping -c 500 -s 1500 备线PEWANIP"),
    "05_speedtest": (42, "测试站点:www.speedtest.net"),
    # 以下三行模板内站点名可能与客户输入不同，只校验固定前缀
    "06_local": (51, "ping -n 100 -l 1500"),
    "07_accel": (59, "ping -n 100 -l 1500"),
    "08_failover": (67, "ping -n 100 -l 1500"),
}

IPV4_CORE = r"\d{1,3}(?:\.\d{1,3}){3}"
# 本机：仅允许 ping -n 100 -l 1200 <host> 与 tracert -d <host>；host 为 IPv4 或域名标签
HOST_TOKEN = r"(?:\d{1,3}(?:\.\d{1,3}){3}|[A-Za-z0-9][A-Za-z0-9.-]*)"
LOCAL_PING_PATTERN = re.compile(rf"^ping -n 100 -l 1200 {HOST_TOKEN}$")
LOCAL_TRACERT_PATTERN = re.compile(rf"^tracert -w 1 -d {HOST_TOKEN}$")

FONT_PATH = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "consola.ttf"

@dataclass
class Config:
    customer: str
    line_id: str
    bandwidth: str
    engineer: str
    test_date: str
    ce_host: str
    ce_port: int
    ce_user: str
    main_ip: str
    backup_ip: str
    local_site: str
    accel_site: str
    # er：CE ping 使用 -i；usg：CE ping 使用 -m，且 CE 为 ping+tracert 组合
    product_type: str = "er"
    ce_ping_interval_i: str = "0.01"
    ce_ping_interval_m: str = "1"


def strip_ansi(s: str) -> str:
    return re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", s)


def validate_ipv4(ip: str) -> None:
    m = re.fullmatch(
        r"(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})",
        ip.strip(),
    )
    if not m:
        raise ValueError(f"主线/备线 IP 必须是合法 IPv4 点分十进制: {ip!r}")
    for g in m.groups():
        if int(g) > 255:
            raise ValueError(f"非法 IPv4 段: {ip!r}")


def validate_ce_interval_i(value: str) -> None:
    s = value.strip()
    if not re.fullmatch(r"\d+(?:\.\d+)?", s):
        raise ValueError(f"CE ping -i 必须是正数或小数（如 0.01）: {value!r}")


def validate_ce_interval_m(value: str) -> None:
    s = value.strip()
    if not re.fullmatch(r"\d+", s):
        raise ValueError(f"CE ping -m 必须是非负整数: {value!r}")


def validate_product_type(value: str) -> None:
    if value not in ("er", "usg"):
        raise ValueError(f"product_type 必须是 er 或 usg: {value!r}")


def assert_ce_cmd_allowed(cfg: Config, cmd: str) -> None:
    c = cmd.strip()
    validate_product_type(cfg.product_type)
    if cfg.product_type == "er":
        validate_ce_interval_i(cfg.ce_ping_interval_i)
        pat = re.compile(
            rf"^sudo ping -c 500 -i {re.escape(cfg.ce_ping_interval_i.strip())} "
            rf"-s (64|1500) ({IPV4_CORE})$"
        )
        if not pat.match(c):
            raise RuntimeError(f"拒绝发送非白名单 CE 命令: {cmd!r}")
        return
    validate_ce_interval_m(cfg.ce_ping_interval_m)
    ping_pat = re.compile(
        rf"^ping -c 500 -s (64|1500) -m {re.escape(cfg.ce_ping_interval_m.strip())} "
        rf"({IPV4_CORE})$"
    )
    if ping_pat.match(c):
        return
    raise RuntimeError(f"拒绝发送非白名单 CE 命令: {cmd!r}")


def assert_local_cmd_allowed(cmd: str) -> None:
    c = cmd.strip()
    if not (LOCAL_PING_PATTERN.match(c) or LOCAL_TRACERT_PATTERN.match(c)):
        raise RuntimeError(f"拒绝执行非白名单本机命令: {cmd!r}")


def prompt_nonempty(msg: str) -> str:
    v = input(msg).strip()
    if not v:
        print("错误：此项不能为空。", file=sys.stderr)
        sys.exit(1)
    return v


def prompt_optional(msg: str) -> str:
    return input(msg).strip()


def prompt_int_default(msg: str, default: int) -> int:
    raw = input(msg).strip()
    if not raw:
        return default
    if not re.fullmatch(r"\d+", raw):
        print("错误：端口必须是正整数。", file=sys.stderr)
        sys.exit(1)
    return int(raw)


def prompt_date_default(msg: str, default: str) -> str:
    raw = input(msg).strip()
    return raw if raw else default


def prompt_site_default(msg: str, default: str) -> str:
    raw = input(msg).strip()
    return raw if raw else default


def load_config_json(path: Path) -> Config:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    data.setdefault("product_type", "er")
    data.setdefault("ce_ping_interval_i", "0.01")
    data.setdefault("ce_ping_interval_m", "1")
    for k in ("ce_ping_interval_i", "ce_ping_interval_m", "product_type"):
        if k in data and data[k] is not None and not isinstance(data[k], str):
            data[k] = str(data[k])
    known = {f.name for f in fields(Config)}
    filtered = {k: v for k, v in data.items() if k in known}
    return Config(**filtered)


def save_config_json(cfg: Config, path: Path) -> None:
    path.write_text(
        json.dumps(asdict(cfg), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_state(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save_state(path: Path, state: dict) -> None:
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def prompt_inputs() -> Config:
    print("== 客户信息（可全部留空，报告中对应格不填）==")
    customer = prompt_optional("客户名称: ")
    line_id = prompt_optional("涉及的线路ID: ")
    bandwidth = prompt_optional("客户合同购买的服务带宽: ")
    engineer = prompt_optional("测试工程师: ")
    today = date.today().isoformat()
    test_date = prompt_date_default(f"测试日期 [默认 {today}]: ", today)

    print("\n== CE 设备 ==")
    ce_host = prompt_nonempty("CE SSH 主机/IP (必填): ")
    ce_port = prompt_int_default("CE SSH 端口 [默认 2707]: ", 2707)
    ce_user = prompt_nonempty("CE SSH 用户名 (必填): ")

    print("\n== 测试目标 IP ==")
    main_ip = prompt_nonempty("主线对端IP (必填): ")
    validate_ipv4(main_ip)
    backup_ip = prompt_nonempty("备线 PE WAN IP (必填): ")
    validate_ipv4(backup_ip)

    print("\n== 用户侧测试目标 ==")
    local_site = prompt_site_default("本地测试站点 [默认 www.baidu.com]: ", "www.baidu.com")
    accel_site = prompt_site_default("加速测试站点 [默认 www.google.com]: ", "www.google.com")

    print("\n== 产品类型与 CE 间隔参数 ==")
    product_type = prompt_optional("产品类型 er / usg [默认 er]: ").strip().lower() or "er"
    validate_product_type(product_type)
    ce_i = prompt_optional("ER: CE ping -i 秒 [默认 0.01]: ").strip() or "0.01"
    ce_m = prompt_optional("USG: CE ping -m [默认 1]: ").strip() or "1"
    if product_type == "er":
        validate_ce_interval_i(ce_i)
    else:
        validate_ce_interval_m(ce_m)

    return Config(
        customer=customer,
        line_id=line_id,
        bandwidth=bandwidth,
        engineer=engineer,
        test_date=test_date,
        ce_host=ce_host,
        ce_port=ce_port,
        ce_user=ce_user,
        main_ip=main_ip,
        backup_ip=backup_ip,
        local_site=local_site,
        accel_site=accel_site,
        product_type=product_type,
        ce_ping_interval_i=ce_i,
        ce_ping_interval_m=ce_m,
    )


def ask_on_failure(
    tag: str, cmd: str, out: str, exit_code: int | None, err_extra: str = ""
) -> Literal["retry", "save_continue", "abort"]:
    if not sys.stdin.isatty() or not _INTERACTIVE:
        raise RuntimeError(
            f"任务失败且当前为非交互环境，无法选择重试/继续。tag={tag}, exit={exit_code}"
        )
    print(f"\n任务失败: {tag}")
    print(f"命令: {cmd}")
    if err_extra:
        print(err_extra)
    if exit_code is not None:
        print(f"退出码: {exit_code}")
    tail = "\n".join(out.strip().splitlines()[-12:])
    if tail:
        print("--- 输出末尾 ---")
        print(tail)
    while True:
        c = input("[1] 重试  [2] 保存当前输出并继续  [3] 中止 > ").strip()
        if c == "1":
            return "retry"
        if c == "2":
            return "save_continue"
        if c == "3":
            return "abort"
        print("请输入 1 / 2 / 3")


def ssh_exec_ce(client: paramiko.SSHClient, cmd: str, sudo_password: str, cfg: Config) -> tuple[str, int]:
    assert_ce_cmd_allowed(cfg, cmd)
    stdin, stdout, stderr = client.exec_command(cmd)
    if "sudo -S" in cmd:
        stdin.write(sudo_password + "\n")
        stdin.flush()
    stdin.close()
    out_b = stdout.read()
    err_b = stderr.read()
    code = stdout.channel.recv_exit_status()
    out = (out_b or b"").decode("utf-8", errors="replace")
    err = (err_b or b"").decode("utf-8", errors="replace")
    out = strip_ansi(out)
    err = strip_ansi(err)
    if err.strip():
        out = out.rstrip() + "\n" + err.strip()
    return out, int(code)


def local_exec(cmd: str) -> tuple[str, int]:
    assert_local_cmd_allowed(cmd)
    wrapped_cmd = f'cmd /c "chcp 65001>nul & {cmd}"'
    proc = subprocess.Popen(
        wrapped_cmd,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    lines: list[str] = []
    assert proc.stdout is not None
    try:
        for line_b in iter(proc.stdout.readline, b""):
            line = line_b.decode("utf-8", errors="replace")
            lines.append(line)
            try:
                sys.stdout.write(line)
            except UnicodeEncodeError:
                enc = sys.stdout.encoding or "utf-8"
                sys.stdout.buffer.write(line.encode(enc, errors="replace"))
            sys.stdout.flush()
    except KeyboardInterrupt:
        proc.kill()
        proc.wait()
        raise
    proc.wait()
    return "".join(lines), int(proc.returncode or 0)


def render_terminal_png(
    out_path: Path,
    title_line: str,
    body: str,
    font_path: Path,
    tail_lines: int | None = None,
) -> None:
    if not font_path.is_file():
        print(f"错误：找不到字体文件 {font_path}", file=sys.stderr)
        sys.exit(1)

    bg = "#0c0c0c"
    fg = "#cccccc"
    title_bg = "#3c3c3c"
    width_px = 1200
    pad = 12
    line_h = 24
    font = ImageFont.truetype(str(font_path), 15)
    font_title = ImageFont.truetype(str(font_path), 15)

    body_lines = body.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if tail_lines is not None and tail_lines > 0:
        body_lines = body_lines[-tail_lines:]
    # 简单折行
    max_chars = 110
    wrapped: list[str] = []
    for ln in body_lines:
        while len(ln) > max_chars:
            wrapped.append(ln[:max_chars])
            ln = ln[max_chars:]
        wrapped.append(ln)

    title_h = line_h + pad * 2
    content_h = max(1, len(wrapped)) * line_h + pad * 2
    h = title_h + content_h
    img = Image.new("RGB", (width_px, h), bg)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, width_px, title_h], fill=title_bg)
    draw.text((pad, pad), title_line, fill=fg, font=font_title)
    y = title_h + pad
    for wl in wrapped:
        draw.text((pad, y), wl, fill=fg, font=font)
        y += line_h
    img.save(out_path, format="PNG")


def validate_screenshot_row(table, tag: str) -> None:
    row_idx, needle = SCREENSHOT_BLOCK_FIRST_ROW[tag]
    cell0 = table.rows[row_idx].cells[0].text.replace("\r", "").strip()
    if needle not in cell0:
        raise RuntimeError(
            f"模板校验失败：{tag} 期望第 {row_idx} 行首列包含 {needle!r}，实际为 {cell0[:120]!r}…"
        )


def insert_images_in_cell(cell, paths: list[Path], skip_missing: bool) -> None:
    first = True
    for p in paths:
        if not p.is_file():
            if skip_missing:
                continue
            raise FileNotFoundError(f"缺少截图文件: {p}")
        if not first:
            cell.add_paragraph()
        first = False
        cell.paragraphs[-1].add_run().add_picture(str(p), width=Inches(5.5))


def fill_docx(
    template_path: Path,
    out_path: Path,
    cfg: Config,
    shots: Path,
) -> None:
    doc = Document(str(template_path))
    if len(doc.tables) != 1:
        raise RuntimeError(f"模板必须只有 1 个表格，当前 {len(doc.tables)}")
    t = doc.tables[0]

    # 先校验截图锚点行（在对表格做任何写入之前）
    for tag in SCREENSHOT_BLOCK_FIRST_ROW:
        validate_screenshot_row(t, tag)

    # 表头
    t.rows[1].cells[1].text = cfg.customer
    t.rows[1].cells[3].text = cfg.line_id
    t.rows[2].cells[1].text = cfg.bandwidth

    for c in (0, 1, 2):
        t.rows[74].cells[c].text = (
            f"测试工程师：{cfg.engineer}" if cfg.engineer else "测试工程师："
        )
    t.rows[74].cells[3].text = f"测试日期：{cfg.test_date}"

    # 将模板中的占位 IP 替换为实际值（仅字面替换）
    for row in t.rows:
        for cell in row.cells:
            for p in cell.paragraphs:
                for r in p.runs:
                    if r.text:
                        r.text = r.text.replace("主线PEWANIP", cfg.main_ip).replace(
                            "备线PEWANIP", cfg.backup_ip
                        )

    # 截图
    blocks = [
        ("01_ce_main_small", [shots / "01_ce_main_small.png"], False),
        ("02_ce_main_large", [shots / "02_ce_main_large.png"], False),
        ("03_ce_backup_small", [shots / "03_ce_backup_small.png"], False),
        ("04_ce_backup_large", [shots / "04_ce_backup_large.png"], False),
        ("05_speedtest", [shots / "05_speedtest.png"], True),
        (
            "06_local",
            [shots / "06_ping.png", shots / "06_tracert.png"],
            False,
        ),
        (
            "07_accel",
            [shots / "07_ping.png", shots / "07_tracert.png"],
            False,
        ),
        (
            "08_failover",
            [shots / "08_ping.png", shots / "08_tracert.png"],
            True,
        ),
    ]

    for tag, paths, skip_missing in blocks:
        row_idx = SCREENSHOT_BLOCK_FIRST_ROW[tag][0]
        cell = t.rows[row_idx].cells[0]
        insert_images_in_cell(cell, paths, skip_missing=skip_missing)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path))


def run_task_loop(
    tag: str,
    cmd: str,
    runner: Callable[[], tuple[str, int]],
    run_dir: Path,
    state: dict,
    state_path: Path,
    title_line: str,
) -> None:
    st = state.get("tasks", {}).get(tag, {})
    if st.get("status") == "done":
        png = run_dir / "screenshots" / f"{tag}.png"
        if not png.is_file():
            raise FileNotFoundError(f"断点续跑失败：{tag} 标记完成但缺少 {png}")
        print(f"[skip] {tag} 已完成")
        return

    while True:
        print(f"\n>>> [{tag}] 执行: {cmd}")
        print("测试中，请稍候...")
        t0 = time.perf_counter()
        try:
            out, code = runner()
        except (paramiko.SSHException, RuntimeError) as e:
            if sys.stdin.isatty() and _INTERACTIVE:
                choice = ask_on_failure(tag, cmd, "", None, f"连接/命令异常: {e}")
                if choice == "retry":
                    continue
                if choice == "abort":
                    sys.exit(1)
                out, code = "", 1
            else:
                print(f"[WARN] {tag} 异常（非交互模式继续）：{e}", file=sys.stderr)
                out, code = f"异常: {e}\n", 1
        except KeyboardInterrupt:
            print("\n已 Ctrl+C 中断")
            if sys.stdin.isatty() and _INTERACTIVE:
                choice = ask_on_failure(tag, cmd, "(无完整输出)", None, "用户中断")
                if choice == "retry":
                    continue
                if choice == "abort":
                    sys.exit(1)
                out, code = "", 1
            else:
                raise

        elapsed = int(time.perf_counter() - t0)
        raw_path = run_dir / "raw" / f"{tag}.txt"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_text(out, encoding="utf-8", errors="replace")

        if code != 0:
            if sys.stdin.isatty() and _INTERACTIVE:
                choice = ask_on_failure(tag, cmd, out, code)
                if choice == "retry":
                    continue
                if choice == "abort":
                    sys.exit(1)
            else:
                print(f"[INFO] {tag} 完成（继续生成报告）", file=sys.stderr)

        png_path = run_dir / "screenshots" / f"{tag}.png"
        png_path.parent.mkdir(parents=True, exist_ok=True)
        ping_tail = 20 if re.search(r"\bping\b", cmd) else None
        render_terminal_png(png_path, title_line, out, FONT_PATH, tail_lines=ping_tail)
        state.setdefault("tasks", {})[tag] = {
            "status": "done",
            "exit": code,
            "duration_s": elapsed,
        }
        save_state(state_path, state)
        print(f"    完成 {elapsed}s -> {png_path.name}")
        break


def mock_runner_for_tag(tag: str, cfg: Config) -> Callable[[], tuple[str, int]]:
    def run() -> tuple[str, int]:
        if cfg.product_type == "usg":
            if tag in ("01_ce_main_small", "03_ce_backup_small"):
                ip = cfg.main_ip if tag == "01_ce_main_small" else cfg.backup_ip
                return (
                    f"PING {ip} (mock USG)\n500 packets transmitted, 500 received, 0% packet loss\n",
                    0,
                )
            if tag == "02_ce_main_large":
                return (
                    f"PING {cfg.main_ip} (mock USG)\n500 packets transmitted, 500 received, 0% packet loss\n",
                    0,
                )
            if tag == "04_ce_backup_large":
                return (
                    f"PING {cfg.backup_ip} (mock USG)\n500 packets transmitted, 500 received, 0% packet loss\n",
                    0,
                )
        if tag.startswith("01") or tag.startswith("02"):
            return f"PING {cfg.main_ip} (mock)\n500 packets transmitted, 500 received, 0% packet loss\n", 0
        if tag.startswith("03") or tag.startswith("04"):
            return f"PING {cfg.backup_ip} (mock)\n500 packets transmitted, 500 received, 0% packet loss\n", 0
        if "ping" in tag:
            return f"Mock ping output for {tag}\n", 0
        return f"Mock tracert output for {tag}\n1  10 ms  192.168.1.1\n", 0

    return run


def build_ce_commands(cfg: Config) -> list[tuple[str, str]]:
    if cfg.product_type == "er":
        i = cfg.ce_ping_interval_i.strip()
        return [
            ("01_ce_main_small", f"sudo ping -c 500 -i {i} -s 64 {cfg.main_ip}"),
            ("02_ce_main_large", f"sudo ping -c 500 -i {i} -s 1500 {cfg.main_ip}"),
            ("03_ce_backup_small", f"sudo ping -c 500 -i {i} -s 64 {cfg.backup_ip}"),
            ("04_ce_backup_large", f"sudo ping -c 500 -i {i} -s 1500 {cfg.backup_ip}"),
        ]
    m = cfg.ce_ping_interval_m.strip()
    return [
        ("01_ce_main_small", f"ping -c 500 -s 64 -m {m} {cfg.main_ip}"),
        ("02_ce_main_large", f"ping -c 500 -s 1500 -m {m} {cfg.main_ip}"),
        ("03_ce_backup_small", f"ping -c 500 -s 64 -m {m} {cfg.backup_ip}"),
        ("04_ce_backup_large", f"ping -c 500 -s 1500 -m {m} {cfg.backup_ip}"),
    ]


def validate_config_for_run(cfg: Config) -> None:
    validate_ipv4(cfg.main_ip)
    validate_ipv4(cfg.backup_ip)
    validate_product_type(cfg.product_type)
    if cfg.product_type == "er":
        validate_ce_interval_i(cfg.ce_ping_interval_i)
    else:
        validate_ce_interval_m(cfg.ce_ping_interval_m)


def make_log_run_dir(root: Path, test_date: str, line_id: str) -> Path:
    date_key = re.sub(r"[^0-9]", "", test_date) or datetime.now().strftime("%Y%m%d")
    cid_key = re.sub(r"[^A-Za-z0-9_-]", "_", (line_id or "").strip()) or "NO_CID"
    run_dir = root / "log" / f"{date_key}_{cid_key}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "screenshots").mkdir(exist_ok=True)
    (run_dir / "raw").mkdir(exist_ok=True)
    return run_dir


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--resume",
        type=Path,
        help="继续某次 log 目录（内含 config.json / state.json）",
    )
    parser.add_argument(
        "--mock-network",
        action="store_true",
        help="不连真实网络，用假输出生成 PNG 与 Word（冒烟测试）",
    )
    parser.add_argument(
        "--only-docx",
        type=Path,
        metavar="RUN_DIR",
        help="仅根据已有 RUN_DIR/screenshots 与 config.json 生成 Word（不跑命令）",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="无交互冒烟：假网络 + 假配置，写入 log/_smoke_<时间戳>/",
    )
    parser.add_argument(
        "--ce-password",
        help="CE SSH 密码（用于非交互执行；未提供则走 getpass）",
    )
    parser.add_argument(
        "--no-manual-pause",
        action="store_true",
        help="跳过手工截图等待，直接生成 Word（缺图则留空）",
    )
    args = parser.parse_args()

    global _INTERACTIVE
    if args.smoke or args.no_manual_pause:
        _INTERACTIVE = False

    if getattr(sys, "frozen", False):
        current_dir = Path(sys.executable).resolve().parent
    else:
        current_dir = Path(__file__).resolve().parent
    if (current_dir / "script").is_dir():
        root = current_dir
    elif (current_dir.parent / "script").is_dir():
        root = current_dir.parent
    else:
        root = current_dir
    template = root / "script" / TEMPLATE_NAME
    if not template.is_file():
        print(f"错误：找不到模板 {template}", file=sys.stderr)
        sys.exit(1)

    if args.only_docx:
        run_dir = args.only_docx.resolve()
        cfg = load_config_json(run_dir / "config.json")
        out = run_dir / f"FASTIP-测试报告_{cfg.customer or '未命名'}_{cfg.test_date}.docx"
        fill_docx(template, out, cfg, run_dir / "screenshots")
        print(f"已生成: {out}")
        return

    if args.smoke:
        args.mock_network = True

    if args.resume:
        run_dir = args.resume.resolve()
        if not run_dir.is_dir():
            print("错误：--resume 必须是目录", file=sys.stderr)
            sys.exit(1)
        cfg = load_config_json(run_dir / "config.json")
        print(f"继续任务目录: {run_dir}")
    elif args.mock_network and args.smoke:
        today = date.today().isoformat()
        cfg = Config(
            customer="",
            line_id="",
            bandwidth="",
            engineer="",
            test_date=today,
            ce_host="192.0.2.1",
            ce_port=2707,
            ce_user="smoke",
            main_ip="192.0.2.10",
            backup_ip="192.0.2.11",
            local_site="www.baidu.com",
            accel_site="www.google.com",
            product_type="er",
            ce_ping_interval_i="0.01",
            ce_ping_interval_m="1",
        )
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir = root / "log" / f"_smoke_{stamp}"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "screenshots").mkdir(exist_ok=True)
        (run_dir / "raw").mkdir(exist_ok=True)
        save_config_json(cfg, run_dir / "config.json")
        print(f"\n[smoke] 输出目录: {run_dir}")
    else:
        print(
            "预计耗时：CE 4×500 ping 约 30+ 分钟；本机 ping×2 + tracert×2 数分钟。\n"
            "本机 ping 使用 -l 1200（与模板正文 -l 1500 可能不一致，以实际命令为准）。\n"
        )
        cfg = prompt_inputs()
        run_dir = make_log_run_dir(root, cfg.test_date, cfg.line_id)
        save_config_json(cfg, run_dir / "config.json")
        print(f"\n本次输出目录: {run_dir}")

    state_path = run_dir / "state.json"
    state = load_state(state_path)

    try:
        validate_config_for_run(cfg)
    except ValueError as exc:
        print(f"错误：配置无效: {exc}", file=sys.stderr)
        sys.exit(1)

    ce_password = ""
    if not args.mock_network:
        ce_password = args.ce_password if args.ce_password is not None else getpass.getpass("CE SSH 密码 (必填): ")
        if not ce_password:
            print("错误：密码不能为空", file=sys.stderr)
            sys.exit(1)

    ce_cmds = build_ce_commands(cfg)

    client: paramiko.SSHClient | None = None

    def ensure_ssh() -> paramiko.SSHClient:
        nonlocal client
        if args.mock_network:
            raise RuntimeError("内部错误：mock 模式不应调用 SSH")
        if client is not None:
            tr = client.get_transport()
            if tr is not None and tr.is_active():
                return client
            try:
                client.close()
            except Exception:
                pass
            client = None
        c = paramiko.SSHClient()
        # 首次连 CE 常见未知主机指纹；仅影响 SSH 信道，不向设备下发任何配置命令
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            c.connect(
                cfg.ce_host,
                port=cfg.ce_port,
                username=cfg.ce_user,
                password=ce_password,
                allow_agent=False,
                look_for_keys=False,
                timeout=30,
            )
        except paramiko.AuthenticationException:
            raise RuntimeError("SSH 登录失败：用户名或密码错误。")
        except (paramiko.SSHException, socket.timeout, TimeoutError) as exc:
            raise RuntimeError(f"SSH 连接失败：无法连接到 CE SSH IP {cfg.ce_host}:{cfg.ce_port}。{exc}")
        except OSError as exc:
            raise RuntimeError(f"SSH 连接失败：无法连接到 CE SSH IP {cfg.ce_host}:{cfg.ce_port}。{exc}")
        print(f"SSH 登录成功：{cfg.ce_user}@{cfg.ce_host}:{cfg.ce_port}")
        client = c
        return c

    try:
        for tag, cmd in ce_cmds:
            if args.mock_network:
                runner = mock_runner_for_tag(tag, cfg)
                run_task_loop(
                    tag,
                    cmd,
                    runner,
                    run_dir,
                    state,
                    state_path,
                    f"[CE]$ {cmd}",
                )
            else:
                def _run(c=cmd, pwd=ce_password):
                    conn = ensure_ssh()
                    return ssh_exec_ce(conn, c, pwd, cfg)

                run_task_loop(
                    tag,
                    cmd,
                    _run,
                    run_dir,
                    state,
                    state_path,
                    f"[CE]$ {cmd}",
                )

        if client is not None:
            client.close()
            client = None

        local_cmds = [
            ("06_ping", f"ping -n 100 -l 1200 {cfg.local_site}"),
            ("06_tracert", f"tracert -w 1 -d {cfg.local_site}"),
            ("07_ping", f"ping -n 100 -l 1200 {cfg.accel_site}"),
            ("07_tracert", f"tracert -w 1 -d {cfg.accel_site}"),
        ]
        for tag, cmd in local_cmds:
            if args.mock_network:
                runner = mock_runner_for_tag(tag, cfg)
                run_task_loop(
                    tag,
                    cmd,
                    runner,
                    run_dir,
                    state,
                    state_path,
                    f"C:\\> {cmd}",
                )
            else:

                def _run2(c=cmd):
                    return local_exec(c)

                run_task_loop(
                    tag,
                    cmd,
                    _run2,
                    run_dir,
                    state,
                    state_path,
                    f"C:\\> {cmd}",
                )

    finally:
        if client is not None:
            client.close()

    shots = run_dir / "screenshots"
    if args.smoke or args.no_manual_pause:
        print("\n跳过人工补图等待，直接生成 Word")
    else:
        print(
            f"\n请将人工截图放入（可缺省 Test5/Test8，缺则 Word 中对应位置留空）：\n"
            f"  {shots / '05_speedtest.png'}\n"
            f"  {shots / '08_ping.png'}\n"
            f"  {shots / '08_tracert.png'}\n"
            f"完成后按回车生成 Word …"
        )
        input()

    out = run_dir / f"FASTIP-测试报告_{cfg.customer or '未命名'}_{cfg.test_date}.docx"
    fill_docx(template, out, cfg, shots)
    print(f"\n完成: {out}")


if __name__ == "__main__":
    main()
