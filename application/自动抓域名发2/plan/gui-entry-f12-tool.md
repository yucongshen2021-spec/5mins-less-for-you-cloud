# Plan: GUI Entry for Domain Capture Tool

## Context

用户需要一个 tkinter GUI 桌面入口程序，包装现有的 `capture_domains.py` 核心逻辑，UI 严格遵循 DESIGN.md 设计系统。

## Approach

### Architecture

```
main.py          ← 新建，GUI 入口（"exe入口文件"）
capture_domains.py ← 不变，import 其 capture_domains() 函数
```

`main.py` 通过 `from capture_domains import capture_domains` 复用现有抓取逻辑，用 `threading.Thread` 保持 UI 不冻结。

### DESIGN.md → tkinter 映射

| DESIGN Token | Value | tkinter 用途 |
|---|---|---|
| `colors.canvas` | `#f7f7f4` | 窗口背景 |
| `colors.ink` | `#26251e` | 主文字色 |
| `colors.body` | `#5a5852` | 次要文字 |
| `colors.muted` | `#807d72` | placeholder / hint |
| `colors.surface-card` | `#ffffff` | 卡片 / 输入框背景 |
| `colors.primary` | `#f54e00` | 主按钮（Cursor Orange） |
| `colors.primary-active` | `#d04200` | 按钮 hover/press |
| `colors.hairline` | `#e6e5e0` | 边框 / 分割线 |
| `colors.semantic-success` | `#1f8a65` | 成功状态 |
| `colors.semantic-error` | `#cf2d56` | 错误状态 |
| `typography.button` | 14px / 500 | CTA 按钮字体 |
| `typography.code` | 13px / JetBrains Mono | 域名列表字体（无则用 Consolas） |
| `rounded.md` | 8px | 输入框/按钮圆角 |
| `rounded.lg` | 12px | 结果卡片圆角 |
| `spacing.section` | 80px | 窗口内容区 padding |

### 窗口设计

- 窗口标题: "Domain Capture — F12 域名抓取工具"
- 窗口尺寸: 720×560，可调整大小
- 背景色: `colors.canvas` (#f7f7f4)

### 布局

```
┌─────────────────────────────────────────────┐
│  Domain Capture                             │
│  F12 网页域名抓取工具        (display / muted) │
├─────────────────────────────────────────────┤
│                                             │
│  ┌──────────────────────────────────────┐   │
│  │ 输入网页 URL                          │   │
│  │ [_____________________________] [抓取]│   │
│  └──────────────────────────────────────┘   │
│                                             │
│  Timeout: [30]s   Wait: [3]s   [ ] 包含IP  │
│                                             │
│  ┌── 结果 ── 找到 42 个域名 ──────────────┐  │
│  │                                       │  │
│  │  api.example.com                      │  │
│  │  cdn.example.com                      │  │
│  │  ...                                  │  │
│  │                                       │  │
│  └───────────────────────────────────────┘  │
│                      [导出文件] [复制全部]   │
│                                             │
│  ● 就绪 / ⟳ 正在加载...                     │
└─────────────────────────────────────────────┘
```

### 组件映射到 DESIGN 组件

| GUI 元素 | DESIGN 组件 | 参数 |
|---|---|---|
| URL 输入框 | `text-input` | bg=white, rounded=8px, h=44px |
| 「抓取」按钮 | `button-primary` | bg=#f54e00, white text, 14px/500, rounded=8px, h=40px |
| 「导出文件」按钮 | `button-secondary` | bg=white, ink text, hairline border |
| 结果区域 | `feature-card` | bg=white, rounded=12px, hairline border |
| 域名列表 | `code-block` | JetBrains Mono, 13px |
| 状态栏 | `body-sm` | 14px, body color |

### tkinter 实现技巧

- 用 `tk.Canvas` 或 `ttk.Style` 模拟 `rounded.md` (8px) 的圆角效果
- 域名列表用 `tk.Text` + 等宽字体，加 scrollbar
- 按钮用 `tk.Button` + 自定义颜色（tkinter 原生不支持 border-radius，但可通过 flat style + bg 色模拟视觉层次）
- 输入框用 `ttk.Entry` 调整样式
- 抓取操作在后台线程运行，结果通过 `after()` 回调回主线程

### 关键细节

- 窗口在屏幕居中显示
- 抓取时按钮 disabled，状态显示 "⟳ 正在抓取..."
- 结果数实时显示在卡片标题
- 「复制全部」按钮一键复制所有域名到剪贴板
- 结果卡片中的域名可选中复制
- 错误时状态栏显示红色错误信息

## Files

| File | Action |
|---|---|
| `main.py` | **新建** — GUI 入口文件 |
| `capture_domains.py` | 不变（被 import） |

## Verification

1. 运行 `python main.py`，窗口打开，背景为 cream (#f7f7f4)
2. 输入 `https://httpbin.org`，点击「抓取」，结果卡片显示 3 个域名
3. 输入无 scheme 的 URL（如 `httpbin.org`），自动补全 https
4. 点击「复制全部」→ 粘贴验证内容
5. 点击「导出文件」→ 选择路径，验证文件内容
6. 输入非法 URL，状态栏显示红色错误
7. 调整窗口大小，布局自适应
