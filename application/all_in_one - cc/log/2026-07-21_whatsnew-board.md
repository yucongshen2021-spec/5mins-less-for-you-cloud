## 2026-07-21

### 新增「最近更新告示栏」UI

顶栏右上角加 📣 告示栏，点击展开最近更新列表；内容来自 JSON 文件、服务端渲染，无前端拉取。

- 文件: `web/templates/index.html`（编辑）
  - 说明: ①顶栏 `.top-bar`（L231）右侧加 `.whatsnew-wrap`（`margin-left:auto` 推到右）—— 📣 pill 按钮 + 右上 8px `--p` 未读小点（`--cv` 描边）+ `.whatsnew-popover`（320px，`--sf` 底 + `--hl` 边 + `--rl` 圆角 + `0 8px 24px rgba(0,0,0,.12)` 投影 z200，`cardIn .2s` 入场），head 11px 大写灰 + ✕ 关闭，列表项 date/title/desc 用 Jinja `{% for item in whatsnew %}` 服务端渲染；②CSS（L48-66）全用现有 token，复用 `cardIn` 关键帧；③JS（`WHATSNEW` 常量 L551 + L1187-1210）`toggleWhatsnew`/`closeWhatsnew`/click-outside 关闭 + `localStorage('whatsnew_lastSeen')` 控未读点（对比最新条目 id）。
  - 为什么: 之前发新功能无统一公示入口；放顶栏右上角常驻、点击展开不占横向空间，符合「浮层才投影」的设计约束（DESIGN.md）。
- 文件: `web/app.py`（编辑，`index()` L731-744）
  - 说明: 读取 `data/whatsnew/updates.json`（镜像感谢榜单 `/api/sponsor-board` 的 `json.loads(read_text(encoding='utf-8-sig'))` + 缺失/异常降级 `[]`），作为 `whatsnew` 上下文变量传入 `render_template`，Jinja 服务端渲染。无新增 API、无前端 fetch。
  - 为什么: 服务端渲染无加载闪烁；JSON 与模板分离，发新功能只改数据文件。
- 文件: `data/whatsnew/updates.json`（新建）
  - 说明: schema `{updates:[{id,date,title,desc}]}`，初版 3 条真实 changelog（ER 新增单出口配置 / 修改 ER 飞连匹配格式 / 修复 ER MPLS 海外 bug，对应提交 3cc4054+8af68c0、e9c9ca6、b4fbab9）。
- 验证: Flask test_client `GET /` 200 含 whatsnew markup；JSON 缺失降级显示「暂无更新」+ 200；`docker-compose up -d --build` 重建并注入 JSON 到命名卷后，线上 `http://localhost:5000/app/all_in_one/` 200 含 3 条更新 + `WHATSNEW` 常量（Python 字符串校验，因本机 `grep` 别名 `-E` 与 `-F` 冲突误报）。

### 部署注意（命名卷 + 热重载失效）
- `data/` 在 docker-compose 是命名卷 `portal-data`（非 bind mount），源码是镜像内烘（`COPY . .`）。故改 `app.py`/`index.html` 需 `docker-compose up -d --build`；改 `data/whatsnew/updates.json` 后还需 `docker exec` 注入到容器内 `/app/.../data/whatsnew/`（卷会覆盖镜像内 data，单纯重建不会带入新数据文件）。
- 已知小坑：`web/app.py:3042` `check_and_reload_runtime` 调用未定义的 `_reload_workspace_templates_safe`（应为 `_load_workspace_templates`，L2684），`NameError` 被 `except Exception: pass` 静默吞掉 → 热重载实际是 no-op。故业务模块/路由改动靠 worker 重启或镜像重建生效，不能靠 `touch data/.reload_stamp`。模板靠 `TEMPLATES_AUTO_RELOAD=True` + 重建生效。
