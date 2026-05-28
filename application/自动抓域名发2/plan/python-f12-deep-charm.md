# Plan: F12 Domain Capture Tool

## Context

用户需要一款 Python 脚本，输入一个网页 URL 后，自动使用无头浏览器加载该页面，抓取所有网络请求中的域名（包括子域名），类似浏览器 F12 开发者工具 Network 面板的功能。当前目录为空，从零搭建。

## Approach

使用 **Playwright for Python** 作为核心工具：
- Playwright 驱动 headless Chromium 浏览器
- 通过 `page.on("request")` 事件捕获页面加载过程中的所有网络请求
- 从每个请求 URL 中提取 hostname（域名+子域名）
- 去重、排序后输出

选择 Playwright 而非 Selenium 的原因：Playwright 原生支持网络请求拦截，Selenium 需要用代理（BrowserMob）才能抓请求，Playwright 更轻量更可靠。

## Files to Create

### 1. `requirements.txt`
```
playwright>=1.40.0
```
运行 `playwright install chromium` 安装浏览器。

### 2. `capture_domains.py`

核心脚本，结构如下：

**命令行参数：**
| 参数 | 必选 | 说明 | 默认值 |
|------|------|------|--------|
| `url` | 是 | 目标网页 URL | - |
| `--timeout` | 否 | 页面加载超时(秒) | 30 |
| `--wait` | 否 | network idle 后额外等待(秒) | 3 |
| `--output` | 否 | 输出文件路径 | 无(仅终端) |
| `--include-ip` | 否 | 结果中包含 IP 地址 | false |

**处理流程：**
1. 解析命令行参数
2. 启动 headless Chromium（`playwright.chromium.launch(headless=True)`）
3. 创建新页面，注册 `request` 事件监听器，收集每个请求的 hostname
4. `page.goto(url)` 导航到目标页，`wait_until="networkidle"`
5. 额外 `sleep(wait)` 等待懒加载/异步请求
6. 关闭浏览器
7. 提取 hostname → 去重 → ASCII 排序
8. 输出到终端（+ 可选写入文件）

**输出格式：**
```
Found 42 unique domains:
  a.example.com
  api.example.com
  cdn.example.com
  ...
```

**关键实现细节：**
- 使用 `page.on("request", handler)` 同步收集，用 `set` 去重
- hostname 从 `request.url` 用 `urlparse` 解析
- 过滤掉 `data:` / `blob:` / `about:` 等非 HTTP 协议
- `--include-ip` 控制是否包含纯 IP 地址（默认排除）

## Dependencies

- `playwright` — headless browser + network interception
- 标准库：`argparse`, `urllib.parse`, `time`, `sys`

## Installation & Usage

```bash
# 1. 安装依赖
pip install -r requirements.txt
playwright install chromium

# 2. 运行
python capture_domains.py https://example.com
python capture_domains.py https://example.com --wait 5 --timeout 60 --output domains.txt
python capture_domains.py https://example.com --include-ip
```

## Verification

1. 运行 `python capture_domains.py https://httpbin.org` — 应捕获少数几个域名
2. 运行 `python capture_domains.py https://www.baidu.com` — 应捕获包括 `baidu.com` 及其 CDN 子域名
3. 运行 `python capture_domains.py https://github.com` — 应捕获 `github.com`、`githubassets.com` 等
4. 验证 `--output` 参数正常输出到文件
5. 验证 `--include-ip` 能显示 IP 地址
