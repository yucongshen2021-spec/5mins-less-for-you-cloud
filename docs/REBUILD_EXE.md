# 桌面版 exe 重建指南（wine 跨平台打包）

> 用途：重建「FASTIP 测试报告」应用（5006）提供的 Windows 桌面版压缩包。
> 完整过程实录见 `log/2026-07-27.md`。本机工具链已就绪，无需重装。

## 一、工具链现状（已持久化在服务器）

| 组件 | 路径 | 说明 |
|------|------|------|
| wine（9.0，apt 安装） | 系统级 | `WINEPREFIX=/opt/fivemins/.wine64`（win64，743M） |
| Windows Python 3.13 | `/opt/fivemins/.build_cache/wpython/python/python.exe` | 含 tkinter / pip（python-build-standalone 完整版） |
| 桌面版源码 | `/home/ubuntu/fastip-auto-test-report`（git clone） | 仅源码；exe/zip 不入库 |

> `/opt/fivemins/.wine64` 与 `.build_cache` 均在 `.gitignore`，但**不要删除**——重建 exe 的唯一工具链。

## 二、打包步骤

```bash
# 0) 准备源码（若无克隆）
git clone https://github.com/yucongshen2021-spec/fastip-auto-test-report.git /home/ubuntu/fastip-auto-test-report

# 1) 打引擎 exe（onefile，console）
cd /home/ubuntu/fastip-auto-test-report
WINEPREFIX=/opt/fivemins/.wine64 WINEARCH=win64 \
  WINEDLLOVERRIDES="mscoree,mshtml=d" WINEDEBUG=-all \
  wine /opt/fivemins/.build_cache/wpython/python/python.exe -m PyInstaller \
    --onefile make_report.py

# 2) 打 GUI exe（--windowed，即 report_gui.py）
#    同上命令，把 make_report.py 换成 report_gui.py，加 --windowed

# 3) GUI 冒烟（xvfb-run；25 秒被 timeout 杀且无 traceback/秒退 即通过）
timeout 25 xvfb-run -a wine dist/report_gui.exe

# 4) 更新发布包（zip 内含两个 exe + 使用说明）
#    替换后放到：/opt/fivemins/application/fastip_report/data/fastip-auto-test-report.zip

# 5) 让线上生效（zip 在镜像内，不进 git）
cd /opt/fivemins && sudo docker-compose up -d --build
```

## 三、已知现象（非故障）

- `ensurepip` 报 `CopyFile2 unimplemented`——wine 的已知限制，pip 26.1.1 仍可用。
- 依赖全部为预编译 Windows wheel（paramiko / python-docx / Pillow / pyinstaller），无需编译。
- PyInstaller 不跨平台：不能在 Linux 直接打 Windows exe，必须经 wine + Windows Python。
