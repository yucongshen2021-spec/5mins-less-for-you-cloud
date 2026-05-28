# Network Tools — 子应用接入指南

## 1. 端口分配

每个子应用占用一个唯一端口。端口范围：**5739–5799**。

| 端口 | 应用 ID | 名称 |
|------|---------|------|
| 5741 | all_in_one | 配置生成 |
| 5740 | test_report | 测试报告 |
| 5739 | domain_capture | 域名抓取 |
| 5742 | config_analyzer | 配置梳理 |

新应用选择一个未使用的端口，确保不与现有应用冲突。

## 2. Flask 应用模板

```python
"""<应用名称> — <简要描述>"""
import sys
import os
from flask import Flask, render_template_string

app = Flask(__name__)

# 嵌入 HTML 模板 (或使用 templates/ 目录)
INDEX_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>应用名称</title>
<link rel="stylesheet" href="/static/base.css">
<style>
  /* 应用特定样式 */
</style>
</head>
<body>
  <!-- 应用内容 -->
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(INDEX_HTML)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=<PORT>, debug=False)
```

## 3. 样式要求

### 必须引用
- `framework/base.css`（或内联其 :root tokens + 字体链接）
- Google Fonts: DM Serif Display + DM Sans + JetBrains Mono

### 必须使用
- DESIGN.md 颜色 token：`var(--primary)`, `var(--ink)`, `var(--canvas)` 等
- 标准按钮类：`.btn-primary`, `.btn-secondary`（或自定义但需匹配 8px 圆角、40px 高度）
- 标准卡片类：12px 圆角、1px hairline 边框、白色背景

### 必须包含
- 页面加载入场动画 (`@keyframes cardIn`)
- 交互元素 transition（按钮、输入框 focus）
- 响应式适配（至少 640px 断点）

## 4. 注册到门户

编辑 `application/portal/process_manager.py`，在 `APPS` 列表中添加：

```python
{
    "id": "<app_id>",
    "name": "<中文名称>",
    "cwd": os.path.join(BASE, "<项目目录>"),
    "cmd": [PYTHON, "app.py"],
    "port": <PORT>,
    "url": f"http://localhost:<PORT>",
},
```

## 5. 验收清单

- [ ] 字体正确加载（DM Serif Display / DM Sans / JetBrains Mono）
- [ ] 页面加载时有 cardIn 入场动画
- [ ] 按钮样式与其他应用一致
- [ ] DESIGN.md 颜色 token 全部使用
- [ ] Ctrl+C 可正常停止，不留下僵尸进程
- [ ] 在门户 iframe 中显示正常
- [ ] 无浏览器自动弹出（设置 `BROWSER=echo`）
