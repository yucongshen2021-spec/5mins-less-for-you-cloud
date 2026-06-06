"""Reverse proxy — route /app/<id>/... → http://localhost:<port>/..."""
import re
import urllib.request
import urllib.error
import urllib.parse
import gzip
from flask import request, Response

_HOP_HEADERS = {
    "connection", "keep-alive", "proxy-authenticate",
    "proxy-authorization", "te", "trailers", "transfer-encoding", "upgrade",
}
_HTML_MIMES = {"text/html", "application/xhtml+xml"}
_JS_MIMES = {"text/javascript", "application/javascript", "application/x-javascript"}

# Rewrite absolute paths in HTML attributes (src/href/action).
_ATTR_RE = re.compile(
    r'\b(src|href|action)="(/(?!/|app/)([^"]*))"',
    re.IGNORECASE,
)

# Rewrite absolute-path string literals in JavaScript code.
# Matches "/api/..." or '/api/...' but NOT "//cdn...", "/app/...", or "/" alone.
_JS_STR_RE = re.compile(
    r"""(["'])(/(?!/|app/)(?=[^"'\s;]*[a-zA-Z])([^"'\s;]{2,}))\1""",
)


def _rewrite_paths(text: str, app_id: str) -> str:
    """Rewrite absolute paths in HTML attributes and JS string literals."""
    # HTML attributes: src="/static/..." → src="/app/<id>/static/..."
    def _attr(m):
        return f'{m.group(1)}="/app/{app_id}/{m.group(3)}"'
    text = _ATTR_RE.sub(_attr, text)

    # JS string literals: "/api/..." → "/app/<id>/api/..."
    def _js_str(m):
        return f'{m.group(1)}/app/{app_id}/{m.group(3)}{m.group(1)}'
    text = _JS_STR_RE.sub(_js_str, text)

    return text


def _filter_headers(headers: dict) -> dict:
    return {
        k: v for k, v in headers.items()
        if k.lower() not in _HOP_HEADERS
        and k.lower() not in ("host", "content-length", "content-encoding")
    }


def _build_proxy_request(target_url: str) -> urllib.request.Request:
    headers = _filter_headers(dict(request.headers))
    headers.pop("Host", None)
    data = request.get_data() or None
    return urllib.request.Request(target_url, data=data, headers=headers, method=request.method)


def proxy_to(app_id: str, subpath: str, port_map: dict) -> Response:
    port = port_map.get(app_id)
    if port is None:
        return Response(f"Unknown app: {app_id}", status=404)

    target = f"http://127.0.0.1:{port}/{urllib.parse.quote(subpath, safe='/')}"
    if request.query_string:
        target += "?" + request.query_string.decode("utf-8")

    try:
        backend_req = _build_proxy_request(target)
        with urllib.request.urlopen(backend_req, timeout=3600) as resp:
            resp_headers = _filter_headers(dict(resp.headers))
            content_type = resp.headers.get("Content-Type", "").lower()
            is_sse = "text/event-stream" in content_type

            if is_sse:
                def generate():
                    while True:
                        chunk = resp.readline()
                        if not chunk:
                            break
                        yield chunk
                return Response(generate(), status=resp.status,
                                headers=resp_headers,
                                content_type="text/event-stream")

            body = resp.read()

            content_encoding = resp.headers.get("Content-Encoding", "")
            if "gzip" in content_encoding:
                try:
                    body = gzip.decompress(body)
                except Exception:
                    pass
                resp_headers.pop("Content-Encoding", None)

            is_html = any(m in content_type for m in _HTML_MIMES)
            is_js = any(m in content_type for m in _JS_MIMES)

            if is_html or is_js:
                body_str = body.decode("utf-8", errors="replace")

                # Rewrite absolute paths in both HTML and JS
                body_str = _rewrite_paths(body_str, app_id)

                if is_html:
                    # Inject <base> so relative URLs resolve correctly
                    base_tag = f'<base href="/app/{app_id}/">'
                    if "<head>" in body_str:
                        body_str = body_str.replace("<head>", f"<head>\n  {base_tag}", 1)

                body = body_str.encode("utf-8")
                resp_headers["Content-Length"] = str(len(body))

            return Response(body, status=resp.status, headers=resp_headers)

    except urllib.error.HTTPError as e:
        return Response(e.read() or b"", status=e.code)
    except Exception as e:
        return Response(f"Proxy error: {e}", status=502)
