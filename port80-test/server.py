#!/usr/bin/env python3
"""80 端口连通性测试页 — 仅静态页面 + /ip 回显，无任何业务逻辑。

独立容器运行，与正式环境（5000/8000 端口）完全隔离。
"""
import http.server
import socketserver

PORT = 80


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/ip":
            ip = (
                self.headers.get("X-Real-IP")
                or (self.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
                or self.client_address[0]
            )
            data = ip.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
            return
        if self.path == "/health":
            data = b"ok"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(data)
            return
        return super().do_GET()

    def log_message(self, fmt, *args):
        # 静音访问日志，避免刷屏
        pass


if __name__ == "__main__":
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("0.0.0.0", PORT), Handler) as httpd:
        print(f"Port80 test page serving on 0.0.0.0:{PORT}")
        httpd.serve_forever()
