---
version: 1.0
name: all_in_one 设计规范
source_of_truth: "application/all_in_one - cc/web/templates/index.html:9-28（:root design tokens）"
description: 网络设备配置生成 Web 工具的视觉规范。基色为暖奶油画布 (#f7f7f4) 承载暖近黑墨色 (#26251e)；单一品牌电压色为橙 (#f54e00)，仅用于主 CTA、品牌点、焦点态与 active 强调。Display 用衬线体 DM Serif Display（标题/面板名），body 用 DM Sans，所有代码/数据头/配置输出用 JetBrains Mono。卡片用 1px 发丝线分隔、无投影；8px 节奏 + 12px 卡片圆角；variant 选择用 pill，操作按钮用 8px 圆角。整体是"安静的开发者工具"气质，不是 IDE 暗色也不是营销站。

colors:
  primary: "#f54e00"            # --p  主 CTA、品牌点、焦点态、active 强调
  primary-active: "#d04200"     # --pa 主 CTA hover/press
  ink: "#26251e"                 # --ink 标题、强调正文（暖近黑，非纯黑）
  body: "#5a5852"                # --body 默认正文
  muted: "#807d72"               # --mu  副标题、label
  muted-soft: "#a09c92"          # --mu-soft 禁用/最弱文本
  hairline: "#e6e5e0"            # --hl   1px 分隔线、卡片边
  hairline-soft: "#efeee8"       # --hls  更浅分隔/hover 底
  hairline-strong: "#cfcdc4"     # --hls2 输入/次按钮边、滚动条
  canvas: "#f7f7f4"              # --cv   页面底（暖奶油，非纯白）
  canvas-soft: "#fafaf7"         # --cvs 卡片头底、示例/备注底
  surface-card: "#ffffff"        # --sf   卡片/输入/按钮底（纯白，与奶油形成微对比）
  semantic-success: "#1f8a65"    # --ok  生成成功
  semantic-error: "#cf2d56"      # --er   校验/错误
  # 历史遗留的"警告/警告次按钮"色（未进 token，硬编码）：
  warning-hardcoded: "#e07b2a"   # .btn-w 警告按钮底（hover #c06a1a）

typography:
  font-display:
    fontFamily: "'DM Serif Display', Georgia, 'Times New Roman', serif"
    note: "标题/面板名/品牌名。衬线体，weight 400，负字距。非营销站的 CursorGothic。"
  font-body:
    fontFamily: "'DM Sans', system-ui, -apple-system, 'Microsoft YaHei', 'PingFang SC', sans-serif"
    note: "正文、按钮、nav、variant pill。"
  font-code:
    fontFamily: "'JetBrains Mono', 'Fira Code', monospace"
    note: "所有输入框、数据头、配置输出、代码块。约占页面一半面积。"
  font-zh:
    fontFamily: "'DM Sans','PingFang SC','Microsoft YaHei',sans-serif"
    note: "备注/示例/全屏面板/感谢榜单的中文字体栈。2026-07-20 已补齐到 :root（原为未定义缺口）。"

  display-panel-title:
    fontFamily: "{typography.font-display}"
    fontSize: 22px
    fontWeight: 400
    letterSpacing: -0.3px
  display-top-title:
    fontFamily: "{typography.font-display}"
    fontSize: 20px
    fontWeight: 400
    letterSpacing: -0.3px
  body-default:
    fontFamily: "{typography.font-body}"
    fontSize: 14px
    fontWeight: 400
    lineHeight: 1.6
  body-sm:
    fontFamily: "{typography.font-body}"
    fontSize: 13px
    fontWeight: 400
  caption:
    fontFamily: "{typography.font-body}"
    fontSize: 11px
    fontWeight: 600
    letterSpacing: 0.5px
    textTransform: uppercase
  caption-bar:
    fontFamily: "{typography.font-body}"
    fontSize: 10px
    fontWeight: 600
    letterSpacing: 0.6px-0.8px
    textTransform: uppercase
  code:
    fontFamily: "{typography.font-code}"
    fontSize: 13px
    fontWeight: 400
    lineHeight: 1.5
  button-label:
    fontFamily: "{typography.font-body}"
    fontSize: 13px
    fontWeight: 500
  button-sm:
    fontFamily: "{typography.font-body}"
    fontSize: 11px
    fontWeight: 500

rounded:
  sm: 6px     # --rs nav-tab、小图标按钮
  md: 8px     # --rm 输入框、主/次/警告按钮、cascade dropdown
  lg: 12px    # --rl 卡片
  pill: 9999px # --rp variant-pill、tpl-chip、tunnel-radio

spacing:
  xxs: 4px    # --sp-xxs
  xs: 8px     # --sp-xs  基础节奏
  sm: 12px    # --sp-sm
  md: 16px    # --sp-md
  lg: 24px    # --sp-lg
  xl: 32px    # --sp-xl
  xxl: 48px   # --sp-xxl
  note: "无 section:80px；卡片内 padding 统一 20px，header 11px 20px。"

components:
  top-bar:
    backgroundColor: "{colors.canvas}"
    border: "1px solid {colors.hairline}"
    padding: "12px 28px"
    height: auto
    textColor: "{colors.ink}"
    typography: "{typography.display-top-title}"
    note: "左：橙脉冲点 + 'all_in_one' 衬线标题 + 灰副标题。右：whatsnew 告示栏（见 whatsnew-board）。"
  whatsnew-board:
    note: "顶栏右侧（margin-left:auto）。📣 pill 按钮（12px/500 --mu 字 + --sf 底 + --hl 边 + --rp 圆角）+ 右上 8px --p 未读点（--cv 描边）。点击展开 .whatsnew-popover（320px，--sf 底 + --hl 边 + --rl 圆角 + 0 8px 24px rgba(0,0,0,.12) 投影 z200，cardIn .2s 入场），head 11px 大写灰 + ✕ 关闭，列表项 date（10px f-code --mu-soft）/title（13px/600 --ink）/desc（12px --body）。toggle/close/click-outside 关闭；localStorage(whatsnew_lastSeen) 控未读点。内容来自 data/whatsnew/updates.json，Flask index() 注入 whatsnew 上下文服务端渲染。"
  nav-bar:
    backgroundColor: "{colors.canvas}"
    border: "1px solid {colors.hairline}"
    padding: "0 28px"
    height: 42px
    position: sticky
    note: "横向 tab，可横滚。"
  nav-tab:
    padding: "6px 18px"
    rounded: "{rounded.sm}"
    fontSize: 12px
    fontWeight: 500
    color: "{colors.muted}"
    note: "hover: ink+hls 底；active: 白底+hl 边+ink 字。"
  variant-pill:
    padding: "6px 16px"
    rounded: "{rounded.pill}"
    fontSize: 12px
    fontWeight: 500
    color: "{colors.muted}"
    border: "1px solid {colors.hairline}"
    backgroundColor: "{colors.surface-card}"
    note: "variant/version/tunnel 选择。active 反相：ink 底 + cv 字。"
  card:
    backgroundColor: "{colors.surface-card}"
    border: "1px solid {colors.hairline}"
    rounded: "{rounded.lg}"
    note: "无投影。含 .card-h（头，cvs 底，10px 大写灰 label，可点折叠）+ .card-b（体，16px 20px padding）。"
  field-input:
    padding: "9px 14px"
    border: "1px solid {colors.hairline}"
    rounded: "{rounded.md}"
    fontSize: 13px
    fontFamily: "{typography.font-code}"
    color: "{colors.ink}"
    backgroundColor: "{colors.surface-card}"
    focus: "border hls2 + 3px rgba(207,205,196,.25) 光晕"
  field-textarea:
    padding: "12px 14px"
    border: "1px solid {colors.hairline}"
    rounded: "{rounded.md}"
    fontSize: 13px
    fontFamily: "{typography.font-code}"
    focus: "border 仅变 p（橙），无光晕"
    variants:
      hdr: "数据头输入，min 220px，无边撑满 card"
      code-out: "配置输出，min 380px，12px，撑满"
      ex: "填写示例，cvs 底+body 字"
      notes: "备注说明，cvs 底+body 字（原想 f-zh，未定义）"
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "#ffffff"
    typography: "{typography.button-label}"
    rounded: "{rounded.md}"
    padding: "8px 20px"
    height: 40px
    hover: "{colors.primary-active}"
  button-secondary:
    backgroundColor: "{colors.surface-card}"
    textColor: "{colors.ink}"
    border: "1px solid {colors.hairline-strong}"
    hover: "cvs 底"
  button-warning:
    backgroundColor: "#e07b2a"
    textColor: "#ffffff"
    hover: "#c06a1a"
    note: "硬编码色，未进 token。"
  button-sm:
    padding: "5px 12px"
    height: 30px
    fontSize: 11px
  toast:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.canvas}"
    rounded: "{rounded.md}"
    padding: "12px 24px"
    position: "fixed bottom 24 right 24"
    shadow: "0 4px 16px rgba(0,0,0,.15)"
    note: "唯一允许投影的元素。"
  cascade-dropdown:
    backgroundColor: "{colors.surface-card}"
    border: "1px solid {colors.hairline}"
    rounded: "{rounded.md}"
    shadow: "0 4px 12px rgba(0,0,0,.08)"
    leaf-selected: "ink 底 + cv 字 + '✓ ' 前缀"
    hover: "linear-gradient(135deg, rgba(245,78,0,.15), rgba(255,160,110,.06))"
  tpl-chip:
    padding: "4px 10px"
    rounded: "{rounded.pill}"
    fontSize: 11px
    fontWeight: 600
    letterSpacing: 0.88px
    textTransform: uppercase
    backgroundColor: "{colors.surface-card}"
    note: "active 反相 ink 底 cv 字。"
  scrollbar:
    width: 5px
    thumb: "{colors.hairline-strong}"
    note: "细滚动条，全局。"

---

## Overview

本规范以 `application/all_in_one - cc/web/templates/index.html` 的 `:root`（9–28 行）为**唯一真相来源**反向抽取。任何 UI 改动以该文件实际 token 为准；DESIGN.md 与代码冲突时，**修 DESIGN.md，不改代码**（除非有意做风格升级，需同步两边）。

这是一个**网络设备配置生成工具**的界面，不是营销站、不是 IDE 暗色主题。气质是"安静的开发者工具"：

- **暖奶油画布**（`#f7f7f4`）打底，不是纯白；墨色是暖近黑（`#26251e`），不是纯黑。
- **单一品牌电压色橙**（`#f54e00`）极克制：主 CTA、左上角脉冲点、焦点态、active 反相、cascade hover 渐变。**没有**第二品牌色。
- **衬线 display + 无衬线 body + 等宽 code 三体制**：标题用 DM Serif Display（杂志/编辑感，但通过 DM Sans body 拉回工具感），所有输入/数据头/配置输出用 JetBrains Mono。
- **发丝线分隔、无投影**（唯一例外是 toast 和 dropdown 的轻投影）。
- **8px 节奏 + 12px 卡片圆角 + pill 选择器**：卡片白底浮在奶油画布上，靠 1px hairline 和白/奶油微对比分层。

**关键特征：**
- 画布暖奶油 `#f7f7f4`，墨色暖近黑 `#26251e`，非纯黑纯白。
- 单一 CTA 色 `#f54e00`，hover `#d04200`。用得极少。
- Display 衬线（DM Serif Display），weight 400，负字距 -0.3px。
- 代码面用 JetBrains Mono，约占页面一半（输入+输出都是等宽）。
- 卡片 12px 圆角，按钮/输入 8px，选择器 pill。
- 1px hairline 分层，无投影（toast/dropdown 例外）。
- variant-pill 与 tpl-chip 的 active 态统一为**反相**（ink 底 + cv 字）。

## Colors

### Brand
- **Primary** (`--p` - #f54e00)：主 CTA、品牌脉冲点、textarea 焦点边、cascade hover 渐变、checkbox accent。用得极少。
- **Primary Active** (`--pa` - #d04200)：主 CTA hover/press。

### Surface
- **Canvas** (`--cv` - #f7f7f4)：页面底，暖奶油。
- **Canvas Soft** (`--cvs` - #fafaf7)：卡片头底、示例/备注 textarea 底。
- **Surface Card** (`--sf` - #ffffff)：卡片、输入、按钮底。纯白，与奶油形成微对比。

### Hairlines
- **Hairline** (`--hl` - #e6e5e0)：卡片边、分隔线、输入边。
- **Hairline Soft** (`--hls` - #efeee8)：hover 浅底、清除按钮栏顶边。
- **Hairline Strong** (`--hls2` - #cfcdc4)：输入焦点边、次按钮边、滚动条 thumb。

### Text
- **Ink** (`--ink` - #26251e)：标题、强调、active 反相底。
- **Body** (`--body` - #5a5852)：默认正文、示例/备注正文。
- **Muted** (`--mu` - #807d72)：副标题、label、nav-tab 默认、status。
- **Muted Soft** (`--mu-soft` - #a09c92)：最弱文本（副标题）。

### Semantic
- **Success** (`--ok` - #1f8a65)：生成成功 status。
- **Error** (`--er` - #cf2d56)：校验错误 status。

> 无时间线 pastel 色板（原 DESIGN.md 的 timeline-thinking 等 5 色在本项目不存在，已移除）。

## Typography

### Font Families（三体制）
| Token | Family | 用途 |
|---|---|---|
| `--f-display` | `'DM Serif Display', Georgia, 'Times New Roman', serif` | 标题、面板名、品牌名 |
| `--f-body` | `'DM Sans', system-ui, -apple-system, 'Microsoft YaHei', 'PingFang SC', sans-serif` | 正文、按钮、nav、pill |
| `--f-code` | `'JetBrains Mono', 'Fira Code', monospace` | 所有输入、数据头、配置输出、代码块 |

### Hierarchy
| Token | Size | Weight | Spacing | 用途 |
|---|---|---|---|---|
| panel-title | 22px | 400 | -0.3px | 面板大标题（display） |
| top-title | 20px | 400 | -0.3px | 顶栏品牌名（display） |
| body | 14px | 400 | 0 | 默认正文（line-height 1.6） |
| body-sm | 13px | 400 | 0 | 副标题、状态、小正文 |
| caption | 11px | 600 | 0.5px | field label（大写） |
| caption-bar | 10px | 600 | 0.6–0.8px | card-h / version-bar-label（大写） |
| nav-tab / pill | 12px | 500 | 0 | nav、variant、tunnel |
| button | 13px | 500 | 0 | 按钮标签 |
| button-sm | 11px | 500 | 0 | 小按钮 |
| code | 13px | 400 | 0 | 输入/输出（line-height 1.5–1.7） |

### Principles
- **Display 永远 weight 400**，负字距 -0.3px。不 bold。
- **所有输入/输出都是等宽**（JetBrains Mono），这是工具界面特征，不是营销站。
- label / card-h 一律**大写 + letter-spacing**，是"工具仪表盘"语言。

## Layout

### Spacing
8px 节奏：`--sp-xxs` 4 · `--sp-xs` 8 · `--sp-sm` 12 · `--sp-md` 16 · `--sp-lg` 24 · `--sp-xl` 32 · `--sp-xxl` 48。
- 卡片体 padding：16px 20px。
- 卡片头 padding：11px 20px。
- 顶栏/nav padding：12–0px × 28px。
- **无 80px section 节奏**（原 DESIGN.md 的 section:80px 不适用，本项目是密集工具布局）。

### Grid & Container
- 主内容 `max-width:1440px`，居中，padding 32px 28px 48px。
- 双列网格：`.info-row` / `.editor-grid` / `.out-grid` 均 `1fr 1fr`，gap 24px。
- 断点：info-row ≤900px 单列；editor-grid / out-grid ≤1000px 单列；tgrid ≤1200px 从 4 列降 2 列。
- 模板编辑器 `.tgrid`：4 列，`height: calc(100vh - 240px)`，min 420px。

### Chrome 结构
顶栏（品牌）→ nav-bar（场景 tab，sticky）→ 可选 guest-banner → main-content（各 tool-panel 切换）。tool-panel 切换有 `cardIn` 0.4s 入场动画。

## Elevation & Depth

**发丝线分层，无投影。**

| 层 | 处理 | 用途 |
|---|---|---|
| Canvas | `--cv` #f7f7f4 | 页面底、顶栏、nav |
| Card | `--sf` #ffffff | 卡片、输入、按钮 |
| Card-head | `--cvs` #fafaf7 | 卡片头、示例/备注底 |
| Hairline | 1px `--hl` | 卡片边、分隔 |
| Toast 投影 | `0 4px 16px rgba(0,0,0,.15)` | toast（唯一浮层投影） |
| Dropdown 投影 | `0 4px 12px rgba(0,0,0,.08)` | cascade-dropdown |
| Whatsnew 投影 | `0 8px 24px rgba(0,0,0,.12)` | whatsnew-popover（比 dropdown 更深的浮层） |

> 不允许给卡片/按钮加投影。浮层（toast/dropdown）的投影是物理上"浮起"的语义，才用。

## Shapes

| Token | Value | 用途 |
|---|---|---|
| `--rs` | 6px | nav-tab、小图标按钮 |
| `--rm` | 8px | 输入、主/次/警告按钮、cascade dropdown |
| `--rl` | 12px | 卡片 |
| `--rp` | 9999px | variant-pill、tpl-chip、tunnel-radio |

## Components

### 顶栏 `top-bar`
`--cv` 底 + 下边 1px `--hl`，padding 12px 28px。左：9px 橙脉冲点（2s pulse 动画）+ DM Serif 20px 'all_in_one' + 11px 灰副标题。右：whatsnew 告示栏（见下）。

### 最近更新告示栏 `whatsnew-board`
顶栏右侧（`margin-left:auto` 推到右）。📣 pill 按钮（12px/500 `--mu` 字 + `--sf` 底 + `--hl` 边 + `--rp` 圆角）+ 右上 8px `--p` 未读点（`--cv` 描边）。点击展开 `.whatsnew-popover`：320px、`--sf` 底 + `--hl` 边 + `--rl` 圆角 + `0 8px 24px rgba(0,0,0,.12)` 投影 z200、`cardIn .2s` 入场；head 11px 大写灰 label + ✕ 关闭；列表项 date（10px `--f-code` `--mu-soft`）/ title（13px/600 `--ink`）/ desc（12px `--body`）。`toggle/close/click-outside` 关闭；`localStorage('whatsnew_lastSeen')` 控未读点。内容来自 `data/whatsnew/updates.json`，Flask `index()` 注入 `whatsnew` 上下文服务端渲染（无 JS 拉取）。

### 导航 `nav-bar` / `nav-tab`
`--cv` 底，sticky top:0，高 42px，z 100。tab 12px/500，默认 `--mu`，hover ink+`--hls` 底，active 白底+`--hl` 边+ink 字。可横滚。

### 选择器 `variant-pill` / `tpl-chip` / `tunnel-radio`
均为 pill，默认 `--mu` 字 + 白底 + `--hl` 边。**active 统一反相**：`--ink` 底 + `--cv` 字。tpl-chip 更小（11px/600/0.88px/大写）。version-bar-label 是 10px 大写灰 label。

### 卡片 `card`
白底 + 1px `--hl` + 12px 圆角，无投影。`.card-h` 头：`--cvs` 底，10px 大写灰 label，可点折叠（▼ 箭头旋转）。`.card-b` 体：16px 20px，有 `.p0`（padding:0，用于撑满的 textarea）和 `.coll`（折叠隐藏）变体。

### 表单 `field`
- `.fi` / `.fs`：9px 14px，13px 等宽，8px 圆角，`--hl` 边。焦点：边变 `--hls2` + 3px rgba(207,205,196,.25) 光晕。
- `.ft` textarea：12px 14px，等宽，焦点边变橙 `--p`（无光晕）。变体：`.hdr`（数据头，撑满）、`.code-out`（输出，380px）、`.ex`（示例，cvs 底）、`.notes`（备注，cvs 底）。
- label `.fl`：11px/600/0.5px 大写灰。
- `.fr2`：两列等宽 grid，gap 12px。
- `.cb`：checkbox，`accent-color: var(--p)`。

### 按钮 `btn`
40px 高，13px/500，8px 圆角。
- `.btn-p`：橙底白字，hover `--pa`。
- `.btn-s`：白底 ink 字 + `--hls2` 边，hover cvs 底。
- `.btn-w`：`#e07b2a` 底白字（硬编码，未进 token），hover `#c06a1a`。
- `.btn-sm`：30px 高，11px。
- `.status`：12px `--mu`，`.status-err` 用 `--er`，`.status-ok` 用 `--ok`。

### Toast
`--ink` 底 + `--cv` 字，8px 圆角，fixed bottom 24 right 24，`0 4px 16px rgba(0,0,0,.15)` 投影。`.show` 显隐 + translateY。

### Cascade Dropdown（模板编辑器级联）
白底 + `--hl` 边 + 8px 圆角 + 轻投影。leaf 选中：ink 底 cv 字 + '✓ ' 前缀。hover：橙渐变 `linear-gradient(135deg, rgba(245,78,0,.15), rgba(255,160,110,.06))`。

### Scrollbar
5px 宽，thumb `--hls2`，3px 圆角，track 透明。

## Do's and Don'ts

### Do
- 新增组件**先用现有 token**（`--p/--ink/--cv/--sf/--hl` 等），不内联 hex。
- 选择器 active 态一律**反相**（ink 底 cv 字），保持一致。
- 输入/输出**必须等宽**（JetBrains Mono），这是工具界面特征。
- 卡片用 12px 圆角，按钮/输入 8px，pill 选择器 9999px。
- 焦点态：输入用 `--hls2` 边 + 浅灰光晕；textarea 用 `--p` 边（仅边）。
- label / card-h 用大写 + letter-spacing，仪表盘语言。

### Don't
- 不引入第二品牌色。橙是唯一 CTA 色（警告按钮 `#e07b2a` 是历史遗留，新场景不要再用，改用次按钮）。
- 不给卡片/按钮加投影。只有浮层（toast/dropdown）可以。
- 不用纯白 `#fff` 做页面底（用 `--cv` 奶油）。
- 不用纯黑 `#000` 做文本（用 `--ink` 暖近黑）。
- 不把 display 字体改无衬线（DM Serif Display 是本工具的辨识度之一）。
- 不在工具界面引入营销组件（hero-band / pricing / testimonial / timeline pill 等已移除）。

## Responsive Behavior

| 断点 | 触发 | 变化 |
|---|---|---|
| ≤1200px | tgrid | 4 列 → 2 列 |
| ≤1000px | editor-grid / out-grid | 2 列 → 1 列 |
| ≤900px | info-row | 2 列 → 1 列 |

nav-bar 可横滚（不折叠 hamburger）。主内容 max-width 1440px。

## 已知缺口与待统一项（重要）

> 以下是从代码反向抽取时发现的**实际存在的问题**，记录在此供后续统一。DESIGN.md 不替代码做决定（Rule 1），只如实标注。

### 1. all_in_one `:root` 中被引用但未定义的变量（已于 2026-07-20 补齐 ✓）
| 变量 | 引用处 | 现状 |
|---|---|---|
| `--f-zh` | `.ft.notes` / `.sel .fs` / `.fs-btn` / 感谢榜单 | ✓ 已补：`'DM Sans','PingFang SC','Microsoft YaHei',sans-serif` |
| `--sf-strong` | `.tpl-chip` background | ✓ 已补：`#ffffff`（= `--sf`） |
| `--hl-strong` | `.tpl-chip:hover` background | ✓ 已补：`#cfcdc4`（= `--hls2`） |
| `--bd` | guest-banner / tpl-admin-banner border | ✓ 已补：`#e6e5e0`（= `--hl`） |
| `--primary` | guest-banner / tpl-admin-banner 登录链接色 | ✓ 已补：`#f54e00`（= `--p`） |

已补齐到 `index.html:9-28` 的 `:root` 末尾「semantic aliases」段。全文件引用 33 个 `--var`、定义 33 个，无遗留未定义变量。

### 2. 警告按钮 `#e07b2a` 未进 token
`.btn-w` 硬编码 `#e07b2a` / `#c06a1a`，不在 `:root`。建议要么进 token（`--warn` / `--warn-active`），要么新场景改用次按钮。

### 3. 仓库内存在三套不同源的 UI（统一方向：以 all_in_one 为准）
| 面 | 位置 | 字体 | 主色 | token 命名 | 与主线差异 |
|---|---|---|---|---|---|
| **all_in_one（主线/真相）** | `application/all_in_one - cc/web/templates/index.html` | DM Serif + DM Sans + JetBrains Mono | #f54e00 | 短名 `--p/--cv/--ink` | — |
| portal index | `application/portal/templates/index.html` | Inter | #f54e00 | 长名 `--primary/--canvas/--ink` | token 名不一致，字体不同 |
| portal login | `application/portal/templates/login.html` | 系统字体 | **#4a90d9 蓝** | 无 :root，全内联 | 主色完全是另一套蓝 |

**统一方向**（待你定夺）：portal 两套逐步迁到 all_in_one 的 token 名 + 字体 + 主色。login 的蓝 `#4a90d9` 是最大的偏离，建议优先处理。本次只规范 DESIGN.md，不动 portal 代码。

### 4. whatsnew-popover 投影未进 token
`.whatsnew-popover` 硬编码 `0 8px 24px rgba(0,0,0,.12)`（`index.html` whatsnew CSS），是继 toast（`0 4px 16px`）、dropdown（`0 4px 12px`）之后的第三个浮层投影值。建议引入 `--shadow-popover` token 统一，或与 dropdown 合并。当前可用，仅作待统一记录。

## Iteration Guide

1. 改 UI 前先读 `index.html:9-28` 的 `:root`，用现有 token。
2. 新组件的 active 态默认反相（ink 底 cv 字）。
3. 输入/输出必等宽；label 必大写。
4. 卡片 12px、按钮 8px、选择器 pill，不混用。
5. 颜色不内联 hex，从 token 取；token 不够先补 token 再用。
6. 改完同步更新本 DESIGN.md 的对应组件条目（Rule 2）。
7. 发现"引用了未定义变量"立刻在「已知缺口」段补一条，并优先修代码而非 DESIGN.md。

## 变更记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-07-20 | 1.0 | 以 `all_in_one - cc/web/templates/index.html:9-28` 为真相来源反向重写：字体改 DM Serif Display/DM Sans/JetBrains Mono（原 CursorGothic 不适用）；组件清单替换为项目实际组件（top-bar/nav-tab/variant-pill/card/field/btn/toast/cascade-dropdown 等）；移除营销组件（hero-band/pricing/testimonial）与 timeline pastel 5 色；如实记录 5 个未定义变量与三套 UI 差异为「已知缺口」。 |
| 2026-07-20 | 1.1 | 「已知缺口 #1」已修复：在 `index.html:9-28` 的 `:root` 末尾补齐 5 个语义别名变量（`--primary/--bd/--sf-strong/--hl-strong/--f-zh`），全文件引用与定义均为 33 个、无遗留；DESIGN.md 同步标注为 ✓ 已补。 |
| 2026-07-21 | 1.2 | 新增 `whatsnew-board` 组件文档（顶栏右侧 📣 告示栏 + popover + 未读点 + localStorage）；`top-bar` note 补右侧；Elevation 表加 Whatsnew 投影行；「已知缺口 #4」记录 whatsnew-popover 投影未进 token。 |
| 2026-07-24 | 1.3 | 新增独立应用 `usg_virus_test`（USG 测病毒指引页，`application/usg_virus_test/`）：全量复用 all_in_one token（`--cv` 奶油底 / `--ink` 墨色 / `--p` 橙唯一 CTA / DM Serif Display + DM Sans + JetBrains Mono / 12px 卡片发丝线无投影），与主线视觉同源，未引入新色新字体，作为「统一方向」的首个合规新应用样本。 |
| (原 alpha) | alpha | 原始版本（Cursor 营销站设计，与本项目实际 UI 不符，已废弃）。 |
