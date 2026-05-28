# Plan: Single .exe Domain Capture Tool

## Context

用户需要一个可直接交付的 .exe 文件，包含完整 GUI + 域名抓取功能。删除旧的多余文件，从简重构。

## Steps

1. **清理** — 删除 `capture_domains.py`、`main.py`、`requirements.txt`
2. **合并** — 创建单一 `app.py`，融合 GUI (tkinter) + 抓取逻辑 (Playwright)
3. **打包** — PyInstaller `--onefile --windowed` 生成 `DomainCapture.exe`
4. **记录** — 更新 plan/ 和 log/

## app.py 结构

单一文件，包含：
- DESIGN.md 颜色/token 常量
- `capture_domains()` 函数（从原 capture_domains.py 合并）
- `DomainCaptureApp` 类（从原 main.py 合并，优化 tkinter UI）
- `main()` 入口

## PyInstaller 打包命令

```
pyinstaller --onefile --windowed --name DomainCapture ^
    --add-data "C:\...\ms-playwright\chromium-1217\chrome-win64;chromium" ^
    --hidden-import greenlet --hidden-import pyee ^
    app.py
```

## 关键实现

- 使用 `executable_path` 参数指定打包后的 Chromium 路径
- 区分 frozen (exe) 和 script 运行模式读 Chromium 路径
- `--windowed` 隐藏控制台窗口

## Verification

1. 双击 `DomainCapture.exe` 打开 GUI
2. 输入 URL → 抓取 → 显示域名列表
3. 导出/复制功能正常
