#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""USG 测病毒 — 操作指引页面 + 工具包下载统计。

纯展示应用：展示 USG 一键测病毒工具的使用说明、测试域名清单、
下载入口，供工程师参考后在 Windows 电脑上运行 exe。

权限：用户身份由 portal proxy 注入的 X-User-Id header 确定。
访客（X-User-Id 为空）看不到域名清单与下载链接，需登录后访问。

下载统计：/api/download 返回工具包 zip，并向共享统计库写一条
「下载·USG测病毒工具」记录（含用户名/IP），供 9000 看板统计下载人数。
"""

import os
import sys
import time
from pathlib import Path
from urllib.parse import quote

from flask import Flask, Response, render_template, request

# ── 共享统计库（与 portal/stats 同一个 SQLite） ─────────────────────────────
_APP_DIR = Path(__file__).resolve().parent.parent  # …/application
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))
from common import stats_db  # noqa: E402

app = Flask(__name__)

_PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 5005
_ZIP_PATH = Path(__file__).resolve().parent / "data" / "usg-virus-test.zip"
_ZIP_DOWNLOAD_NAME = "usg一键测病毒.zip"


def _get_request_user_id() -> str:
    """返回当前请求的 X-User-Id（由 portal proxy 注入），访客或无上下文时返回空串。"""
    try:
        return (request.headers.get("X-User-Id") or "").strip()
    except Exception:
        return ""


def _client_ip() -> str:
    """与 portal/proxy.py 一致的取真实 IP 逻辑。"""
    xff = (request.headers.get("X-Forwarded-For") or "").strip()
    if xff:
        return xff.split(",")[0].strip() or request.remote_addr
    xri = (request.headers.get("X-Real-IP") or "").strip()
    return xri or request.remote_addr or "unknown"


@app.route("/")
def index():
    uid = _get_request_user_id()
    is_logged_in = bool(uid)
    username = ""
    if is_logged_in:
        username = (request.headers.get("X-Username") or "").strip()
    return render_template("index.html",
                           is_logged_in=is_logged_in,
                           username=username)


@app.route("/api/download")
def download():
    """返回工具包 zip，并记一条下载统计。仅登录用户可下载。"""
    uid = _get_request_user_id()
    if not uid:
        return Response("请先登录后下载工具包", status=403,
                        mimetype="text/plain; charset=utf-8")
    if not _ZIP_PATH.exists():
        return Response("工具包文件缺失，请联系管理员", status=500,
                        mimetype="text/plain; charset=utf-8")

    username = (request.headers.get("X-Username") or "").strip()
    data = _ZIP_PATH.read_bytes()

    # ── 写统计（不依赖 proxy 的 generate 判定，直接落库）──
    try:
        stats_db.log_access(
            ts=time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            ip=_client_ip(),
            app_id="usg_virus_test",
            method="GET",
            path="/app/usg_virus_test/api/download",
            query="",
            status=200,
            duration_ms=0,
            req_size=0,
            resp_size=len(data),
            subpath="api/download",
            user_agent=request.headers.get("User-Agent", ""),
            referer=request.headers.get("Referer", ""),
            user_id=uid,
            username=username,
        )
    except Exception:
        pass  # 统计失败不影响下载

    # 中文文件名走 RFC 5987 filename*，兼容各浏览器
    fname_star = quote(_ZIP_DOWNLOAD_NAME)
    cd = ("attachment; filename=\"usg-virus-test.zip\"; "
          f"filename*=UTF-8''{fname_star}")
    return Response(
        data,
        mimetype="application/zip",
        headers={"Content-Disposition": cd,
                 "Cache-Control": "no-store"},
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=_PORT, debug=False, use_reloader=False)
