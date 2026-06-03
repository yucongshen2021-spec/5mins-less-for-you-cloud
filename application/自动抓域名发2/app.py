#!/usr/bin/env python3
"""
Domain Capture — DNS CNAME Tracer
Flask web UI + Playwright capture + DNS CNAME chain detection.

Packaging: pyinstaller --onefile --windowed --name DomainCapture
    --collect-all playwright --collect-all dns --collect-all flask
    --hidden-import greenlet --hidden-import pyee
    --hidden-import dns.resolver --hidden-import dns.rdtypes app.py
"""

import io
import ipaddress
import json
import os
import re
import sys
import threading
import time
import webbrowser
from urllib.parse import urlparse

# --windowed mode: stdout/stderr are None, libraries crash silently.
# Redirect to in-memory buffers so print/write calls don't raise.
if sys.stdout is None:
    sys.stdout = io.StringIO()
if sys.stderr is None:
    sys.stderr = io.StringIO()

import dns.exception
import dns.resolver
from flask import Flask, render_template_string, request, jsonify
import logging
from playwright.sync_api import sync_playwright

# ═══════════════════════════════════════════════════════════════════
# DESIGN.md tokens
# ═══════════════════════════════════════════════════════════════════

COLORS = {
    "canvas":          "#f7f7f4",
    "ink":             "#26251e",
    "body":            "#5a5852",
    "muted":           "#807d72",
    "surface_card":    "#ffffff",
    "hairline":        "#e6e5e0",
    "primary":         "#f54e00",
    "primary_active":  "#d04200",
    "on_primary":      "#ffffff",
    "success":         "#1f8a65",
    "error":           "#cf2d56",
}


# ═══════════════════════════════════════════════════════════════════
# Browser detection — scan common Chromium-based browsers
# ═══════════════════════════════════════════════════════════════════

# Each entry: (display_name, path_or_paths)
_BROWSER_CANDIDATES: list[tuple[str, list[str]]] = [
    ("Chrome", [
        r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
        r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe",
        r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe",
    ]),
    ("Chrome Beta", [
        r"%LOCALAPPDATA%\Google\Chrome Beta\Application\chrome.exe",
        r"%PROGRAMFILES%\Google\Chrome Beta\Application\chrome.exe",
    ]),
    ("Chrome Dev", [
        r"%LOCALAPPDATA%\Google\Chrome Dev\Application\chrome.exe",
        r"%PROGRAMFILES%\Google\Chrome Dev\Application\chrome.exe",
    ]),
    ("Chrome Canary", [
        r"%LOCALAPPDATA%\Google\Chrome SxS\Application\chrome.exe",
    ]),
    ("Edge", [
        r"%PROGRAMFILES(X86)%\Microsoft\Edge\Application\msedge.exe",
        r"%PROGRAMFILES%\Microsoft\Edge\Application\msedge.exe",
    ]),
    ("Edge Beta", [
        r"%PROGRAMFILES(X86)%\Microsoft\Edge Beta\Application\msedge.exe",
        r"%PROGRAMFILES%\Microsoft\Edge Beta\Application\msedge.exe",
    ]),
    ("Edge Dev", [
        r"%PROGRAMFILES(X86)%\Microsoft\Edge Dev\Application\msedge.exe",
        r"%PROGRAMFILES%\Microsoft\Edge Dev\Application\msedge.exe",
    ]),
    ("360极速浏览器", [
        r"%LOCALAPPDATA%\360Chrome\Chrome\Application\360chrome.exe",
        r"%PROGRAMFILES(X86)%\360Chrome\Chrome\Application\360chrome.exe",
        r"%PROGRAMFILES%\360Chrome\Chrome\Application\360chrome.exe",
    ]),
    ("360安全浏览器", [
        r"%APPDATA%\360se6\Application\360se.exe",
        r"%PROGRAMFILES(X86)%\360\360se6\Application\360se.exe",
        r"%PROGRAMFILES%\360\360se6\Application\360se.exe",
        r"%APPDATA%\360se\Application\360se.exe",
        r"%PROGRAMFILES(X86)%\360\360se\Application\360se.exe",
    ]),
    ("Brave", [
        r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe",
        r"%PROGRAMFILES%\BraveSoftware\Brave-Browser\Application\brave.exe",
        r"%PROGRAMFILES(X86)%\BraveSoftware\Brave-Browser\Application\brave.exe",
    ]),
    ("Opera", [
        r"%LOCALAPPDATA%\Programs\Opera\launcher.exe",
        r"%PROGRAMFILES%\Opera\launcher.exe",
        r"%PROGRAMFILES(X86)%\Opera\launcher.exe",
    ]),
    ("Opera GX", [
        r"%LOCALAPPDATA%\Programs\Opera GX\launcher.exe",
        r"%PROGRAMFILES%\Opera GX\launcher.exe",
    ]),
    ("QQ浏览器", [
        r"%PROGRAMFILES(X86)%\Tencent\QQBrowser\QQBrowser.exe",
        r"%PROGRAMFILES%\Tencent\QQBrowser\QQBrowser.exe",
        r"%LOCALAPPDATA%\Tencent\QQBrowser\QQBrowser.exe",
    ]),
    ("搜狗浏览器", [
        r"%PROGRAMFILES(X86)%\SogouExplorer\SogouExplorer.exe",
        r"%PROGRAMFILES%\SogouExplorer\SogouExplorer.exe",
    ]),
    ("Vivaldi", [
        r"%LOCALAPPDATA%\Vivaldi\Application\vivaldi.exe",
        r"%PROGRAMFILES%\Vivaldi\Application\vivaldi.exe",
    ]),
    ("Chromium", [
        r"%LOCALAPPDATA%\Chromium\Application\chrome.exe",
        r"%PROGRAMFILES%\Chromium\Application\chrome.exe",
    ]),
    ("SRWare Iron", [
        r"%PROGRAMFILES%\SRWare Iron\iron.exe",
        r"%PROGRAMFILES(X86)%\SRWare Iron\iron.exe",
    ]),
    ("Yandex", [
        r"%LOCALAPPDATA%\Yandex\YandexBrowser\Application\browser.exe",
        r"%PROGRAMFILES%\Yandex\YandexBrowser\Application\browser.exe",
    ]),
    ("Cent Browser", [
        r"%LOCALAPPDATA%\CentBrowser\Application\chrome.exe",
        r"%PROGRAMFILES%\CentBrowser\Application\chrome.exe",
    ]),
    ("Cốc Cốc", [
        r"%LOCALAPPDATA%\CocCoc\Browser\Application\browser.exe",
        r"%PROGRAMFILES%\CocCoc\Browser\Application\browser.exe",
    ]),
    ("UC浏览器", [
        r"%PROGRAMFILES(X86)%\UCBrowser\Application\UCBrowser.exe",
        r"%PROGRAMFILES%\UCBrowser\Application\UCBrowser.exe",
    ]),
]

_browser_cache: tuple[str, str] | None = None  # (name, path)


def _find_browser() -> tuple[str, str]:
    """Scan for installed Chromium-based browsers. Returns (name, path)."""
    global _browser_cache
    if _browser_cache is not None:
        return _browser_cache

    for name, paths in _BROWSER_CANDIDATES:
        for raw in paths:
            expanded = os.path.expandvars(raw)
            if os.path.isfile(expanded):
                _browser_cache = (name, expanded)
                return _browser_cache

    _browser_cache = ("", "")
    return _browser_cache


# ═══════════════════════════════════════════════════════════════════
# Core capture
# ═══════════════════════════════════════════════════════════════════

def _is_ip_address(hostname: str) -> bool:
    try:
        ipaddress.ip_address(hostname)
        return True
    except ValueError:
        return False


def _extract_hostname(url: str) -> str | None:
    if re.match(r"^(data|blob|about|javascript|mailto|file):", url, re.IGNORECASE):
        return None
    parsed = urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        return None
    hostname = hostname.strip(".")
    return hostname or None


def capture_domains(url: str, timeout: float = 30, extra_wait: float = 3,
                    include_ip: bool = False) -> list[str]:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    hostnames: set[str] = set()

    _browser_name, _browser_path = _find_browser()
    launch_kwargs = {"headless": True}
    if _browser_path:
        launch_kwargs["executable_path"] = _browser_path

    with sync_playwright() as p:
        browser = p.chromium.launch(**launch_kwargs)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"),
        )
        page = context.new_page()

        def on_request(request):
            hostname = _extract_hostname(request.url)
            if hostname is None:
                return
            if not include_ip and _is_ip_address(hostname):
                return
            hostnames.add(hostname)

        page.on("request", on_request)
        try:
            page.goto(url, wait_until="load", timeout=timeout * 1000)
        except Exception:
            pass  # timeout or navigation error — keep whatever domains were captured
        time.sleep(extra_wait)
        browser.close()

    return sorted(hostnames)


# ═══════════════════════════════════════════════════════════════════
# DNS CNAME resolution
# ═══════════════════════════════════════════════════════════════════

DNS_TIMEOUT = 5.0
CNAME_MAX_HOPS = 5


def resolve_cname_chain(hostname: str) -> list[str]:
    chain: list[str] = []
    seen = {hostname.lower()}
    current = hostname
    for _ in range(CNAME_MAX_HOPS):
        try:
            answers = dns.resolver.resolve(current, "CNAME", lifetime=DNS_TIMEOUT)
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN,
                dns.exception.Timeout, dns.resolver.NoNameservers):
            break
        for rdata in answers:
            target = str(rdata.target).rstrip(".")
            if target.lower() in seen:
                break
            seen.add(target.lower())
            chain.append(target)
            current = target
            break
    return chain


def analyze_domains(hostnames: list[str]) -> list[dict]:
    """Resolve DNS CNAME chain for each hostname."""
    results: list[dict] = []
    for hostname in hostnames:
        chain = resolve_cname_chain(hostname)
        results.append({
            "hostname": hostname,
            "cname_chain": chain,
        })
    return results


# ═══════════════════════════════════════════════════════════════════
# Flask app
# ═══════════════════════════════════════════════════════════════════

app = Flask(__name__)


log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

# Return JSON for all errors — never HTML
@app.errorhandler(Exception)
def handle_all(err):
    return jsonify({"error": str(err)}), 500


@app.errorhandler(404)
def handle_404(err):
    return jsonify({"error": "Not found"}), 404


INDEX_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Domain Capture — F12 域名抓取工具</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Sans:opsz,wght@9..40,400;9..40,500;9..40,600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root {
    --canvas: #f7f7f4;
    --ink: #26251e;
    --body: #5a5852;
    --muted: #807d72;
    --surface: #ffffff;
    --hairline: #e6e5e0;
    --hairline-strong: #cfcdc4;
    --primary: #f54e00;
    --primary-active: #d04200;
    --success: #1f8a65;
    --error: #cf2d56;
    --section: 80px;
  }
  *, *::before, *::after { box-sizing:border-box; margin:0; padding:0; }
  html { background:var(--canvas); }
  body {
    font-family:'DM Sans',system-ui,-apple-system,sans-serif;
    font-size:15px; line-height:1.5; color:var(--body);
    background:var(--canvas); min-height:100vh;
    display:flex; flex-direction:column; align-items:center;
  }

  /* ── Hero ────────────────────────────────────── */
  .hero {
    text-align:center; padding:var(--section) 24px 48px; max-width:600px;
  }
  .hero h1 {
    font-family:'DM Serif Display',Georgia,'Times New Roman',serif;
    font-size:clamp(24px,4vw,38px); font-weight:400; line-height:1.2;
    color:var(--ink); letter-spacing:-0.3px; margin-bottom:10px;
  }
  .hero h1 .hl { color:var(--ink); }
  .hero p { color:var(--muted); font-size:15px; max-width:420px; margin:0 auto; }
  .hero-sub { white-space:nowrap; }

  /* ── Card ────────────────────────────────────── */
  .card {
    background:var(--surface); border:1px solid var(--hairline);
    border-radius:12px; padding:28px 28px 24px;
    width:100%; max-width:720px; margin:0 24px 24px;
    opacity:0; transform:translateY(12px);
    animation:cardIn .45s ease forwards;
  }
  .card:nth-child(2) { animation-delay:.1s; }
  .card:nth-child(3) { animation-delay:.2s; }
  @keyframes cardIn {
    to { opacity:1; transform:translateY(0); }
  }

  /* ── Input card ──────────────────────────────── */
  .input-row { display:flex; gap:10px; align-items:stretch; }
  .input-row input[type=text] {
    flex:1; font-family:'DM Sans',sans-serif; font-size:15px;
    color:var(--ink); background:var(--canvas);
    border:1px solid var(--hairline-strong); border-radius:8px;
    padding:0 16px; height:46px; outline:none; min-width:0;
    transition:border-color .2s;
  }
  .input-row input[type=text]:focus { border-color:var(--primary); }
  .btn-capture {
    font-family:'DM Sans',sans-serif; font-size:14px; font-weight:600;
    color:#fff; background:var(--primary);
    border:none; border-radius:8px; padding:0 22px; height:46px;
    cursor:pointer; white-space:nowrap; letter-spacing:.3px;
    transition:background .15s,transform .1s;
  }
  .btn-capture:hover { background:var(--primary-active); }
  .btn-capture:active { transform:scale(.97); }
  .btn-capture:disabled { background:var(--muted); cursor:not-allowed; transform:none; }
  .btn-capture .spinner {
    display:none; width:18px; height:18px; border:2px solid rgba(255,255,255,.3);
    border-top-color:#fff; border-radius:50%; animation:spin .7s linear infinite;
    margin-right:6px; vertical-align:middle; position:relative; top:-1px;
  }
  .btn-capture.loading .spinner { display:inline-block; }
  .btn-capture.loading .label { display:none; }
  @keyframes spin { to { transform:rotate(360deg); } }

  .options-row {
    display:flex; gap:20px; align-items:center; margin-top:16px; flex-wrap:wrap;
  }
  .options-row label { font-size:13px; color:var(--muted); display:flex; align-items:center; gap:6px; }
  .options-row input[type=number] {
    width:52px; height:30px; text-align:center; font-size:13px; font-family:'DM Sans',sans-serif;
    color:var(--ink); background:var(--canvas); border:1px solid var(--hairline-strong);
    border-radius:6px; outline:none;
  }
  .options-row input[type=checkbox] { accent-color:var(--primary); width:15px; height:15px; }

  /* ── Results card ────────────────────────────── */
  .results-header {
    display:flex; justify-content:space-between; align-items:center;
    margin-bottom:16px; flex-wrap:wrap; gap:8px;
  }
  .results-header h2 {
    font-size:14px; font-weight:500; color:var(--body); letter-spacing:.4px;
    text-transform:uppercase;
  }
  .results-header h2 em {
    font-style:normal; color:var(--primary); font-weight:600;
  }
  .results-actions { display:flex; gap:8px; }
  .btn-sm {
    font-family:'DM Sans',sans-serif; font-size:12px; font-weight:500;
    color:var(--ink); background:var(--canvas);
    border:1px solid var(--hairline-strong); border-radius:6px;
    padding:5px 12px; cursor:pointer; transition:background .15s;
    letter-spacing:.2px;
  }
  .btn-sm:hover { background:var(--hairline); }

  /* ── Domain tree ─────────────────────────────── */
  .domain-list { list-style:none; }
  .domain-item { border-bottom:1px solid var(--hairline); }
  .domain-item:last-child { border-bottom:none; }

  .domain-row {
    display:flex; align-items:center; padding:11px 4px; cursor:pointer;
    transition:background .12s; gap:10px;
  }
  .domain-row:hover { background:var(--canvas); }
  .domain-row .toggle {
    width:20px; height:20px; display:flex; align-items:center; justify-content:center;
    flex-shrink:0; font-size:10px; color:var(--muted); transition:transform .2s;
  }
  .domain-row .toggle.open { transform:rotate(90deg); }
  .domain-row .toggle.none { visibility:hidden; }
  .domain-row .hostname {
    font-family:'JetBrains Mono','Consolas','Courier New',monospace;
    font-size:13px; color:var(--ink); flex:1; word-break:break-all;
  }
  /* CNAME children */
  .cname-children { max-height:0; overflow:hidden; }
  .cname-children.expanded { max-height:2000px; transition:max-height .4s ease; }
  .cname-child {
    display:flex; align-items:center; padding:7px 4px 7px 40px;
    font-family:'JetBrains Mono','Consolas','Courier New',monospace;
    font-size:12px; color:var(--muted); gap:12px;
  }
  .cname-child .hop-num {
    font-size:10px; color:var(--muted); min-width:34px; flex-shrink:0;
  }
  .cname-child .cname-target { flex:1; word-break:break-all; }

  /* ── Empty / Error states ───────────────────── */
  .empty-state { text-align:center; padding:48px 24px; color:var(--muted); }
  .empty-state .icon { font-size:40px; margin-bottom:12px; }
  .error-msg { color:var(--error); font-size:13px; padding:8px 0; }

  /* ── Footer ──────────────────────────────────── */
  .footer {
    text-align:center; padding:48px 24px var(--section);
    font-size:12px; color:var(--muted);
    max-width:720px; margin:0 auto;
  }
  .footer span { color:var(--primary); }

  /* ── Hero badge ──────────────────────────────── */
  .hero-badge {
    display:inline-block; font-size:11px; font-weight:600;
    letter-spacing:.88px; text-transform:uppercase;
    color:var(--primary); border:1px solid var(--hairline-strong);
    border-radius:9999px; padding:4px 14px; margin-bottom:20px;
  }
  .hero h1 .hl {
    background:linear-gradient(120deg,rgba(245,78,0,.12) 0%,rgba(245,78,0,.04) 100%);
    padding:0 6px; border-radius:4px; position:relative;
  }
  .hero h1 .hl::after {
    content:''; position:absolute; left:2px; right:2px; bottom:-2px;
    height:2px; background:var(--primary); border-radius:1px; opacity:.35;
  }
  .hero-sep {
    width:36px; height:2px; background:var(--hairline-strong);
    margin:18px auto; border-radius:1px;
  }

  /* ── Loading card ────────────────────────────── */
  .loading-card { text-align:center; padding:44px 24px; }
  .progress-track {
    width:100%; max-width:300px; height:4px;
    background:var(--hairline); border-radius:2px;
    margin:0 auto 20px; overflow:hidden;
  }
  .progress-bar {
    height:100%; border-radius:2px;
    background:var(--hairline);
    position:relative; overflow:hidden;
  }
  .progress-bar::after {
    content:'';
    position:absolute; top:0;
    width:40%; height:100%;
    background:linear-gradient(90deg,transparent,rgba(245,78,0,.55),transparent);
    animation:shimmer 1.6s ease-in-out infinite;
  }
  @keyframes shimmer {
    from { left:-40%; }
    to { left:100%; }
  }
  .loading-card .scan-ring {
    width:48px; height:48px; border-radius:50%;
    border:2px solid var(--hairline); margin:0 auto 16px;
    display:flex; align-items:center; justify-content:center;
    animation:ringPulse 2s ease-in-out infinite;
  }
  .scan-ring .scan-dot {
    width:10px; height:10px; border-radius:50%;
    background:var(--primary);
    animation:dotPulse 2s ease-in-out infinite;
  }
  @keyframes ringPulse {
    0%,100% { border-color:var(--hairline); transform:scale(1); }
    50% { border-color:var(--primary); transform:scale(1.05); }
  }
  @keyframes dotPulse {
    0%,100% { opacity:1; transform:scale(1); }
    50% { opacity:.3; transform:scale(.7); }
  }
  .loading-card .status-text {
    font-size:15px; color:var(--ink); margin-bottom:6px;
  }
  .loading-card .elapsed {
    font-family:'JetBrains Mono','Consolas',monospace;
    font-size:13px; color:var(--muted);
  }

  /* ── Toast ───────────────────────────────────── */
  .toast {
    position:fixed; bottom:32px; left:50%; transform:translateX(-50%);
    background:var(--ink); color:var(--canvas); font-size:13px;
    padding:10px 22px; border-radius:9999px;
    opacity:0; pointer-events:none; transition:opacity .25s; z-index:99;
  }
  .toast.show { opacity:1; }

  /* ── yydy link button ──────────────────────────── */
  .yydy-btn {
    display:inline-flex; align-items:center; gap:5px;
    font-size:11px; font-weight:600; letter-spacing:.6px;
    color:var(--body); background:var(--surface);
    border:1px solid var(--hairline); border-radius:9999px;
    padding:5px 14px; cursor:pointer; text-decoration:none;
    transition:border-color .18s,color .18s,background .18s;
    margin-top:6px;
  }
  .yydy-btn:hover {
    color:var(--primary); border-color:var(--primary);
    background:rgba(245,78,0,.04);
  }
  .yydy-btn .yydy-dot {
    width:5px; height:5px; border-radius:50%;
    background:var(--primary); flex-shrink:0;
  }

  /* ── Responsive ──────────────────────────────── */
  @media (max-width:640px) {
    .input-row { flex-direction:column; }
    .hero { padding-top:48px; }
    .card { padding:20px 16px; margin:0 12px 16px; }
  }
</style>
</head>
<body>

<div class="hero">
  <div class="hero-badge">F12 Domain Tool</div>
  <h1>Domain <span class="hl">Capture</span></h1>
  <div class="hero-sep"></div>
  <p class="hero-sub">输入 URL，自动捕获网页所有请求域名，追踪 DNS CNAME 解析链路</p>
  <a class="yydy-btn" href="https://domain.yydy.link:2023/" target="_blank" rel="noopener" title="打开 YYDY 域名平台"><span class="yydy-dot"></span>yydy</a>
</div>

<div class="card" id="inputCard">
  <div class="input-row">
    <input type="text" id="urlInput" placeholder="输入网页 URL，如 https://example.com" autofocus>
    <button class="btn-capture" id="btnCapture" onclick="doCapture()">
      <span class="spinner"></span><span class="label">抓取</span>
    </button>
  </div>
  <div class="options-row">
    <label>Timeout <input type="number" id="optTimeout" value="30" min="5" max="120"> s</label>
    <label>Wait <input type="number" id="optWait" value="3" min="0" max="30"> s</label>
    <label><input type="checkbox" id="optIP"> 包含 IP</label>
    <label><input type="checkbox" id="optDNS" checked> 解析 CNAME</label>
  </div>
</div>

<div class="card" id="resultsCard">
  <div class="results-header">
    <h2 id="resultsTitle">结果 — 尚未抓取</h2>
    <div class="results-actions">
      <button class="btn-sm" id="btnToggleAll" onclick="toggleExpandAll()">全部展开</button>
      <button class="btn-sm" onclick="copyDomains()">复制</button>
      <button class="btn-sm" onclick="exportDomains()">导出</button>
    </div>
  </div>
  <div id="resultsBody">
    <div class="empty-state">
      <div class="icon">⌘</div>
      <p>输入 URL 开始抓取</p>
    </div>
  </div>
</div>

<div class="footer">
  Domain Capture · 本机 <span>127.0.0.1:5001</span> · 抓取引擎: {{ browser_name }} · 局域网访问需防火墙放行端口 5001
</div>

<div class="toast" id="toast"></div>

<script>
const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);

let analysisData = [];

let _elapsedTimer = null;
function _startElapsedTimer() {
  _stopElapsedTimer();
  const start = Date.now();
  _elapsedTimer = setInterval(() => {
    const el = $('#elapsedTime');
    if (!el) return;
    const s = Math.floor((Date.now() - start) / 1000);
    const mm = String(Math.floor(s / 60)).padStart(2,'0');
    const ss = String(s % 60).padStart(2,'0');
    el.textContent = mm + ':' + ss;
  }, 200);
}
function _stopElapsedTimer() {
  if (_elapsedTimer) { clearInterval(_elapsedTimer); _elapsedTimer = null; }
}

/* ── Dots animation ── */
let _dotsTimer = null;
function _startDots() {
  _stopDots();
  const el = $('#statusDots');
  if (!el) return;
  let n = 0;
  _dotsTimer = setInterval(() => { n = (n + 1) % 4; el.textContent = '.'.repeat(n); }, 400);
}
function _stopDots() {
  if (_dotsTimer) { clearInterval(_dotsTimer); _dotsTimer = null; }
}

async function doCapture() {
  const url = $('#urlInput').value.trim();
  if (!url) return toast('请输入 URL');
  const btn = $('#btnCapture');
  btn.classList.add('loading'); btn.disabled = true;
  $('#resultsTitle').textContent = '结果 — 抓取中...';
  $('#resultsBody').innerHTML =
    '<div class="loading-card">' +
    '<div class="scan-ring"><div class="scan-dot"></div></div>' +
    '<div class="progress-track"><div class="progress-bar"></div></div>' +
    '<p class="status-text">正在抓取域名<span class="dots" id="statusDots"></span></p>' +
    '<p class="elapsed" id="elapsedTime">00:00</p>' +
    '</div>';
  _startElapsedTimer();
  _startDots();

  try {
    const res = await fetch('/api/capture', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({
        url,
        timeout: parseFloat($('#optTimeout').value)||30,
        wait: parseFloat($('#optWait').value)||3,
        include_ip: $('#optIP').checked,
        resolve_dns: $('#optDNS').checked,
      }),
    });
    if (!res.ok) {
      const text = await res.text();
      try { const err = JSON.parse(text); showError(err.error||text); }
      catch(_) { showError(`HTTP ${res.status}: ${text.slice(0,200)}`); }
      return;
    }
    const data = await res.json();
    if (data.error) { showError(data.error); return; }
    analysisData = data.results;
    renderResults(data);
  } catch(e) {
    const msg = e.message || '网络错误';
    if (msg === 'Failed to fetch' || msg.includes('fetch')) {
      showError('无法连接后端服务，请确认程序已启动（端口 5001 未被占用）');
    } else {
      showError(msg);
    }
  } finally {
    _stopElapsedTimer();
    _stopDots();
    btn.classList.remove('loading'); btn.disabled = false;
  }
}

function showError(msg) {
  $('#resultsTitle').textContent = '结果 — 出错';
  $('#resultsBody').innerHTML = `<div class="empty-state"><p class="error-msg">⚠ ${msg}</p></div>`;
}

function renderResults(data) {
  const {domains_count, results} = data;
  $('#resultsTitle').innerHTML = `结果 — ${domains_count} 个域名`;
  _allExpanded = false;
  const btnToggle = $('#btnToggleAll');
  if (btnToggle) btnToggle.textContent = '全部展开';

  if (!results.length) {
    $('#resultsBody').innerHTML = '<div class="empty-state"><p>未捕获到域名</p></div>';
    return;
  }

  let html = '<ul class="domain-list">';
  results.forEach((r, i) => {
    const hasChain = r.cname_chain.length > 0;

    html += '<li class="domain-item">';
    html += '<div class="domain-row" onclick="toggleItem(this)">';
    html += `<span class="toggle${hasChain ? '' : ' none'}">▶</span>`;
    html += `<span class="hostname">${r.hostname}</span>`;
    html += '</div>';

    if (hasChain) {
      html += `<div class="cname-children">`;
      r.cname_chain.forEach((cname, j) => {
        html += `<div class="cname-child">`;
        html += `<span class="hop-num">hop ${j+1}</span>`;
        html += `<span class="cname-target">${cname}</span>`;
        html += '</div>';
      });
      html += '</div>';
    }
    html += '</li>';
  });
  html += '</ul>';
  $('#resultsBody').innerHTML = html;
}

function toggleItem(row) {
  const toggle = row.querySelector('.toggle');
  if (toggle.classList.contains('none')) return;
  toggle.classList.toggle('open');
  const children = row.nextElementSibling;
  if (!children || !children.classList.contains('cname-children')) return;
  children.classList.toggle('expanded');
}

let _allExpanded = false;
function toggleExpandAll() {
  const btn = $('#btnToggleAll');
  _allExpanded = !_allExpanded;
  if (_allExpanded) {
    $$('.toggle:not(.none)').forEach(t => t.classList.add('open'));
    $$('.cname-children').forEach(c => c.classList.add('expanded'));
    if (btn) btn.textContent = '全部折叠';
  } else {
    $$('.toggle:not(.none)').forEach(t => t.classList.remove('open'));
    $$('.cname-children').forEach(c => c.classList.remove('expanded'));
    if (btn) btn.textContent = '全部展开';
  }
}

/* ── Copy: visible items only (collapsed children excluded) ── */
function copyDomains() {
  let lines = [];
  $$('.domain-item').forEach(item => {
    const hostname = item.querySelector('.hostname');
    if (hostname) lines.push(hostname.textContent);
    const children = item.querySelector('.cname-children');
    if (children && children.classList.contains('expanded')) {
      children.querySelectorAll('.cname-child').forEach(child => {
        const hop = child.querySelector('.hop-num');
        const cname = child.querySelector('.cname-target');
        lines.push(`  ${hop.textContent}: ${cname.textContent}`);
      });
    }
  });
  if (lines.length) {
    var text = lines.join('\n');
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function() {
        toast('已复制（仅展开项）');
      }).catch(function() {
        _fallbackCopy(text);
      });
    } else {
      _fallbackCopy(text);
    }
  }
}

function _fallbackCopy(text) {
  var ta = document.createElement('textarea');
  ta.value = text;
  ta.style.position = 'fixed'; ta.style.left = '-9999px';
  document.body.appendChild(ta);
  ta.select();
  try { document.execCommand('copy'); toast('已复制（仅展开项）'); }
  catch (e) { toast('复制失败，请手动选择复制'); }
  document.body.removeChild(ta);
}

/* ── Export: always full data ── */
function exportDomains() {
  let lines = [];
  analysisData.forEach(r => {
    lines.push(r.hostname);
    r.cname_chain.forEach((c, i) => {
      lines.push(`  hop ${i+1}: ${c}`);
    });
  });
  if (!lines.length) return toast('无数据');
  const blob = new Blob([lines.join('\n')+'\n'], {type:'text/plain'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'domains_export.txt';
  a.click();
  URL.revokeObjectURL(a.href);
  toast('已导出（含全部 CNAME 数据）');
}

function toast(msg) {
  const t = $('#toast');
  t.textContent = msg; t.classList.add('show');
  clearTimeout(t._tid);
  t._tid = setTimeout(() => t.classList.remove('show'), 2200);
}

document.addEventListener('keydown', e => {
  if (e.key === 'Enter' && document.activeElement === $('#urlInput')) doCapture();
});
</script>
</body>
</html>"""


@app.route("/")
def index():
    browser_name, _ = _find_browser()
    return render_template_string(INDEX_HTML, browser_name=browser_name or "自动检测")


@app.route("/api/capture", methods=["POST"])
def api_capture():
    try:
        data = request.get_json()
        url = data.get("url", "").strip()
        if not url:
            return jsonify({"error": "URL is required"}), 400

        timeout = float(data.get("timeout", 30))
        wait = float(data.get("wait", 3))
        include_ip = bool(data.get("include_ip", False))
        resolve_dns = bool(data.get("resolve_dns", True))

        domains = capture_domains(url, timeout=timeout, extra_wait=wait,
                                  include_ip=include_ip)
        if resolve_dns and domains:
            results = analyze_domains(domains)
        else:
            results = [{"hostname": d, "cname_chain": []} for d in domains]

        return jsonify({
            "domains_count": len(results),
            "results": results,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ═══════════════════════════════════════════════════════════════════
# Entry
# ═══════════════════════════════════════════════════════════════════

def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5001
    threading.Timer(1.2, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    app.run(host="0.0.0.0", port=port, debug=False)


if __name__ == "__main__":
    main()
