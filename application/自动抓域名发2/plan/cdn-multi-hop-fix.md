# Plan: CDN Domain Detection + Collapsible Tree UI

## Context

用户要求扩展现有 Domain Capture 工具：抓取到的域名中有的指向 CDN，需要通过 DNS CNAME 解析识别 CDN 域名，并在 UI 中以可折叠/展开的树形结构展示域名与其 CDN 的关系。

## Approach

新增 DNS CNAME 解析层，在抓取完成后对每个域名查询 CNAME 记录，匹配已知 CDN 提供商列表。UI 从纯文本列表改为 `ttk.Treeview` 树形控件。

## Changes to `app.py`

### 1. 新增依赖

```python
# 新增
import dns.resolver
import dns.exception
```

`requirements.txt` / PyInstaller 需加 `dnspython` 和 `--collect-all dns`。

### 2. 新增：已知 CDN 提供商清单

常量 `CDN_PROVIDERS`：域名后缀 → 提供商名称的映射。覆盖主流 CDN：

| 域名后缀 | 提供商 |
|---|---|
| `cdn.cloudflare.net` | Cloudflare |
| `akamaiedge.net`, `akamaihd.net`, `akamai.net`, `edgesuite.net`, `edgekey.net` | Akamai |
| `fastly.net`, `global.ssl.fastly.net` | Fastly |
| `cloudfront.net` | AWS CloudFront |
| `azureedge.net`, `vo.msecnd.net` | Azure CDN |
| `kxcdn.com` | KeyCDN |
| `stackpathcdn.com` | StackPath |
| `b-cdn.net` | BunnyCDN |
| `alicdn.com`, `aliyuncs.com` | Alibaba CDN |
| `myqcloud.com` | Tencent Cloud CDN |
| `bdstatic.com` | Baidu CDN |
| `qiniucdn.com`, `clouddn.com` | Qiniu CDN |
| `jsdelivr.net` | jsDelivr |
| `cdnjs.cloudflare.com` | cdnjs |
| `googleapis.com`, `gstatic.com`, `googlehosted.com` | Google |
| `netlify.app`, `netlify.com` | Netlify |
| `vercel.app` | Vercel |
| `cdn77.com`, `cdn77.org` | CDN77 |

### 3. 新增函数

**`resolve_cname(hostname: str) -> str | None`**
- 使用 `dns.resolver.resolve(hostname, 'CNAME')` 查询 CNAME 记录
- 返回 CNAME 目标域名（去除末尾 `.`），无 CNAME 则返回 None
- DNS 查询超时 5 秒，异常时返回 None

**`check_cdn(cname_target: str) -> str | None`**
- 将 CNAME 目标域名与 `CDN_PROVIDERS` 后缀匹配
- 命中则返回提供商名称，否则返回 None

**`analyze_domains(hostnames: list[str]) -> list[dict]`**
- 对每个域名依次调用 `resolve_cname()` 和 `check_cdn()`
- 返回结构化结果列表：`[{hostname, cname, provider, is_cdn}, ...]`
- 批量 DNS 查询使用 `dns.resolver.resolve` 串行（避免并发复杂性）

### 4. UI 改动：Text → Treeview

**替换** `self.domain_text` (tk.Text) **为** `self.domain_tree` (ttk.Treeview)

Treeview 结构：
```
列: "域名" | "CNAME / CDN"
├── 🔹 www.example.com
│   └── CDN: cloudflare → cdn.cloudflare.net
├── 🔹 api.example.com
├── 🔹 cdn.example.com
│   └── CDN: akamai → e1234.akamaiedge.net
├── 🔹 fonts.googleapis.com
│   └── CDN: google → fonts.googleapis.com
```

- **顶级项**：每个捕获的域名，图标使用 Unicode 符号（🔹/•）
- **子项**：仅当 CNAME 指向已知 CDN 时才显示子节点，显示提供商名 + CNAME 目标
- **无 CDN 的域名**：作为叶子节点（无子节点），不显示展开箭头
- 所有 CDN 分组默认折叠（`open=False`）
- 点击 `[+]`/`[-]` 展开/折叠

**ttk.Style 适配 DESIGN.md：**
- `Treeview`: background=`canvas`, fieldbackground=`canvas`, foreground=`ink`
- `Treeview.Heading`: background=`surface_card`, foreground=`ink`, font=Inter bold
- `Treeview.Row`: 行高略大便于点击

### 5. 操作按钮适配

- **复制全部**：将树中所有顶级域名 + 子域名 CNAME 信息展开为文本后复制
- **导出文件**：导出为结构化文本，包含层级关系（缩进表示）
- 新增 **「全部展开」/「全部折叠」** 按钮（可选，遵循 DESIGN.md `button-tertiary-text` 样式）

### 6. 选项栏新增

在现有 Options 栏新增一个 checkbox：
- `[x] 解析 CDN` — 默认勾选，控制是否执行 DNS CNAME 解析。不勾选时行为和旧版一致（纯域名列表 + 简单展示）

### 7. 窗口尺寸调整

从 720×560 扩大到 **820×640**，以容纳 Treeview 双列布局。

## Files Changed

| File | Action |
|---|---|
| `app.py` | 修改：新增 DNS 逻辑、Treeview UI、CDN 选项、更新窗口尺寸 |
| `requirements.txt` | 新建（用于记录 dnspython 依赖） |

## Dependencies

- 新增：`dnspython>=2.0`（纯 Python，无 C 扩展，PyInstaller 友好）

## PyInstaller 打包

```
pyinstaller --onefile --windowed --name DomainCapture \
    --add-data "chromium;chromium" \
    --collect-all playwright \
    --collect-all dns \
    --hidden-import greenlet --hidden-import pyee \
    --hidden-import dns.resolver --hidden-import dns.rdtypes \
    app.py
```

## Verification

1. `python app.py` → 输入 `https://www.baidu.com` → 点击抓取 → 树形列表展示域名，CDN 域名可折叠
2. 输入 `https://github.com` → 验证 `github.githubassets.com` 等 CDN 被识别
3. 取消勾选「解析 CDN」→ 再抓取 → 仅显示纯域名列表（兼容旧行为）
4. 「复制全部」→ 粘贴验证含 CDN 信息的完整文本
5. 「导出文件」→ 验证文件内容含层级缩进
6. 重新打包 .exe → 双击运行 → 功能完整
