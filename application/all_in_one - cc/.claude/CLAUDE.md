# all_in_one 项目规则

## 规则 1：跨场景一致性检查

每次修复一个 bug 或修改一个场景的逻辑后，必须检查所有其他场景是否存在同类问题。



## 项目结构

```
all_in_one/
├── web/                     Web 应用（Flask + SPA 前端）
│   ├── app.py               Flask 后端，端口 5741
│   └── templates/index.html 前端页面
├── src/                     业务逻辑源码
│   ├── all_in_one_v2.py     主程序（SCENARIOS、VisualEditorTab、模板常量）
│   ├── er_fastip_2in1_v8.py Epoch FastIP（HK/US/飞连/新增出口/域名分流）
│   ├── usg_fastip_3in1_v5.py USG FastIP（非HK/HK/飞连/新增出口）
│   ├── er_mpls_v1.py        Epoch MPLS（国内/海外/IPSEC）
│   ├── ar_sdwan_zihuan_v4.py AR SD-WAN（单机/双机 OPS+Factory）
│   ├── shared_utils.py      共享工具（re_get、wanip_hosts、widget_get/set_value）
│   ├── field_coverage.py    字段覆盖检查
│   └── user_activity_log.py 用户活动记录
├── test/
│   └── run_all.py           全场景自动化测试（Flask test client）
├── data/
│   ├── editor_workspace/    用户自定义模板
│   ├── editor_defaults/     出厂默认模板
│   └── user_init_placeholders.json
├── README.md                用户说明
├── DESIGN.md                设计规范（Cursor 设计系统）
└── log/                     修改日志
```

## 架构关键点

- Web 后端用 `exec()` 加载 4 个工具模块（与 tkinter 桌面版相同的预处理机制）
- `_load_module()` 替换 `root = tk.Tk()` → `__WEB_FRAME__`，删除 `root.mainloop()`
- 模块函数通过 namespace dict 访问（`ns.get("build_epoch_hk_format_dict")`）
- Flask 使用 `threaded=False` 确保 tkinter 在主线程运行
- 网络参数通过 `_inject_network_to_module()` 写入模块 `globals()` + `_clear_entry_widgets()` 清除 Entry 控件

## 20 个场景

Epoch FastIP: HK, US, Flink, New Exit, Domain Split
USG FastIP: US, HK, Flink, New Exit  
Epoch MPLS: Domestic, Overseas, IPSec
AR SD-WAN: Single OPS/Factory, Single DualWAN OPS/Factory, Dual Pri/Bak OPS/Factory

## API 端点

- `POST /api/generate/<tool>` — 生成配置
- `GET /api/examples/<tool>/<variant>` — 示例数据
- `GET /api/notes/<tool>?variant=` — 备注说明
- `GET /api/scenarios` — 场景列表
- `POST /api/template/load|save|reset` — 模板编辑器
- `POST /api/template/preview` — 模板预览

