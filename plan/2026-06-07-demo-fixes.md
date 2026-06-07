# Demo 版修复计划: 场景选择 UI + 删除 report 文件

> **Goal:** 修复 demo 版两个问题：(1) "我来定模板"场景选择改为芯片式，级联菜单仅作选择器 (2) 删除自动做测试报告的 report/ 目录及依赖。版本号 1.1.12 → 1.1.14。

**Architecture:** 两个修改互不依赖，可并行执行。均为 demo 版修改，不影响 release 版。

**Tech Stack:** Flask + Jinja2 + vanilla JS/CSS (all_in_one)；Flask + subprocess (test_report)

---

### Task 1: 重构"我来定模板"场景选择 UI

**Files:**
- Modify: `application/all_in_one - cc/web/templates/index.html` (HTML #416-419, CSS #171-183, JS #746-799)

**设计要点 (遵循 DESIGN.md):**
- 芯片样式: `badge-pill` 组件 — bg `var(--sf-strong)` (#e6e5e0), pill 圆角, caption-uppercase 字体 (11px/600/0.88px)
- 选中芯片: bg `var(--ink)` (#26251e), 文字 `var(--cv)` (#f7f7f4)
- 级联菜单: 保持现有样式，改为 dropdown 模式

- [ ] **Step 1: 修改 HTML 结构**

将 `#tpl-cascade` 从始终展开的级联菜单改为「已选芯片 + 触发按钮 + dropdown」:

```html
<!-- 替换 lines 416-419 -->
<div class="tpl-scene-bar" id="tpl-scene-bar">
  <span class="cascade-label">已选场景</span>
  <div class="tpl-chips" id="tpl-chips"></div>
  <button class="btn btn-sm btn-s" id="tpl-cascade-trigger" onclick="toggleCascade()">+ 选择场景</button>
  <div class="cascade-dropdown" id="tpl-cascade-dropdown" style="display:none">
    <ul id="tpl-col1"></ul>
  </div>
</div>
```

- [ ] **Step 2: 修改 CSS**

替换 lines 171-183 的级联菜单样式:

```css
/* 场景选择栏 */
.tpl-scene-bar{display:flex;align-items:center;gap:8px;margin-bottom:10px;flex-wrap:wrap;position:relative}
.tpl-scene-bar .cascade-label{font-size:11px;font-weight:600;color:var(--mu);text-transform:uppercase;letter-spacing:.88px;white-space:nowrap;flex-shrink:0}
/* 已选场景芯片 */
.tpl-chips{display:flex;gap:6px;flex-wrap:wrap;flex:1}
.tpl-chip{display:inline-flex;align-items:center;gap:4px;padding:4px 10px;font-size:11px;font-weight:600;letter-spacing:.88px;text-transform:uppercase;border-radius:9999px;background:var(--sf-strong);color:var(--ink);cursor:pointer;transition:background .12s;border:none;white-space:nowrap}
.tpl-chip:hover{background:var(--hl-strong)}
.tpl-chip.active{background:var(--ink);color:var(--cv)}
.tpl-chip .chip-x{margin-left:2px;font-size:14px;line-height:1;opacity:.5;cursor:pointer}
.tpl-chip .chip-x:hover{opacity:1}
/* cascade dropdown */
.cascade-dropdown{position:absolute;top:100%;left:0;z-index:10;background:var(--sf);border:1px solid var(--hl);border-radius:var(--rm);box-shadow:0 4px 12px rgba(0,0,0,.08);padding:4px 0;min-width:200px}
.cascade-dropdown .cascade-col{list-style:none;padding:0;margin:0;min-width:170px;background:transparent;border:none;border-radius:0;overflow:visible}
.cascade-dropdown .cascade-col li{position:relative}
.cascade-dropdown .cascade-col li a{display:flex;align-items:center;justify-content:space-between;padding:7px 12px;font-size:13px;font-weight:500;color:var(--ink);text-decoration:none;cursor:pointer;white-space:nowrap;transition:background .12s}
.cascade-dropdown .cascade-col li a:hover,.cascade-dropdown .cascade-col li a.active{background:linear-gradient(135deg,rgba(245,78,0,.15),rgba(255,160,110,.06))}
.cascade-dropdown .cascade-col li a .arr{font-size:10px;color:var(--mu);margin-left:12px}
.cascade-dropdown .cascade-col .cascade-col{position:absolute;left:100%;top:0;display:none;z-index:5}
.cascade-dropdown .cascade-col li:hover>.cascade-col{display:block}
.cascade-dropdown .cascade-col li a.leaf .arr{display:none}
.cascade-dropdown .cascade-col li a.leaf:hover,.cascade-dropdown .cascade-col li a.leaf.selected{background:var(--ink);color:var(--cv)}
.cascade-dropdown .cascade-col li a.leaf.selected::before{content:'✓ ';font-size:11px}
```

移除旧的 `.cascade-menu`, `.cascade-col`, `.cascade-col li` 等样式 (lines 171-183).

- [ ] **Step 3: 修改 JS — 支持多选场景**

替换 lines 746-799 的模板编辑器 JS:

```javascript
/* Template Editor */
let _selKeys=[];  // 已选场景 key 数组 (多选)
let _ck='';        // 当前正在编辑的场景 key
let _tplTree=null;

function _renderCascadeCol(parentUl, nodes, depth){
  let ul=document.createElement('ul');ul.className='cascade-col';
  nodes.forEach(n=>{
    let li=document.createElement('li');
    let a=document.createElement('a');
    a.textContent=n.label;
    if(n.children&&n.children.length){
      a.innerHTML+= '<span class=arr>▸</span>';
      li.appendChild(a);
      _renderCascadeCol(li, n.children, depth+1);
    }else if(n.key){
      a.className='leaf';a.href='#';
      a.addEventListener('click',e=>{e.preventDefault();
        selScene(n.key);
      });
      li.appendChild(a);
    }
    ul.appendChild(li);
  });
  parentUl.appendChild(ul);
}

function selScene(key){
  if(!_selKeys.includes(key)) _selKeys.push(key);
  _ck=key;
  closeCascade();
  renderChips();
  loadSc(key);
}

function rmScene(key){
  _selKeys=_selKeys.filter(k=>k!==key);
  if(_ck===key){
    _ck=_selKeys.length?_selKeys[_selKeys.length-1]:'';
    if(_ck) loadSc(_ck); else clearEditor();
  }
  renderChips();
}

function renderChips(){
  let container=$('tpl-chips');
  container.innerHTML=_selKeys.map(k=>{
    let active=k===_ck?' active':'';
    return `<span class="tpl-chip${active}" onclick="switchScene('${k.replace(/'/g,"\\'")}')">${k}<span class="chip-x" onclick="event.stopPropagation();rmScene('${k.replace(/'/g,"\\'")}')">×</span></span>`;
  }).join('');
}

function switchScene(key){
  _ck=key;
  renderChips();
  loadSc(key);
}

function clearEditor(){
  $('tpl-header').value='';
  $('tpl-mapping').value='';
  $('tpl-template').value='';
  $('tpl-preview').value='';
  $('template-status').textContent='';
  $('tpl-init-body').innerHTML='<span style="color:var(--mu);font-size:12px">选择场景后加载初始化参数…</span>';
}

function toggleCascade(){
  let dd=$('tpl-cascade-dropdown');
  if(dd.style.display==='none'){
    dd.style.display='block';
    if(!_tplTree) ldScens();
  }else{
    closeCascade();
  }
}

function closeCascade(){
  $('tpl-cascade-dropdown').style.display='none';
}

async function ldScens(){
  if(_tplTree)return;
  try{
    let r=await fetch('/api/scenarios');let d=await r.json();
    if(d.ok&&d.tree){_tplTree=d.tree;
      let col1=$('tpl-col1');col1.innerHTML='';
      _renderCascadeCol(col1, d.tree, 0);
    }
  }catch(e){}
}

async function loadSc(key){if(!key)return;_ck=key;$('template-status').textContent='加载中…';$('template-status').className='status';try{let r=await fetch('/api/template/load',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({key})});let d=await r.json();if(d.ok){$('tpl-header').value=d.header;$('tpl-mapping').value=d.mapping;$('tpl-template').value=d.template;$('tpl-preview').value='# 请点击【预览模板】按钮生成完整预览\n';$('template-status').textContent='已切换: '+key;$('template-status').className='status status-ok'}loadInitDefaults(key)}catch(e){$('template-status').textContent='加载失败';$('template-status').className='status status-err'}}
```

保留 `loadInitDefaults`, `saveInitDefaults`, `resetInitDefaults`, `prevTpl`, `saveTpl`, `rstTpl` 函数不变（它们使用 `ck` 变量 — 改为 `_ck`）。

更新这些函数中对 `ck` 的引用为 `_ck`。

- [ ] **Step 4: 全局处理 dropdown 关闭**

```javascript
// 点击 cascade 外部时关闭 dropdown
document.addEventListener('click',e=>{
  let dd=$('tpl-cascade-dropdown');
  if(dd&&dd.style.display==='block'){
    if(!e.target.closest('#tpl-scene-bar')){
      closeCascade();
    }
  }
});
```

- [ ] **Step 5: 更新 `ck` → `_ck` 引用**

`savInitDefaults()`, `resetInitDefaults()`, `prevTpl()`, `saveTpl()`, `rstTpl()` 函数中使用 `ck` 的地方全部改为 `_ck`。

---

### Task 2: 删除测试报告 report/ 目录

**Files:**
- Modify: `application/自动做测试报告 - cc/app.py` (lines 17, 197-205)
- Delete: `application/自动做测试报告 - cc/report/` 目录

- [ ] **Step 1: 从 app.py 删除 REPORT_DIR 和相关代码**

删除 line 17:
```python
REPORT_DIR = ROOT / "report"
```

删除 lines 197-205 (report copy block):
```python
        # 复制报告到用户 report/ 文件夹
        try:
            REPORT_DIR.mkdir(parents=True, exist_ok=True)
            import shutil
            dest = REPORT_DIR / report.name
            shutil.copy2(report, dest)
            q.put(f"[OK] 报告已复制到 report/{report.name}\n")
        except Exception as e:
            q.put(f"[WARN] 复制到 report/ 失败: {e}\n")
```

- [ ] **Step 2: 删除 report/ 目录**

```powershell
Remove-Item -Recurse -Force "C:\Users\123\Desktop\帮你节省5分钟\application\自动做测试报告 - cc\report"
```

- [ ] **Step 3: 检查全局引用**

确认无其他文件引用 `REPORT_DIR` 或 `report/` 目录:
```powershell
rg "REPORT_DIR|report_dir|自动做测试报告.*report" --no-filename
```

---

### Task 3: 版本号 1.1.12 → 1.1.14

**Files:**
- Modify: `RELEASE_INFO.json`

- [ ] **Step 1: 更新版本号**

```json
{"version":"1.1.14","name":"帮你节省5分钟","built_at":"2026-06-07T00:00:00Z"}
```

---

### Task 4: Playwright 验证

- [ ] **Step 1: 启动 demo 版服务**

```powershell
# 终端 1: 启动 portal
$env:FLASK_DEBUG="1"; py application/portal/app.py

# 终端 2: 启动 all_in_one (端口 5001)
$env:FLASK_DEBUG="1"; py "application/all_in_one - cc/web/app.py"
```

- [ ] **Step 2: Playwright 验证场景选择 UI**

验证项:
1. 打开 http://localhost:5000/app/all_in_one/ → 点击"我来定模板"tab
2. 验证"已选场景"区域显示为空，"+ 选择场景"按钮可见
3. 点击"+ 选择场景"→ 级联菜单 dropdown 出现
4. 选择 "Epoch FastIP > 4.0 > HK . OpenVPN" → dropdown 关闭，芯片出现
5. 验证芯片显示场景名，可点击切换
6. 验证 textarea ①-④ 正确填充
7. 选择第二个场景 → 验证两个芯片都存在
8. 点击芯片 X → 验证删除
9. 验证"预览模板"+"保存模板"功能正常

- [ ] **Step 3: Playwright 验证测试报告无报错**

验证项:
1. 打开测试报告页面 http://localhost:5000/app/test_report/
2. 检查 console 无报错
3. 确认 report/ 目录引用已清除

---

### Task 5: 记录修改日志

- [ ] **Step 1: 写入 `log/2026-06-07.md`**

记录所有修改的文件和说明。
