"""检查远端是否有新版本可用。

设计原则（严守"不允许猜测"）：
- 拉不到远端 / 配置缺失 / 版本号无法比较时，**绝不**回退到"假装已是最新"。
  前端会得到明确的状态标识（network_error / config_error / incomparable）。
- 多个数据源按用户配置顺序尝试，所有失败原因都返回给前端，便于排障。
- 默认读取本进程同目录的 update_config.json，客户可改，无配置时仅做"未配置"提示。

数据流：
  本地版本：从 zip 解压根的 RELEASE_INFO.json 读取（build_release.py 写入）
  远端版本：GitHub Release API → 自定义镜像 manifest（任一成功即返回）

返回结构（status 一律存在）：
  {
    "status": "ok" | "config_error" | "network_error",
    "local_version": "0.2.2" | None,
    "remote_version": "0.3.0" | None,
    "comparison": "older" | "same" | "newer" | "incomparable",
    "has_update": bool,                # 仅 comparison == "older" 时为 True
    "release_url": "...",              # 客户点击横幅跳转的页面
    "download_url": "...",             # 直接下载 zip 的链接（如果远端给出）
    "source": "github" | "mirror",     # 命中哪个数据源
    "errors": [...],                   # 命中前所有失败原因
    "checked_at": <unix-seconds>,
    "from_cache": bool,
  }
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

CONFIG_FILENAME = "update_config.json"
CACHE_FILENAME = ".update_cache.json"

DEFAULT_CONFIG: dict[str, Any] = {
    # GitHub 仓库 owner/repo；置空则跳过此源（默认置空：当前项目仓库为 private，匿名拉不到）
    "github_repo": "",
    # 自定义镜像 manifest.json 的公网地址，返回 JSON: {version, release_url, download_url}
    # 客户拿到包后只需把 update_config.json 的 mirror_url 改成你的地址即可启用更新提醒

    "mirror_urls": [],
    "mirror_url": "",
    # 单源超时秒数
    "timeout_seconds": 5,
    # 缓存有效期，避免每次首页刷新都打外网
    "cache_ttl_seconds": 3600,
    # User-Agent，方便服务端日志识别请求来源
    "user_agent": "5mins-portal-update-check",
}

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent.parent  # <root>/application/portal/ -> <root>
_LOCAL_RELEASE_INFO = _PROJECT_ROOT / "RELEASE_INFO.json"

_lock = threading.Lock()
_memory_cache: tuple[float, dict] | None = None  # (when_checked, result)


# ── 配置 ────────────────────────────────────────────────────────────────
def load_config(config_path: Path | None = None) -> dict[str, Any]:
    """读取配置；缺失文件或读取异常时回退到 DEFAULT_CONFIG（仅默认值，不猜测语义）。"""
    cfg = dict(DEFAULT_CONFIG)
    path = config_path or (_HERE / CONFIG_FILENAME)
    if path.is_file():
        try:
            user_cfg = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(user_cfg, dict):
                cfg.update({k: v for k, v in user_cfg.items() if k in DEFAULT_CONFIG})
        except (OSError, json.JSONDecodeError):
            # 配置文件损坏 → 用默认；不静默忽略，写到 errors 里供前端排查
            cfg["_config_error"] = f"配置文件无法解析：{path}"
    return cfg


# ── 本地版本 ────────────────────────────────────────────────────────────
def get_local_version() -> str | None:
    """从 RELEASE_INFO.json 读"当前运行的版本"。

    无文件（开发模式或源码运行）时返回 None；不猜、不假装。
    """
    if not _LOCAL_RELEASE_INFO.is_file():
        return None
    try:
        meta = json.loads(_LOCAL_RELEASE_INFO.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    v = meta.get("version")
    if isinstance(v, str) and v.strip():
        return v.strip()
    return None


# ── 版本比较（语义化版本，无法解析显式返回 incomparable） ────────────────
def _parse_semver(s: str | None) -> tuple[int, int, int] | None:
    if not isinstance(s, str):
        return None
    # 去掉前缀 v / V，去掉 pre-release / build metadata
    core = s.lstrip("vV").split("-", 1)[0].split("+", 1)[0]
    parts = core.split(".")
    if not 1 <= len(parts) <= 4:
        return None
    nums: list[int] = []
    for p in parts:
        if not p.isdigit():
            return None
        nums.append(int(p))
    while len(nums) < 3:
        nums.append(0)
    return (nums[0], nums[1], nums[2])


def compare_versions(local: str | None, remote: str | None) -> str:
    """返回 'older' | 'same' | 'newer' | 'incomparable'。

    incomparable = 任一侧无法解析为语义化版本，前端会显示"远端版本 X，本地版本 Y"原样字符串
    供用户自行判断；**绝不**默认返回 same。
    """
    lp = _parse_semver(local)
    rp = _parse_semver(remote)
    if lp is None or rp is None:
        return "incomparable"
    if lp < rp:
        return "older"
    if lp > rp:
        return "newer"
    return "same"


# ── 远端 ────────────────────────────────────────────────────────────────
def _http_get_json(url: str, timeout: float, ua: str) -> Any:
    req = urllib.request.Request(url, headers={
        "User-Agent": ua,
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if resp.status != 200:
            raise urllib.error.HTTPError(url, resp.status, "non-200", resp.headers, None)
        return json.loads(resp.read().decode("utf-8"))


def fetch_github_latest(repo: str, timeout: float, ua: str) -> tuple[str, str, str | None]:
    """返回 (version, release_url, download_url|None)；任一异常向上抛。"""
    api = f"https://api.github.com/repos/{repo}/releases/latest"
    data = _http_get_json(api, timeout=timeout, ua=ua)
    version = data.get("tag_name") or data.get("name")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("GitHub 响应缺少 tag_name/name 字段")
    release_url = data.get("html_url") or f"https://github.com/{repo}/releases/latest"
    download_url: str | None = None
    for a in data.get("assets") or []:
        name = (a.get("name") or "").lower()
        if name.endswith(".zip"):
            download_url = a.get("browser_download_url")
            break
    return version.strip(), release_url, download_url


def fetch_mirror_manifest(url: str, timeout: float, ua: str) -> tuple[str, str, str | None]:
    """镜像 manifest 必须为 JSON: {"version": "...", "release_url": "...", "download_url": "..."}。"""
    data = _http_get_json(url, timeout=timeout, ua=ua)
    version = data.get("version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("镜像 manifest 缺少 version 字段")
    release_url = data.get("release_url") or url
    download_url = data.get("download_url")
    return version.strip(), release_url, download_url


# ── 主流程 ──────────────────────────────────────────────────────────────
def _check_uncached(cfg: dict[str, Any]) -> dict[str, Any]:
    local = get_local_version()
    timeout = float(cfg.get("timeout_seconds") or 5)
    ua = str(cfg.get("user_agent") or "5mins-portal-update-check")

    sources: list[tuple[str, callable]] = []
    repo = (cfg.get("github_repo") or "").strip()
    mirror = (cfg.get("mirror_url") or "").strip()
    mirror_list: list[str] = []
    if isinstance(cfg.get("mirror_urls"), list):
        mirror_list.extend(str(u).strip() for u in cfg["mirror_urls"] if str(u).strip())
    if repo:
        sources.append(("github", lambda: fetch_github_latest(repo, timeout, ua)))
    if mirror:
        sources.append(("mirror", lambda: fetch_mirror_manifest(mirror, timeout, ua)))
    for m in mirror_list:
        if m != mirror:
            sources.append(("mirror", lambda u=m: fetch_mirror_manifest(u, timeout, ua)))

    base: dict[str, Any] = {
        "local_version": local,
        "remote_version": None,
        "comparison": "incomparable",
        "has_update": False,
        "release_url": None,
        "download_url": None,
        "source": None,
        "errors": [],
        "checked_at": int(time.time()),
    }

    if "_config_error" in cfg:
        base["errors"].append(cfg["_config_error"])

    if not sources:
        return {
            **base,
            "status": "config_error",
            "message": "update_config.json 未配置 github_repo 或 mirror_url",
        }

    for name, fetcher in sources:
        try:
            version, release_url, download_url = fetcher()
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
            base["errors"].append(f"{name}: {type(exc).__name__}: {exc}")
            continue
        except (ValueError, json.JSONDecodeError) as exc:
            base["errors"].append(f"{name}: parse_error: {exc}")
            continue

        cmp = compare_versions(local, version)
        return {
            **base,
            "status": "ok",
            "source": name,
            "remote_version": version,
            "release_url": release_url,
            "download_url": download_url,
            "comparison": cmp,
            "has_update": cmp == "older",
        }

    return {
        **base,
        "status": "network_error",
        "message": "无法连接更新服务器",
    }


# ── 缓存（内存 + 磁盘） ─────────────────────────────────────────────────
def _cache_path() -> Path:
    return _HERE / CACHE_FILENAME


def _load_disk_cache() -> tuple[float, dict] | None:
    p = _cache_path()
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
        ts = float(data.get("timestamp"))
        result = data.get("result")
        if isinstance(result, dict):
            return ts, result
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    return None


def _save_disk_cache(ts: float, result: dict) -> None:
    p = _cache_path()
    try:
        p.write_text(
            json.dumps({"timestamp": ts, "result": result}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


def check(force: bool = False) -> dict[str, Any]:
    """主入口。force=True 跳过缓存。"""
    global _memory_cache
    cfg = load_config()
    ttl = float(cfg.get("cache_ttl_seconds") or 3600)

    with _lock:
        now = time.time()
        if not force:
            cache = _memory_cache or _load_disk_cache()
            if cache and (now - cache[0]) < ttl:
                _memory_cache = cache
                cached_result = dict(cache[1])
                cached_result["from_cache"] = True
                cached_result["cache_age_seconds"] = int(now - cache[0])
                return cached_result

        result = _check_uncached(cfg)
        _memory_cache = (now, result)
        _save_disk_cache(now, result)
        result = dict(result)
        result["from_cache"] = False
        result["cache_age_seconds"] = 0
        return result


def reset_cache_for_tests() -> None:
    """仅测试用：清空内存缓存 + 删磁盘缓存。"""
    global _memory_cache
    with _lock:
        _memory_cache = None
        try:
            _cache_path().unlink(missing_ok=True)
        except OSError:
            pass
