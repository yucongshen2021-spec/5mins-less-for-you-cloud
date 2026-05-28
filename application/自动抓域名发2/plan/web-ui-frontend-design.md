# Plan: Web UI with frontend-design

## Context

将 tkinter GUI 替换为 Flask + Web 前端，利用 frontend-design skill 打造具有设计感、独特视觉风格的界面。后端逻辑（Playwright 抓取 + DNS CNAME 链追踪）保持不变。

## Architecture

```
app.py  ← 单文件：Flask server + API + 业务逻辑 + HTML模板
         ├── 后端: capture_domains(), analyze_domains()
         ├── Flask: / (主页), /api/capture (POST)
         └── HTML/CSS/JS inline (Jinja2 template)
```

启动流程：`python app.py` → Flask 启动 → 自动打开浏览器 → 显示 Web UI

## Design Direction

**Tone**: Editorial luxury meets developer tooling
- Warm cream canvas + ink typography
- Cursor Orange as single voltage accent
- Hairline borders, no shadows (per DESIGN.md)
- Magazine-editorial whitespace rhythm

**Typography**:
- Display: "DM Serif Display" (editorial, distinctive — 替代 Inter)
- Body: "DM Sans" (clean, refined)
- Code: "JetBrains Mono" (per DESIGN.md)

**Color** (DESIGN.md):
- Canvas: `#f7f7f4`
- Ink: `#26251e`
- Body text: `#5a5852`
- Primary: `#f54e00` (Cursor Orange — CTA only)
- Hairline: `#e6e5e0`
- Surface card: `#ffffff`

**Motion**:
- Cards fade in with staggered delay on page load
- Domain tree items expand/collapse with height transition
- 「抓取」button shows spinner animation during loading
- Results counter animates on update

**Spatial**:
- Centered layout, max-width 780px
- 80px section rhythm (per DESIGN.md)
- Cards: white on cream, 1px hairline border

## API Design

### `POST /api/capture`
Request: `{url, timeout, wait, include_ip, resolve_cdn}`
Response: `{domains_count, cdn_count, results: [{hostname, cname_chain, providers, is_cdn}]}`

同步处理（抓取 + DNS 解析），前端显示加载动画。

## Components

1. **Header**: Logo/title area, subdued description
2. **Input Card**: URL field + 抓取 button + options row
3. **Results Card**: Domain tree with expand/collapse, CDN badges
4. **Action Bar**: Copy + Export buttons
5. **Status Bar**: Loading/success/error states
6. **Footer**: Subtle branding

## Files Changed

| File | Action |
|---|---|
| `app.py` | 重写：Flask + API + HTML template inline |
| `requirements.txt` | 新增 flask |

## Packaging

```
pyinstaller --onefile --windowed --name DomainCapture
    --add-data "chromium;chromium"
    --add-data "templates;templates"  (if using separate template)
    --collect-all playwright
    --collect-all dns
    --collect-all flask
    --hidden-import ...
    app.py
```
