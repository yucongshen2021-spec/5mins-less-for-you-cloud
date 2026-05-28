const PRESETS = {
  bothwin_tfe: { user: "bothwin", password: "Tfe28@w%" },
  admin_tfe: { user: "admin", password: "Tfe28@w%" },
  bothwin_dotx12: { user: "bothwin", password: ".x12Tfe192Ti.2024" },
};

let currentTaskId = null;
let eventSource = null;
let running = false;

function $(id) { return document.getElementById(id); }

function syncProduct() {
  const isER = document.querySelector('input[name="product_type"]:checked').value === "er";
  $("ce_ping_interval_i").disabled = !isER;
  $("ce_ping_interval_m").disabled = isER;
}

function applyPreset() {
  const mode = document.querySelector('input[name="preset"]:checked').value;
  if (mode === "custom") return;
  const p = PRESETS[mode];
  if (p) {
    $("ce_user").value = p.user;
    $("ce_password").value = p.password;
  }
}

function savePreset() {
  const user = $("aaa_user").value.trim() || $("ce_user").value.trim();
  const pwd = $("aaa_password").value.trim() || $("ce_password").value;
  if (!user) { alert("aaa 用户名不能为空"); return; }
  if (!pwd) { alert("CE密码不能为空"); return; }
  $("ce_user").value = user;
  $("ce_password").value = pwd;
  alert("已保存自定义 aaa 用户名与密码");
}

function setRunning(v) {
  running = v;
  $("run-btn").disabled = v;
  $("stop-btn").disabled = !v;
  $("status").textContent = v ? "运行中..." : "就绪";
}

function clearLog() {
  $("log-output").textContent = " ";
}

function appendLog(text) {
  const el = $("log-output");
  const now = new Date();
  const ts = now.toTimeString().slice(0, 8);
  el.textContent += `[${ts}] ${text}\n`;
  el.scrollTop = el.scrollHeight;
}

function runReport() {
  if (running) { alert("任务正在执行中"); return; }

  const line_id = $("line_id").value.trim();
  const ce_host = $("ce_host").value.trim();
  const ce_user = $("ce_user").value.trim();
  const ce_password = $("ce_password").value;
  const main_ip = $("main_ip").value.trim();
  const backup_ip = $("backup_ip").value.trim();
  if (!(line_id && ce_host && ce_user && ce_password && main_ip && backup_ip)) {
    alert("CID、CE主机、CE用户名、CE密码、主线对端IP、备线IP为必填");
    return;
  }

  const productType = document.querySelector('input[name="product_type"]:checked').value;
  const body = {
    customer: $("customer").value,
    line_id,
    bandwidth: $("bandwidth").value,
    engineer: $("engineer").value,
    test_date: $("test_date").value,
    ce_host,
    ce_port: $("ce_port").value,
    ce_user,
    ce_password,
    main_ip,
    backup_ip,
    local_site: $("local_site").value,
    accel_site: $("accel_site").value,
    product_type: productType,
    ce_ping_interval_i: $("ce_ping_interval_i").value,
    ce_ping_interval_m: $("ce_ping_interval_m").value,
  };

  clearLog();
  setRunning(true);

  fetch("/api/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
    .then(r => r.json())
    .then(data => {
      if (!data.ok) { appendLog("[ERROR] " + data.error); setRunning(false); return; }
      currentTaskId = data.task_id;
      connectSSE(currentTaskId);
    })
    .catch(err => { appendLog("[ERROR] " + err); setRunning(false); });
}

function stopReport() {
  if (!currentTaskId) return;
  fetch("/api/stop", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task_id: currentTaskId }),
  }).catch(() => {});
  if (eventSource) { eventSource.close(); eventSource = null; }
  setRunning(false);
}

function connectSSE(taskId) {
  if (eventSource) { eventSource.close(); }
  eventSource = new EventSource("/api/logs/" + taskId);
  eventSource.onmessage = function (e) {
    const text = e.data;
    if (text.startsWith("__DOWNLOAD__")) {
      const relPath = text.replace("__DOWNLOAD__ ", "").trim();
      showDownload(relPath);
      return;
    }
    if (text.startsWith("__DONE__")) {
      setRunning(false);
      eventSource.close();
      eventSource = null;
      return;
    }
    appendLog(text);
    if (text.startsWith("[OK] 报告已生成") || text.startsWith("[ERROR]") || text.startsWith("[WARN] 任务已被中断")) {
      setRunning(false);
      eventSource.close();
      eventSource = null;
    }
  };
  eventSource.onerror = function () {
    if (running) { appendLog("[WARN] 日志连接断开"); }
    setRunning(false);
  };
}

function showDownload(relPath) {
  const toast = $("download-toast");
  const link = document.createElement("a");
  link.href = "/api/download/" + relPath;
  link.textContent = "下载报告: " + relPath.split("/").pop();
  link.style.cssText = "color:#fff;text-decoration:underline;";
  $("download-link-text").innerHTML = "";
  $("download-link-text").appendChild(link);
  toast.classList.remove("hidden");
  setTimeout(() => { toast.classList.add("hidden"); }, 30000);
}

function closeToast() {
  $("download-toast").classList.add("hidden");
}
