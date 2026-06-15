#!/usr/bin/env python3
"""镜像更新服务器 — 为客户 portal 提供 /api/update/manifest 和 zip 下载。

用法：
    python tools/serve_mirror.py                  # 默认端口 8000
    python tools/serve_mirror.py --port 9000       # 自定义端口
    python tools/serve_mirror.py --dist ./dist     # 自定义 zip 目录

客户 portal 的 update_config.json 中 mirror_url 指向此服务器地址。
"""

import argparse
import hashlib
import json
import os
import sys
import urllib.parse
import zipfile
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = PROJECT_ROOT / "dist"
BUNDLE_NAME = "帮你节省5分钟"


def find_latest_zip(dist_dir: Path) -> Path | None:
    """扫描 dist/ 目录，返回最新的 zip 文件路径。"""
    if not dist_dir.is_dir():
        return None
    zips = sorted(
        dist_dir.glob(f"{BUNDLE_NAME}-*.zip"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return zips[0] if zips else None


def _read_zip_version(zip_path: Path) -> str | None:
    """从 zip 内 RELEASE_INFO.json 读取版本号（clean semver，不含 bundle 前缀）。"""
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            # RELEASE_INFO.json 在 zip 根目录下（inside the bundle folder）
            for name in zf.namelist():
                if name.endswith("/RELEASE_INFO.json") or name == "RELEASE_INFO.json":
                    data = json.loads(zf.read(name).decode("utf-8"))
                    v = data.get("version")
                    if isinstance(v, str) and v.strip():
                        return v.strip()
    except Exception:
        pass
    return None


def build_manifest(zip_path: Path, base_url: str) -> dict:
    """从 zip 文件构建 manifest 响应。"""
    stat = zip_path.stat()
    with open(zip_path, "rb") as f:
        sha256 = hashlib.sha256(f.read()).hexdigest()

    filename = zip_path.name
    # 优先从 zip 内 RELEASE_INFO.json 读版本（clean semver），fallback 文件名提取
    version = _read_zip_version(zip_path)
    if not version:
        version = filename.removeprefix(f"{BUNDLE_NAME}-").removesuffix(".zip")

    # download_url 必须 percent-encode 文件名（见 log/mistake.txt #47 / #54）。
    # 原始中文字面量会让 urllib 的请求行直接 UnicodeEncodeError；客户端再做一次
    # 幂等编码（upgrade._encode_url_idempotent）拿到同样的结果，两边契约一致。
    encoded_filename = urllib.parse.quote(filename, safe="")
    return {
        "name": BUNDLE_NAME,
        "version": version,
        "size": stat.st_size,
        "sha256": sha256,
        "download_url": f"{base_url}/api/update/download/{encoded_filename}",
        "release_url": f"{base_url}/api/update/manifest",
    }


class MirrorHandler(SimpleHTTPRequestHandler):
    """处理 /api/update/manifest 和 /api/update/download/ 请求。"""

    base_url: str = "http://127.0.0.1:8000"

    def log_message(self, format, *args):
        print(f"[mirror] {args[0]}")

    def do_GET(self):
        path = self.path.split("?")[0]

        if path == "/api/update/manifest":
            self._serve_manifest()
        elif path.startswith("/api/update/download/"):
            self._serve_download(path)
        else:
            super().do_GET()

    def _serve_manifest(self):
        zip_path = find_latest_zip(DIST_DIR)
        if not zip_path:
            self._json({"ok": False, "error": "未找到发布包"}, 404)
            return

        manifest = build_manifest(zip_path, self.base_url)
        self._json({"ok": True, **manifest})

    def _serve_download(self, path: str):
        filename = urllib.parse.unquote(os.path.basename(path))
        filepath = DIST_DIR / filename

        if not filepath.is_file():
            self._json({"ok": False, "error": "文件不存在"}, 404)
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        # RFC 5987: non-ASCII filenames must use filename*=UTF-8''...
        encoded = urllib.parse.quote(filename, safe='')
        self.send_header("Content-Disposition",
                         f"attachment; filename=\"{encoded}\"; "
                         f"filename*=UTF-8''{encoded}")
        self.send_header("Content-Length", str(filepath.stat().st_size))
        self.end_headers()

        with open(filepath, "rb") as f:
            self.wfile.write(f.read())

    def _json(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    global DIST_DIR
    parser = argparse.ArgumentParser(description="镜像更新服务器")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--dist", type=str, default=str(DIST_DIR))
    parser.add_argument("--host", type=str, default="0.0.0.0")
    args = parser.parse_args()

    DIST_DIR = Path(args.dist)

    if not DIST_DIR.is_dir():
        print(f"[mirror] dist 目录不存在: {DIST_DIR}")
        sys.exit(1)

    latest = find_latest_zip(DIST_DIR)
    if latest:
        print(f"[mirror] 最新发布: {latest.name}")
    else:
        print("[mirror] WARNING: dist/ 中没有发布包")

    # Auto-detect local IP for download URLs.
    # Priority: 192.168.72.219 (primary) → 192.168.5.10 (fallback) → auto-detect.
    import socket as _socket, subprocess as _sp
    PREFERRED_IPS = ["192.168.72.219", "192.168.5.10"]

    def _local_ips() -> set[str]:
        """Return all IPv4 addresses configured on local interfaces."""
        ips: set[str] = set()
        # Method 1: hostname resolution
        try:
            for info in _socket.getaddrinfo(_socket.gethostname(), None):
                addr = info[4][0]
                if addr and ":" not in addr:  # IPv4 only
                    ips.add(addr)
        except Exception:
            pass
        # Method 2: ipconfig (Windows — catches secondary NICs)
        try:
            import re
            out = _sp.run(["ipconfig"], capture_output=True, text=True,
                          encoding="gbk", errors="replace").stdout
            for m in re.finditer(r"IPv4[^:]*:\s*([\d.]+)", out):
                ips.add(m.group(1))
        except Exception:
            pass
        return ips

    local_ips = _local_ips()
    print(f"[mirror] 本地 IP: {sorted(local_ips)}")

    local_ip = None
    for ip in PREFERRED_IPS:
        if ip in local_ips:
            local_ip = ip
            break

    if local_ip is None:
        try:
            local_ip = _socket.gethostbyname(_socket.gethostname())
        except Exception:
            local_ip = "127.0.0.1"

    MirrorHandler.base_url = f"http://{local_ip}:{args.port}"
    print(f"[mirror] download_url 使用 IP: {local_ip}")

    server = HTTPServer((args.host, args.port), MirrorHandler)
    print(f"[mirror] 镜像服务启动: http://{args.host}:{args.port}")
    print(f"[mirror] manifest: {MirrorHandler.base_url}/api/update/manifest")
    print(f"[mirror] 按 Ctrl+C 停止")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[mirror] 已停止")
        server.shutdown()


if __name__ == "__main__":
    main()
