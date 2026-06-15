"""update.bat 生成 & 执行全量测试 — 更新模块最关键的测试。

现有测试的盲区：所有 Playwright 测试都用 page.route() 拦截了 upgrade API，
perform_upgrade() 从未被调用，update.bat 从未被生成或执行。
这导致批处理语法错误（如 echo (...) 在 if 内的解析 bug）完全漏过。

本测试：
  A. 静态分析 — 验证生成的 bat 不含已知的语法陷阱
  B. 步骤模拟 — 逐步骤测试 bat 的 6 个阶段
  C. 端到端 — 完整升级流程（生成 bat → 执行 → 验证）

以后每次修改 upgrade.py，必须运行本测试全部通过才能发版。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_UPGRADE_PY = _PROJECT_ROOT / "application" / "portal" / "upgrade.py"
_TEMP_ROOT = _PROJECT_ROOT / "temp" / "test_upgrade_bat"


def _clean_temp():
    if _TEMP_ROOT.exists():
        shutil.rmtree(_TEMP_ROOT, ignore_errors=True)
    _TEMP_ROOT.mkdir(parents=True, exist_ok=True)


def _port_open(port: int) -> bool:
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.3)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


def _kill_port(port: int) -> None:
    try:
        out = subprocess.check_output(
            f'netstat -ano | findstr ":{port}" | findstr "LISTENING"',
            shell=True, text=True, encoding="utf-8",
        )
        for line in out.strip().split("\n"):
            parts = line.strip().split()
            if parts:
                subprocess.run(["taskkill", "/F", "/PID", parts[-1]],
                               capture_output=True, shell=True)
    except Exception:
        pass


# ============================================================================
# A. 静态分析 — 批处理语法正确性验证
# ============================================================================

class TestBatGeneration:
    """验证 update.bat 生成正确、不含已知语法陷阱。"""

    @pytest.fixture(scope="class")
    def generated_bat(self) -> Path:
        """Generate update.bat same way perform_upgrade() does."""
        _clean_temp()
        # Simulate what perform_upgrade does
        sys.path.insert(0, str(_PROJECT_ROOT / "application" / "portal"))
        import upgrade
        project_dir = str(_TEMP_ROOT / "test_bundle")
        bat_content = upgrade.UPDATE_BAT_TEMPLATE.replace("{bundle_path}", project_dir)
        bat_path = _TEMP_ROOT / "__update__.bat"
        bat_path.write_text(bat_content, encoding="utf-8")
        return bat_path

    def test_bat_file_is_valid_encoding(self, generated_bat):
        """bat 必须 UTF-8 编码、无 BOM 头。"""
        raw = generated_bat.read_bytes()
        assert not raw.startswith(b'\xef\xbb\xbf'), "bat 不得带 UTF-8 BOM"
        generated_bat.read_text(encoding="utf-8")  # must not raise

    def test_bat_starts_with_echo_off(self, generated_bat):
        """bat 必须以 @echo off 开头。"""
        first_line = generated_bat.read_text(encoding="utf-8").splitlines()[0].strip()
        assert first_line == "@echo off", f"第一行应为 @echo off, 实际: {first_line}"

    def test_bat_has_enabledelayedexpansion(self, generated_bat):
        """bat 必须启用延迟变量扩展。"""
        content = generated_bat.read_text(encoding="utf-8")
        assert "setlocal enabledelayedexpansion" in content

    def test_bat_bundle_path_replaced(self, generated_bat):
        """{bundle_path} 必须被替换为实际路径。"""
        content = generated_bat.read_text(encoding="utf-8")
        assert "{bundle_path}" not in content, "{bundle_path} 未被替换"

    def test_bat_no_echo_parens_triple_dot_in_compound_blocks(self, generated_bat):
        """检测已知 bug: echo ... (...) ... 在 if/for 块内触发语法错误。

        模式: echo <text> (<text>)... 在 if (...) 或 for (...) do (...) 内部
        —— 批处理解析器将 ( ) 视为分组，其后的 ... 成为孤立 token → 崩溃。
        """
        content = generated_bat.read_text(encoding="utf-8")
        lines = content.splitlines()
        in_compound = 0  # 跟踪 if / for 嵌套深度
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            # Track compound block depth
            open_parens = stripped.count('(')
            close_parens = stripped.count(')')
            # echo lines inside compound blocks
            if in_compound > 0 and stripped.lower().startswith('echo'):
                # Check for (...) ... pattern
                if re.search(r'\([^)]+\)\s*\.{3}', stripped):
                    pytest.fail(
                        f"Line {i}: echo 在复合块内含 (...)... 模式 → 批处理语法错误"
                        f"\n  {stripped}"
                    )
            # Track nesting
            if ' do (' in stripped:
                in_compound += 1
            if stripped == ')' and in_compound > 0:
                in_compound -= 1
            elif stripped.endswith('('):
                in_compound += 1

    def test_bat_no_chcp(self, generated_bat):
        """bat 不得包含 chcp（纯 ASCII 输出, 见 mistake #36）。"""
        content = generated_bat.read_text(encoding="utf-8")
        assert "chcp" not in content.lower(), "bat 不得包含 chcp 命令"

    def test_bat_no_pause(self, generated_bat):
        """bat 不得包含 pause（零交互, 见 upgrade.py 设计原则）。"""
        content = generated_bat.read_text(encoding="utf-8")
        assert "pause" not in content.lower(), "bat 不得包含 pause"

    def test_bat_has_all_6_steps(self, generated_bat):
        """bat 必须包含全部 6 个步骤标签。"""
        content = generated_bat.read_text(encoding="utf-8")
        for step in range(1, 7):
            assert f"[{step}/6]" in content, f"bat 缺少步骤 [{step}/6]"

    def test_bat_protects_user_data(self, generated_bat):
        """bat 必须备份和恢复用户数据（workspace, placeholders, cache）。"""
        content = generated_bat.read_text(encoding="utf-8")
        assert "editor_workspace" in content, "bat 未备份 editor_workspace"
        assert "user_init_placeholders.json" in content, "bat 未备份 placeholders"
        assert ".update_cache.json" in content, "bat 未备份 .update_cache"

    def test_bat_restarts_with_release_mode(self, generated_bat):
        """bat 必须以 RELEASE_MODE=1 重启 portal。"""
        content = generated_bat.read_text(encoding="utf-8")
        assert 'RELEASE_MODE=1' in content, "bat 未设置 RELEASE_MODE=1"

    def test_bat_uses_endlocal_before_start(self, generated_bat):
        """bat 必须在 start 命令之前 endlocal（防止环境变量泄漏, 见 mistake #37）。"""
        content = generated_bat.read_text(encoding="utf-8")
        endlocal_idx = content.find("\nendlocal\n")
        # start "" 是实际的重启命令（而非 start_all.bat 文件名中的 start）
        start_cmd_idx = content.find('\nstart ""')
        assert endlocal_idx > 0, "bat 缺少 endlocal"
        assert start_cmd_idx > endlocal_idx, \
            f"endlocal 必须在 'start \"\"' 之前 (endlocal at {endlocal_idx}, start at {start_cmd_idx})"


# ============================================================================
# B. 步骤模拟 — update.bat 各步骤独立验证
# ============================================================================

class TestBatStepByStep:
    """模拟 update.bat 的每个步骤，验证可以正常执行。"""

    @pytest.fixture(scope="class")
    def work_dir(self) -> Path:
        _clean_temp()
        wd = _TEMP_ROOT / "work"
        wd.mkdir()
        return wd

    @pytest.fixture(scope="class")
    def test_bundle(self, work_dir) -> Path:
        """Create a minimal bundle that the bat can operate on."""
        bundle = work_dir / "test_bundle"
        # Create expected directory structure
        (bundle / "application" / "all_in_one - cc" / "data" / "editor_workspace").mkdir(parents=True)
        (bundle / "application" / "portal").mkdir(parents=True)
        (bundle / "runtime" / "python").mkdir(parents=True)
        (bundle / "start_all.bat").write_text("@echo off\r\necho test start\r\n", encoding="utf-8")
        # User data files
        (bundle / "application" / "all_in_one - cc" / "data" / "editor_workspace" / "test.json").write_text(
            '{"test":"data"}', encoding="utf-8"
        )
        (bundle / "user_init_placeholders.json").write_text('{}', encoding="utf-8")
        (bundle / ".update_cache.json").write_text('{}', encoding="utf-8")
        return bundle

    def test_step3_backup_restores_correctly(self, test_bundle, work_dir):
        """Step 3 备份 → Step 5 恢复：用户数据必须完整保留。"""
        bak = work_dir / "__ws_backup__"
        bak.mkdir(exist_ok=True)

        # Step 3: backup
        ws_src = test_bundle / "application" / "all_in_one - cc" / "data" / "editor_workspace"
        ws_bak = bak / "editor_workspace"
        ws_bak.mkdir(exist_ok=True)
        if ws_src.exists():
            subprocess.run(
                ["robocopy", str(ws_src), str(ws_bak), "/E", "/R:0", "/W:0", "/NP", "/NFL", "/NDL", "/NJH", "/NJS"],
                capture_output=True, shell=True,
            )

        # Verify backup
        backed_up = ws_bak / "test.json"
        assert backed_up.exists(), f"备份失败: {backed_up}"
        assert backed_up.read_text(encoding="utf-8") == '{"test":"data"}'

        # Simulate upgrade: delete original
        shutil.rmtree(ws_src)
        ws_src.mkdir()

        # Step 5: restore
        if (bak / "editor_workspace").exists():
            subprocess.run(
                ["robocopy", str(bak / "editor_workspace"), str(ws_src), "/E", "/R:0", "/W:0", "/NP", "/NFL", "/NDL", "/NJH", "/NJS"],
                capture_output=True, shell=True,
            )

        # Verify restore
        restored = ws_src / "test.json"
        assert restored.exists(), f"恢复失败: {restored}"
        assert restored.read_text(encoding="utf-8") == '{"test":"data"}'

    def test_step4_extract_and_copy(self, test_bundle, work_dir):
        """Step 4 解压新版本 + robocopy 复制。"""
        # Create a test "new version" zip
        new_zip = work_dir / "__update__.zip"
        with zipfile.ZipFile(new_zip, "w") as zf:
            zf.writestr("new_version/RELEASE_INFO.json",
                        json.dumps({"version": "99.0.0"}))
            zf.writestr("new_version/test_file.txt", "new content")
            zf.writestr("new_version/start_all.bat", "@echo off\r\necho new\r\n")

        # Step 4a: Extract
        tmpdir = work_dir / "__update_tmp__"
        tmpdir.mkdir(exist_ok=True)
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"Expand-Archive -Path '{new_zip}' -DestinationPath '{tmpdir}' -Force"],
            capture_output=True, text=True, encoding="utf-8", shell=True,
        )
        assert result.returncode == 0, f"Expand-Archive failed: {result.stderr}"

        # Verify extraction
        assert (tmpdir / "new_version").is_dir(), "Extraction failed"

        # Step 4b: Robocopy
        for d in tmpdir.iterdir():
            if d.is_dir():
                result = subprocess.run(
                    ["robocopy", str(d), str(test_bundle), "/E", "/R:3", "/W:3",
                     "/NFL", "/NDL", "/NJH", "/NJS", "/NC", "/NS", "/NP"],
                    capture_output=True, shell=True,
                )
                # robocopy exit codes 0-7 are success
                assert result.returncode < 8, f"Robocopy failed: {result.returncode}"

        # Verify copy
        assert (test_bundle / "test_file.txt").exists()
        assert (test_bundle / "test_file.txt").read_text(encoding="utf-8") == "new content"


# ============================================================================
# C. 端到端 — 完整升级流程
# ============================================================================

class TestFullUpgradeBat:
    """完整升级流程：生成 bat → 模拟执行各步骤 → 验证结果。"""

    @pytest.fixture(scope="class")
    def e2e_env(self):
        """Set up complete end-to-end test environment."""
        _clean_temp()

        # Create "old" bundle (simulating customer's extracted v1.1.9)
        old_bundle = _TEMP_ROOT / "customer_old" / "帮你节省5分钟"
        old_bundle.mkdir(parents=True)
        (old_bundle / "RELEASE_INFO.json").write_text(
            '{"version":"1.1.9"}', encoding="utf-8"
        )
        (old_bundle / "application" / "portal").mkdir(parents=True)
        (old_bundle / "application" / "portal" / "app.py").write_text(
            "# release portal", encoding="utf-8"
        )
        (old_bundle / "application" / "all_in_one - cc" / "data" / "editor_workspace").mkdir(parents=True)
        (old_bundle / "application" / "all_in_one - cc" / "data" / "editor_workspace" / "user_template.json").write_text(
            '{"name":"my template"}', encoding="utf-8"
        )
        (old_bundle / "user_init_placeholders.json").write_text('{"test":"data"}', encoding="utf-8")
        (old_bundle / ".update_cache.json").write_text('{"cached":true}', encoding="utf-8")
        (old_bundle / "start_all.bat").write_text("@echo off\r\necho old\r\n", encoding="utf-8")

        # Create "new" zip (simulating downloaded v1.1.10)
        new_zip = _TEMP_ROOT / "customer_old" / "__update__.zip"
        with zipfile.ZipFile(new_zip, "w") as zf:
            zf.writestr("帮你节省5分钟/RELEASE_INFO.json",
                        json.dumps({"version": "1.1.10"}))
            zf.writestr("帮你节省5分钟/application/portal/app.py",
                        "# release portal v1.1.10")
            zf.writestr("帮你节省5分钟/start_all.bat",
                        "@echo off\r\necho new version\r\n")
            zf.writestr("帮你节省5分钟/application/all_in_one - cc/data/editor_workspace/.keep",
                        "")
            zf.writestr("帮你节省5分钟/user_init_placeholders.json", '{"from_zip":"data"}')
            zf.writestr("帮你节省5分钟/.update_cache.json", '{"from_zip":true}')
            # Add a new file to verify it arrives
            zf.writestr("帮你节省5分钟/NEW_FEATURE.txt", "this is new in v1.1.10")

        # Generate update.bat
        sys.path.insert(0, str(_PROJECT_ROOT / "application" / "portal"))
        import upgrade
        project_dir = str(old_bundle.resolve())
        bat_content = upgrade.UPDATE_BAT_TEMPLATE.replace("{bundle_path}", project_dir)
        bat_path = _TEMP_ROOT / "customer_old" / "__update__.bat"
        bat_path.write_text(bat_content, encoding="utf-8")

        return {
            "old_bundle": old_bundle,
            "new_zip": new_zip,
            "bat_path": bat_path,
        }

    def test_generated_bat_passes_static_checks(self, e2e_env):
        """生成的 bat 通过所有静态检查。"""
        content = e2e_env["bat_path"].read_text(encoding="utf-8")
        # No syntax traps
        import re as _re
        for i, line in enumerate(content.splitlines(), 1):
            stripped = line.strip()
            if stripped.lower().startswith('echo'):
                if _re.search(r'\([^)]+\)\s*\.{3}', stripped):
                    # Only fail if inside a compound block (indented)
                    if line.startswith('    ') or line.startswith('\t'):
                        pytest.fail(f"Line {i}: echo (...) in compound block: {stripped}")
        # Key variables
        assert "RELEASE_MODE=1" in content
        assert "start_all.bat" in content
        # No {bundle_path} placeholder
        assert "{bundle_path}" not in content

    def test_step3_backup_preserves_user_data(self, e2e_env):
        """Step 3 备份：用户数据正确备份。"""
        old = e2e_env["old_bundle"]
        bak = _TEMP_ROOT / "customer_old" / "__ws_backup__"
        bak.mkdir(exist_ok=True)

        ws = old / "application" / "all_in_one - cc" / "data" / "editor_workspace"
        ws_bak = bak / "editor_workspace"
        subprocess.run(
            ["robocopy", str(ws), str(ws_bak), "/E", "/R:0", "/W:0", "/NP", "/NFL", "/NDL", "/NJH", "/NJS"],
            capture_output=True, shell=True,
        )
        assert (ws_bak / "user_template.json").exists()
        assert (ws_bak / "user_template.json").read_text(encoding="utf-8") == '{"name":"my template"}'

        # Backup placeholders and cache
        for fname in ["user_init_placeholders.json", ".update_cache.json"]:
            shutil.copy2(old / fname, bak / fname)
            assert (bak / fname).exists()

    def test_step4_extraction_produces_correct_structure(self, e2e_env):
        """Step 4 解压：新版本文件正确提取。"""
        new_zip = e2e_env["new_zip"]
        tmp = _TEMP_ROOT / "customer_old" / "__update_tmp__"
        tmp.mkdir(exist_ok=True)

        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"Expand-Archive -Path '{new_zip}' -DestinationPath '{tmp}' -Force"],
            capture_output=True, text=True, encoding="utf-8", shell=True,
        )
        assert result.returncode == 0, f"Expand-Archive failed: {result.stderr}"
        assert (tmp / "帮你节省5分钟").is_dir()
        assert (tmp / "帮你节省5分钟" / "RELEASE_INFO.json").exists()
        ri = json.loads((tmp / "帮你节省5分钟" / "RELEASE_INFO.json").read_text(encoding="utf-8"))
        assert ri["version"] == "1.1.10"

    def test_step4_robocopy_delivers_new_files(self, e2e_env):
        """Step 4 robocopy：新文件正确复制到 bundle。"""
        new_zip = e2e_env["new_zip"]
        old = e2e_env["old_bundle"]
        tmp = _TEMP_ROOT / "customer_old" / "__update_tmp__"
        tmp.mkdir(exist_ok=True)

        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"Expand-Archive -Path '{new_zip}' -DestinationPath '{tmp}' -Force"],
            capture_output=True, shell=True,
        )

        # Robocopy from extracted dir to bundle
        for d in tmp.iterdir():
            if d.is_dir():
                result = subprocess.run(
                    ["robocopy", str(d), str(old), "/E", "/R:3", "/W:3",
                     "/NFL", "/NDL", "/NJH", "/NJS", "/NC", "/NS", "/NP"],
                    capture_output=True, shell=True,
                )
                assert result.returncode < 8, f"robocopy exit {result.returncode}"

        # Verify new file arrived
        assert (old / "NEW_FEATURE.txt").exists()
        assert (old / "NEW_FEATURE.txt").read_text(encoding="utf-8") == "this is new in v1.1.10"
        # Verify RELEASE_INFO updated
        ri = json.loads((old / "RELEASE_INFO.json").read_text(encoding="utf-8"))
        assert ri["version"] == "1.1.10"

    def test_step5_restore_preserves_user_data_after_upgrade(self, e2e_env):
        """Step 5 恢复：升级后用户数据保留。"""
        old = e2e_env["old_bundle"]
        bak = _TEMP_ROOT / "customer_old" / "__ws_backup__"

        # Simulate: robocopy happened (overwrote user data), now restore
        # Restore workspace
        if (bak / "editor_workspace").exists():
            subprocess.run(
                ["robocopy", str(bak / "editor_workspace"),
                 str(old / "application" / "all_in_one - cc" / "data" / "editor_workspace"),
                 "/E", "/R:0", "/W:0", "/NP", "/NFL", "/NDL", "/NJH", "/NJS"],
                capture_output=True, shell=True,
            )

        # Restore individual files (placeholders + cache)
        for fname in ["user_init_placeholders.json", ".update_cache.json"]:
            bak_file = bak / fname
            if bak_file.exists():
                shutil.copy2(str(bak_file), str(old / fname))

        # User template should be restored
        tmpl = old / "application" / "all_in_one - cc" / "data" / "editor_workspace" / "user_template.json"
        assert tmpl.exists(), "用户模板未恢复"
        assert tmpl.read_text(encoding="utf-8") == '{"name":"my template"}'

        # placeholders restored (check that original data survived, not zip data)
        ph = old / "user_init_placeholders.json"
        assert ph.exists()
        assert '"test":"data"' in ph.read_text(encoding="utf-8"), \
            f"用户 placeholders 未恢复，实际内容: {ph.read_text(encoding='utf-8')[:100]}"

    def test_step6_restart_command_valid(self, e2e_env):
        """Step 6 重启：bat 的最后一步命令合法。"""
        content = e2e_env["bat_path"].read_text(encoding="utf-8")
        # Find the restart section
        restart_section = content[content.find("[6/6]"):]
        assert "start_all.bat" in restart_section
        assert "RELEASE_MODE=1" in restart_section
        # start command should use empty title
        assert 'start ""' in restart_section or 'start ""' in restart_section.lower()

    def test_full_bat_syntax_valid_on_windows(self, e2e_env):
        """在真实 Windows cmd.exe 中验证 bat 语法（不实际执行升级操作）。"""
        bat_path = e2e_env["bat_path"]
        # Run cmd /c with echo off and exit at the first real command
        # to validate syntax parsing without side effects
        test_bat = _TEMP_ROOT / "customer_old" / "__syntax_test.bat"
        # Take the bat but change dangerous commands to echo
        content = e2e_env["bat_path"].read_text(encoding="utf-8")
        # Neutralize destructive/spawning commands for syntax check.
        # `start` MUST be neutralized: even when the target start_all.bat does not
        # exist, `start "" ...` opens a NEW console window whose lifetime is
        # independent of the parent bat. Under subprocess capture, that child
        # inherits the stdout pipe and keeps it open → communicate() hangs until
        # timeout. Echoing it validates syntax without spawning anything.
        # (see log/mistake.txt #54)
        safe = content.replace("taskkill /F /PID", "echo taskkill /F /PID")
        safe = safe.replace("rmdir /s /q", "echo rmdir /s /q")
        safe = safe.replace("robocopy", "echo robocopy")
        safe = safe.replace("rd /s /q", "echo rd /s /q")
        safe = safe.replace("del ", "echo del ")
        safe = safe.replace("timeout /t", "echo timeout /t")
        safe = safe.replace("powershell", "echo powershell")
        safe = safe.replace("mkdir ", "echo mkdir ")
        safe = safe.replace("netstat ", "echo netstat ")
        safe = safe.replace('start ""', 'echo start ""')
        test_bat.write_text(safe, encoding="utf-8")

        # Capture as BYTES, then decode with the OS ANSI codepage (cp936/GBK on
        # zh-CN Windows). The bat is pure ASCII (mistake.txt #36), but cmd.exe's
        # own error messages ("系统找不到文件" etc.) are emitted in the console's
        # active codepage, not UTF-8. Forcing encoding="utf-8" here crashed the
        # reader thread and produced a spurious test failure (mistake.txt #54).
        result = subprocess.run(
            ["cmd", "/c", str(test_bat)],
            cwd=str(test_bat.parent),
            capture_output=True, shell=True,
            timeout=60,
        )
        stdout = result.stdout.decode("mbcs", errors="replace") if result.stdout else ""
        stderr = result.stderr.decode("mbcs", errors="replace") if result.stderr else ""
        # Check stderr for batch syntax errors
        assert "was unexpected at this time" not in stderr.lower(), \
            f"bat syntax error: {stderr.strip()}"
        assert "unexpected" not in stderr.lower(), \
            f"bat syntax error: {stderr.strip()}"
        # stdout should contain step markers
        for step in range(1, 7):
            assert f"[{step}/6]" in stdout, f"bat 未执行步骤 [{step}/6]"


# ============================================================================
# 清理
# ============================================================================

def teardown_module():
    _clean_temp()
