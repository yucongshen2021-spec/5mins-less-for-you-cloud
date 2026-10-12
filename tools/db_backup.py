#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据库定时备份脚本 -- 每天 2 次热备 SQLite 数据库。

备份策略：
- 通过 docker exec 在容器内用 Python sqlite3.Connection.backup() 做在线热备
  （WAL 安全，不需要停服务）
- 备份 auth.sqlite + stats.sqlite 两个数据库
- 备份文件存到宿主机 /opt/fivemins/db_backup/
- 保留最近 14 天的备份，每周一的备份永久保留到 weekly/ 目录
- 备份完成后做 PRAGMA integrity_check 验证完整性

用法：
  python3 /opt/fivemins/tools/db_backup.py           # 正常备份
  python3 /opt/fivemins/tools/db_backup.py --check    # 只检查现有备份
"""

import os
import sys
import subprocess
import shutil
from datetime import datetime, timedelta
from pathlib import Path

# ── 配置 ──────────────────────────────────────────────────────────
CONTAINER = "fivemins-portal"
DB_DIR_IN_CONTAINER = "/app/application/portal/logs"
DB_FILES = ["auth.sqlite", "stats.sqlite"]
BACKUP_DIR = Path("/opt/fivemins/db_backup")
WEEKLY_DIR = BACKUP_DIR / "weekly"
LOG_FILE = BACKUP_DIR / "backup.log"
RETENTION_DAYS = 14  # 普通备份保留天数
CONTAINER_PYTHON = "python3"

# ── 日志 ──────────────────────────────────────────────────────────
def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

# ── 容器内热备脚本（通过 docker exec 执行）────────────────────────
# 用 sqlite3.Connection.backup() API，WAL 模式下安全的热备
BACKUP_SCRIPT_IN_CONTAINER = '''
import sqlite3, sys, os, tempfile

db_dir = "{db_dir}"
db_file = sys.argv[1]
out_path = sys.argv[2]

src = os.path.join(db_dir, db_file)
if not os.path.exists(src):
    print(f"ERROR: {{src}} not found", file=sys.stderr)
    sys.exit(1)

# 先备份到临时文件，验证完整性后再 rename
tmp_path = out_path + ".tmp"
try:
    src_conn = sqlite3.connect(src)
    dst_conn = sqlite3.connect(tmp_path)
    src_conn.backup(dst_conn)
    dst_conn.close()
    src_conn.close()

    # 验证完整性
    chk_conn = sqlite3.connect(tmp_path)
    result = chk_conn.execute("PRAGMA integrity_check").fetchone()
    chk_conn.close()
    if result[0] != "ok":
        print(f"ERROR: integrity_check failed for {{db_file}}: {{result[0]}}", file=sys.stderr)
        os.unlink(tmp_path)
        sys.exit(1)

    # rename 到最终路径
    os.replace(tmp_path, out_path)
    fsize = os.path.getsize(out_path)
    print(f"OK: {{db_file}} -> {{out_path}} ({{fsize}} bytes)")
except Exception as e:
    if os.path.exists(tmp_path):
        os.unlink(tmp_path)
    print(f"ERROR: {{e}}", file=sys.stderr)
    sys.exit(1)
'''.format(db_dir=DB_DIR_IN_CONTAINER)


def check_container_running() -> bool:
    """检查容器是否在运行。"""
    try:
        result = subprocess.run(
            ["sudo", "docker", "inspect", "-f", "{{.State.Running}}", CONTAINER],
            capture_output=True, text=True, timeout=10
        )
        return result.stdout.strip() == "true"
    except Exception:
        return False


def backup_one_db(db_file: str, out_path: str) -> bool:
    """通过 docker exec 在容器内执行热备，再 docker cp 到宿主机。

    out_path 是宿主机路径。容器内先备份到 /tmp/，再拷出来。
    """
    container_tmp = f"/tmp/_backup_{db_file}.sqlite"
    try:
        # Step 1: 容器内热备到 /tmp/
        result = subprocess.run(
            ["sudo", "docker", "exec", CONTAINER, CONTAINER_PYTHON, "-c",
             BACKUP_SCRIPT_IN_CONTAINER, db_file, container_tmp],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            log(f"FAIL: {db_file} container backup - {result.stderr.strip()}")
            return False
        log(result.stdout.strip())

        # Step 2: docker cp 到宿主机
        result = subprocess.run(
            ["sudo", "docker", "cp", f"{CONTAINER}:{container_tmp}", out_path],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            log(f"FAIL: {db_file} docker cp - {result.stderr.strip()}")
            return False

        # Step 3: 清理容器内临时文件
        subprocess.run(
            ["sudo", "docker", "exec", CONTAINER, "rm", "-f", container_tmp],
            capture_output=True, timeout=10
        )

        return True
    except subprocess.TimeoutExpired:
        log(f"FAIL: {db_file} - timeout")
        return False
    except Exception as e:
        log(f"FAIL: {db_file} - {e}")
        return False


def verify_backup(out_path: str) -> bool:
    """在宿主机上验证备份文件完整性。用 immutable 模式打开，不创建 WAL/SHM 文件。"""
    if not out_path.exists() or out_path.stat().st_size == 0:
        return False
    try:
        import sqlite3
        # immutable 模式：只读，不创建 -wal/-shm 文件
        conn = sqlite3.connect(f"file:{out_path}?immutable=1", uri=True)
        result = conn.execute("PRAGMA integrity_check").fetchone()
        conn.close()
        ok = result[0] == "ok"
        if ok:
            log(f"VERIFY OK: {out_path.name}")
        else:
            log(f"VERIFY FAIL: {out_path.name} - {result[0]}")
        return ok
    except Exception as e:
        log(f"VERIFY FAIL: {out_path.name} - {e}")
        return False


def cleanup_old_backups():
    """清理超过 RETENTION_DAYS 天的普通备份（不动 weekly/ 目录）。同时清理残留的 -wal/-shm。"""
    cutoff = datetime.now() - timedelta(days=RETENTION_DAYS)
    removed = 0
    for f in BACKUP_DIR.iterdir():
        if not f.is_file():
            continue
        # 清理残留的 WAL/SHM 文件（所有，不看时间）
        # 注意：Path("x.sqlite-wal").suffix 是 ".sqlite-wal"，必须用 endswith 判断
        if f.name.endswith(("-wal", "-shm")):
            f.unlink()
            continue
        if not f.name.endswith(".sqlite"):
            continue
        try:
            mtime = datetime.fromtimestamp(f.stat().st_mtime)
            if mtime < cutoff:
                f.unlink()
                removed += 1
                log(f"CLEANUP: removed {f.name} (older than {RETENTION_DAYS} days)")
        except Exception as e:
            log(f"CLEANUP SKIP: {f.name} - {e}")
    if removed == 0:
        log(f"CLEANUP: no expired backups (retention={RETENTION_DAYS}d)")


def save_weekly_if_monday(now: datetime, backups_made: list):
    """如果是周一，额外复制一份到 weekly/ 目录（永久保留）。"""
    if now.weekday() != 0:  # 0=Monday
        return
    date_str = now.strftime("%Y%m%d")
    for db_file, out_path in backups_made:
        base = db_file.replace(".sqlite", "")
        weekly_path = WEEKLY_DIR / f"{base}_{date_str}_weekly.sqlite"
        try:
            shutil.copy2(str(out_path), str(weekly_path))
            log(f"WEEKLY: saved {weekly_path.name}")
        except Exception as e:
            log(f"WEEKLY FAIL: {weekly_path.name} - {e}")


def list_backups():
    """列出所有现有备份。"""
    log("=== 现有备份 ===")
    for d in [BACKUP_DIR, WEEKLY_DIR]:
        label = "普通" if d == BACKUP_DIR else "周备份"
        files = sorted(d.glob("*.sqlite"), key=lambda f: f.stat().st_mtime, reverse=True)
        if not files:
            log(f"  [{label}] 无")
            continue
        total_size = 0
        for f in files:
            size = f.stat().st_size
            total_size += size
            mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            log(f"  [{label}] {f.name}  {size:>10,} bytes  {mtime}")
        log(f"  [{label}] 共 {len(files)} 个文件, 总计 {total_size:,} bytes")


def main():
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    WEEKLY_DIR.mkdir(parents=True, exist_ok=True)

    if "--check" in sys.argv:
        list_backups()
        return

    now = datetime.now()
    ts = now.strftime("%Y%m%d_%H%M")
    log(f"===== 开始备份 ({ts}) =====")

    # 检查容器
    if not check_container_running():
        log(f"ERROR: 容器 {CONTAINER} 未运行，跳过备份")
        sys.exit(1)

    # 逐个备份
    backups_made = []
    all_ok = True
    for db_file in DB_FILES:
        base = db_file.replace(".sqlite", "")
        out_path = BACKUP_DIR / f"{base}_{ts}.sqlite"
        if backup_one_db(db_file, str(out_path)):
            if verify_backup(out_path):
                backups_made.append((db_file, out_path))
            else:
                all_ok = False
        else:
            all_ok = False

    # 周一保存周备份
    if backups_made:
        save_weekly_if_monday(now, backups_made)

    # 清理过期备份
    cleanup_old_backups()

    if all_ok and backups_made:
        log(f"===== 备份完成: {len(backups_made)}/{len(DB_FILES)} 成功 =====")
    else:
        log(f"===== 备份结束: 有失败项 ({len(backups_made)}/{len(DB_FILES)} 成功) =====")
        sys.exit(1)


if __name__ == "__main__":
    main()
