#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按次目录记录：仅在各工具「生成配置」成功写入输出区后落盘一组文件。

落盘：APP_ROOT/user_activity/YYYY-MM-DD_<host>[_NN]/record.json + record.txt
其中 host 提取：hostname > 首个 lineid > unknown-host。
写盘失败须静默，不得影响生成流程。
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# 单字段过大时截断并设置 truncated:true，避免单条日志无限膨胀；None 表示不限制。
_MAX_FIELD_CHARS = 2_000_000
_EVENT = "generate.config"


def _safe_file_tag(raw: str) -> str:
    # 仅保留常见文件名安全字符，避免跨平台写盘异常
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", raw)
    safe = safe.strip("._-")
    return safe or "unknown-host"


def _extract_host_or_lineid(input_text: str, output_text: str) -> str:
    """
    文件名中的 host 取值规则：
    1) 优先脚本里的 hostname
    2) 若无，再取第一个 lineid
    3) 仍无则 unknown-host
    """
    text = f"{output_text or ''}\n{input_text or ''}"
    patterns = [
        r"(?im)\bhostname\s*[:=]\s*([A-Za-z0-9._-]+)",
        r"(?im)\bHostname\s*[:：]\s*([A-Za-z0-9._-]+)",
        r"(?im)set\s+system\s+host-name\s+['\"]?([A-Za-z0-9._-]+)['\"]?",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m and m.group(1):
            return _safe_file_tag(m.group(1).strip())
    m = re.search(r"(?im)\blineid\s*[:=]\s*([A-Za-z0-9._-]+)", text)
    if m and m.group(1):
        return _safe_file_tag(m.group(1).strip())
    return "unknown-host"


def _next_record_dir(root: Path, base_tag: str) -> Path:
    """
    每次生成创建一个新目录。
    - 首次：YYYY-MM-DD_<host>
    - 之后：YYYY-MM-DD_<host>_02 / _03 ...
    """
    parent = root / "user_activity"
    parent.mkdir(parents=True, exist_ok=True)
    first = parent / base_tag
    if not first.exists():
        return first
    pat = re.compile(rf"^{re.escape(base_tag)}_(\d{{2}})$")
    max_idx = 1
    for p in parent.iterdir():
        if not p.is_dir():
            continue
        m = pat.match(p.name)
        if not m:
            continue
        try:
            max_idx = max(max_idx, int(m.group(1)))
        except ValueError:
            continue
    return parent / f"{base_tag}_{max_idx + 1:02d}"


def _app_root() -> Path:
    """与 all_in_one_v2._runtime_dirs 中 app_root 规则对齐（避免循环 import）。"""
    if getattr(sys, "frozen", False):
        deliver_root = Path(sys.executable).resolve().parent
        app_root = deliver_root / "data"
        if not app_root.exists():
            parent_data = deliver_root.parent / "data"
            if parent_data.exists():
                app_root = parent_data
        app_root.mkdir(parents=True, exist_ok=True)
        return app_root
    here = Path(__file__).resolve().parent
    app_root = here.parent / "data"
    app_root.mkdir(parents=True, exist_ok=True)
    return app_root


def _maybe_truncate(s: str) -> tuple[str, bool]:
    if _MAX_FIELD_CHARS is None or len(s) <= _MAX_FIELD_CHARS:
        return s, False
    return s[:_MAX_FIELD_CHARS], True


def append_record(record: dict[str, Any], *, host_tag: str) -> None:
    try:
        root = _app_root()
        day = datetime.now().astimezone().strftime("%Y-%m-%d")
        base_tag = f"{day}_{host_tag}"
        rec_dir = _next_record_dir(root, base_tag)
        rec_dir.mkdir(parents=True, exist_ok=True)

        rec_json = rec_dir / "record.json"
        rec_txt = rec_dir / "record.txt"
        rec_json.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

        txt = "\n".join(
            [
                "user_activity 生成记录",
                f"ts: {record.get('ts', '')}",
                f"event: {record.get('event', '')}",
                f"tool: {record.get('tool', '')}",
                f"variant: {record.get('variant', '')}",
                f"data_header_chars: {record.get('data_header_chars', 0)}",
                f"output_script_lines: {record.get('output_script_lines', 0)}",
                "",
                "=== data_header ===",
                str(record.get("data_header", "")),
                "",
                "=== output_script ===",
                str(record.get("output_script", "")),
            ]
        )
        rec_txt.write_text(txt, encoding="utf-8")
    except Exception:
        pass


def log_generate_config(
    *,
    tool: str,
    variant: str,
    input_text: str,
    output_text: str,
) -> None:
    """成功生成后调用；记录「数据头 + 输出脚本」，内部异常吞掉。"""
    try:
        full_header = input_text or ""
        full_script = output_text or ""
        header_txt, tr_i = _maybe_truncate(full_header)
        script_txt, tr_o = _maybe_truncate(full_script)
        rec: dict[str, Any] = {
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "event": _EVENT,
            "tool": tool,
            "variant": variant,
            # 主字段（用户语义）
            "data_header": header_txt,
            "output_script": script_txt,
            "data_header_chars": len(full_header),
            "output_script_lines": len(full_script.splitlines()),
            # 兼容字段（历史工具读取）
            "input_text": header_txt,
            "output_text": script_txt,
            "input_chars": len(full_header),
            "output_lines": len(full_script.splitlines()),
        }
        if tr_i or tr_o:
            rec["truncated"] = True
        host_tag = _extract_host_or_lineid(full_header, full_script)
        append_record(rec, host_tag=host_tag)
    except Exception:
        pass
