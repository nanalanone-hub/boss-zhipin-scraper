const urlToken = (location.hash.match(/token=([^&]+)/) || [,""])[1];
if (urlToken) localStorage.setItem("boss_tool_token", urlToken);
const token = urlToken || localStorage.getItem("boss_tool_token") || "";
const headers = {"Content-Type":"application/json", "X-Boss-Tool-Token": token};
const state = {tasks: [], selectedId: "", runTimer: null, settings: {browser:"edge", cdp_port:9222, accepted_compliance:false}};
function setBrowserEnabled(enabled) { for (const id of ["browserStart","browserCheck","browserStop","runTask"]) document.getElementById(id).disabled = !enabled; }
async function loadSettings() {
  state.settings = await api("/api/settings");
  document.getElementById("browserChoice").value = state.settings.browser || "edge";
  document.getElementById("cdpPort").value = state.settings.cdp_port || 9222;
  document.getElementById("complianceModal").classList.toggle("hidden", Boolean(state.settings.accepted_compliance));
  setBrowserEnabled(Boolean(state.settings.accepted_compliance));
}
async function saveSettings(patch={}) {
  state.settings = {...state.settings, browser:document.getElementById("browserChoice").value, cdp_port:Number(document.getElementById("cdpPort").value), ...patch};
  await api("/api/settings", {method:"PUT", body:JSON.stringify(state.settings)});
}
async function api(path, options={}) {
  const response = await fetch(path, {...options, headers: {...headers, ...(options.headers||{})}});
  const text = await response.text();
  const data = text ? JSON.parse(text) : {};
  if (!response.ok) throw new Error(data.message || data.error || `HTTP ${response.status}`);
  return data;
}
function splitWords(value) { return (value || "").split(/[,，;；\n]/).map(x=>x.trim()).filter(Boolean); }
function formData() {
  const form = document.forms.taskForm;
  return {
    name: form.name.value.trim(), keyword: form.keyword.value.trim(), city: form.city.value.trim(),
    pages: Number(form.pages.value), max_details: Number(form.max_details.value),
    scale: form.scale.value.trim(), stage: form.stage.value.trim(), salary: form.salary.value.trim(),
    experience: form.experience.value.trim(), degree: form.degree.value.trim(), industry: form.industry.value.trim(),
    title_include: splitWords(form.title_include.value), title_exclude: splitWords(form.title_exclude.value),
    export_fields: splitWords(form.export_fields.value), detail_export_fields: splitWords(form.detail_export_fields.value),
    changed_policy: form.changed_policy.value, fetch_detail: form.fetch_detail.checked,
    analysis: form.analysis.checked, chinese_header: form.chinese_header.checked,
    close_chrome: form.close_chrome.checked, allow_dom_fallback: form.allow_dom_fallback.checked
  };
}
function fillForm(task={}) {
  const form = document.forms.taskForm;
  const defaults = {id:"", name:"", keyword:"", city:"上海", pages:1, max_details:2, scale:"", stage:"", salary:"", experience:"", degree:"", industry:"", title_include:"", title_exclude:"", changed_policy:"warn",
    export_fields:["title","salary","location","tags","boss_name","boss_active_status","company_scale","company_industry","skills","job_link","is_new"],
    detail_export_fields:["title","company","salary","location","skill_tags","jd","job_link"], fetch_detail:false, analysis:true, chinese_header:true, close_chrome:false, allow_dom_fallback:false};
  const merged = {...defaults, ...task, title_include:(task.title_include||[]).join(","), title_exclude:(task.title_exclude||[]).join(",")};
  for (const [key,value] of Object.entries(merged)) {
    if (form.elements[key] === undefined || !form.elements[key]) continue;
    const normalized = Array.isArray(value) ? value.join(",") : value;
    if (form.elements[key].type === "checkbox") form.elements[key].checked = Boolean(value);
    else form.elements[key].value = normalized;
  }
}
async function loadTasks() {
  const data = await api("/api/tasks"); state.tasks = data.tasks; renderTasks();
}
function renderTasks() {
  const box = document.getElementById("taskList");
  box.innerHTML = "";
  for (const task of state.tasks) {
    const div = document.createElement("div");
    div.className = "task-item" + (task.id === state.selectedId ? " active" : "");
    const title = document.createElement("strong");
    title.textContent = task.name;
    const meta = document.createElement("small");
    meta.textContent = `${task.keyword} @ ${task.city} · ${task.pages}页`;
    div.append(title, meta);
    div.onclick = () => { state.selectedId = task.id; fillForm(task); renderTasks(); };
    box.appendChild(div);
  }
}
async function saveCurrentTask() {
  const form = document.forms.taskForm;
  if (!form.reportValidity()) return false;
  const id = form.elements.id.value;
  const payload = formData();
  const saved = id ? await api(`/api/tasks/${id}`, {method:"PUT", body:JSON.stringify(payload)}) : await api("/api/tasks", {method:"POST", body:JSON.stringify(payload)});
  state.selectedId = saved.id; fillForm(saved); await loadTasks(); return true;
}
async function saveTask(event) { event.preventDefault(); await saveCurrentTask(); }
async function pollRun() {
  if (!state.selectedId) return;
  const run = await api(`/api/tasks/${state.selectedId}/run`);
  const result = run.result ? ` · 原始 ${run.result.raw_total}，新增 ${run.result.new_total}，详情 ${run.result.detail_total}${run.result.fingerprint_changed ? "，搜索条件已变化" : ""}` : "";
  document.getElementById("status").textContent = `${run.status}${run.error ? " · "+run.error : ""}${result}`;
  const newLogs = (run.logs || []).join("\n");
  if (newLogs) document.getElementById("logs").textContent = newLogs;
  if (["success","failed","cancelled"].includes(run.status)) { clearInterval(state.runTimer); state.runTimer = null; }
}
document.getElementById("newTask").onclick = () => { state.selectedId=""; fillForm(); };
document.getElementById("resetForm").onclick = () => fillForm();
document.getElementById("taskForm").onsubmit = saveTask;
document.getElementById("runTask").onclick = async () => {
  if (!await saveCurrentTask()) return;
  await api(`/api/tasks/${state.selectedId}/run`, {method:"POST"});
  if (!state.runTimer) state.runTimer = setInterval(pollRun, 1200);
};
document.getElementById("cancelTask").onclick = () => state.selectedId && api(`/api/tasks/${state.selectedId}/cancel`, {method:"POST"});
async function openResult(kind) {
  if (!state.selectedId) return alert("请先选择任务");
  try { await api(`/api/tasks/${state.selectedId}/open-result`, {method:"POST", body:JSON.stringify({kind})}); }
  catch (err) { alert(err.message); }
}
document.getElementById("openFolder").onclick = () => openResult("folder");
document.getElementById("openCsv").onclick = () => openResult("csv");
document.getElementById("openJson").onclick = () => openResult("json");
document.getElementById("openDetails").onclick = () => openResult("details");
document.getElementById("browserDetect").onclick = async () => { const d=await api("/api/browsers"); alert(JSON.stringify(d,null,2)); };
document.getElementById("browserStart").onclick = () => api("/api/browser/start",{method:"POST"});
document.getElementById("browserCheck").onclick = async () => { const r=await api("/api/browser/check",{method:"POST"}); document.getElementById("logs").textContent=r.output; };
document.getElementById("browserStop").onclick = () => api("/api/browser/stop",{method:"POST"});

for (const id of ["browserChoice", "cdpPort"]) document.getElementById(id).onchange = () => saveSettings();
document.getElementById("acceptCompliance").onclick = async () => {
  await saveSettings({accepted_compliance:true});
  await loadSettings();
};
loadSettings().then(loadTasks).catch(err => document.getElementById("status").textContent = err.message);

document.getElementById("duplicateTask").onclick = async () => {
  if (!state.selectedId) return alert("请先选择任务");
  const copied = await api(`/api/tasks/${state.selectedId}/duplicate`, {method:"POST", body:JSON.stringify({})});
  state.selectedId = copied.id; fillForm(copied); await loadTasks();
};
document.getElementById("exportTask").onclick = async () => {
  if (!state.selectedId) return alert("请先选择任务");
  const response = await fetch(`/api/tasks/${state.selectedId}/export`, {headers});
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const blob = await response.blob();
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `${state.selectedId}.json`;
  link.click();
  URL.revokeObjectURL(link.href);
};
document.getElementById("importTask").onclick = () => document.getElementById("importFile").click();
document.getElementById("importFile").onchange = async event => {
  const file = event.target.files[0];
  if (!file) return;
  const data = JSON.parse(await file.text());
  const saved = await api("/api/tasks/import", {method:"POST", body:JSON.stringify(data)});
  state.selectedId = saved.id; fillForm(saved); await loadTasks();
  event.target.value = "";
};
document.getElementById("deleteTask").onclick = async () => {
  if (!state.selectedId || !confirm("删除任务配置不会删除历史结果目录，确定继续？")) return;
  await api(`/api/tasks/${state.selectedId}`, {method:"DELETE"});
  state.selectedId = ""; fillForm(); await loadTasks();
};
