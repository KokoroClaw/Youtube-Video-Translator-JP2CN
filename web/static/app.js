const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const state = {
  jobId: null,
  job: null,
  pollTimer: null,
  terms: [],
  biliup: null,
  biliCategories: [],
  defaultTid: 158,
  editor: {
    document: null,
    loadedJobId: null,
    selectedId: null,
    previewMode: "dual",
    undo: [],
    redo: [],
    savedContent: "",
    pendingSnapshot: null,
    exactUrl: null,
  },
};

async function api(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    let message = `请求失败 (${response.status})`;
    try { message = (await response.json()).detail || message; } catch (_) {}
    throw new Error(message);
  }
  return response.status === 204 ? null : response.json();
}

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
}

function switchView(name) {
  $$(".tab").forEach(button => button.classList.toggle("active", button.dataset.view === name));
  $$(".view").forEach(view => view.classList.remove("active"));
  $(`#${name}View`).classList.add("active");
  if (name === "editor" && state.jobId && state.job?.status === "completed") {
    loadEditor().catch(error => { $("#editorError").textContent = error.message; });
  }
}

async function checkHealth() {
  const status = $("#systemStatus");
  try {
    const health = await api("/api/health");
    status.className = `system-status ${health.openai_configured ? "ready" : "error"}`;
    status.lastElementChild.textContent = health.openai_configured
      ? `${health.transcription_model} · ${health.translation_model}`
      : "OpenAI API Key 未配置";
  } catch (error) {
    status.className = "system-status error";
    status.lastElementChild.textContent = "服务连接失败";
  }
}

function setJobRunning(running) {
  $("#startButton").disabled = running;
  $("#videoUrl").disabled = running;
  $("#startButton span").textContent = running ? "任务处理中…" : "开始生成字幕";
}

function renderJob(job) {
  state.job = job;
  const progress = Math.max(0, Math.min(100, job.progress || 0));
  $("#progressRing").style.setProperty("--progress", progress);
  $("#progressValue").textContent = progress;
  $("#stageText").textContent = job.stage;
  $("#messageText").textContent = job.message;
  const badge = $("#jobState");
  badge.className = `job-state ${job.status}`;
  badge.textContent = ({ queued: "已进入队列", running: "正在处理", completed: "已完成", failed: "处理失败" })[job.status] || job.status;

  $$("#milestones li").forEach(item => item.classList.toggle("done", progress >= Number(item.dataset.at)));
  const logBox = $("#logBox");
  logBox.replaceChildren();
  (job.logs.length ? job.logs : [{ stage: "系统", message: "等待任务开始…" }]).forEach(log => {
    const line = document.createElement("p");
    line.textContent = `[${log.stage}] ${log.message}`;
    logBox.append(line);
  });
  logBox.scrollTop = logBox.scrollHeight;

  if (job.status === "completed") {
    setJobRunning(false);
    renderResults(job.files);
    renderPostProcessing(job);
    if (state.editor.loadedJobId !== job.id) $("#editorCueCount").textContent = "…";
  } else if (job.status === "failed") {
    setJobRunning(false);
    $("#formError").textContent = job.error || "任务处理失败";
  }
  if (state.editor.loadedJobId === job.id && state.editor.document) {
    state.editor.document.operation_active = operationIsActive(job);
    updateEditorSaveState();
  }
}

function populateBiliTid(categoryId, preferredTid = null) {
  const category = state.biliCategories.find(item => item.id === Number(categoryId));
  const tidSelect = $("#biliTid");
  tidSelect.replaceChildren();
  if (!category) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "暂无可用分区";
    tidSelect.append(option);
    $("#biliTidValue").textContent = "--";
    return;
  }

  const options = [
    { id: category.id, name: `${category.name}（大区）` },
    ...category.children,
  ];
  options.forEach(item => {
    const option = document.createElement("option");
    option.value = String(item.id);
    option.textContent = item.name;
    tidSelect.append(option);
  });
  const target = options.some(item => item.id === Number(preferredTid))
    ? Number(preferredTid)
    : (category.children[0]?.id || category.id);
  tidSelect.value = String(target);
  $("#biliTidValue").textContent = String(target);
}

function selectBiliTid(tid) {
  const numericTid = Number(tid);
  const category = state.biliCategories.find(item =>
    item.id === numericTid || item.children.some(child => child.id === numericTid)
  );
  if (!category) return;
  $("#biliCategory").value = String(category.id);
  populateBiliTid(category.id, numericTid);
}

async function loadBilibiliCategories() {
  try {
    const data = await api("/api/bilibili/categories");
    state.biliCategories = data.categories || [];
    state.defaultTid = Number(data.default_tid || 158);
    const categorySelect = $("#biliCategory");
    categorySelect.replaceChildren();
    state.biliCategories.forEach(category => {
      const option = document.createElement("option");
      option.value = String(category.id);
      option.textContent = category.name;
      categorySelect.append(option);
    });
    const savedTid = state.job?.upload?.request?.tid;
    selectBiliTid(savedTid || state.defaultTid);
  } catch (error) {
    $("#uploadError").textContent = `分区表加载失败：${error.message}`;
  }
}

function operationIsActive(job) {
  return [job.burn?.status, job.upload?.status].some(status => ["queued", "running"].includes(status));
}

function ensurePolling() {
  if (!state.pollTimer) state.pollTimer = setInterval(pollJob, 1000);
}

function renderResults(files) {
  const panel = $("#resultsPanel");
  const grid = $("#resultGrid");
  grid.replaceChildren();
  files.forEach(file => {
    const extension = file.name.split(".").pop().toUpperCase();
    const link = document.createElement("a");
    link.className = "result-card";
    link.href = file.url;
    link.download = file.name;
    const icon = document.createElement("span");
    icon.className = "file-icon";
    icon.textContent = extension;
    const copy = document.createElement("div");
    const name = document.createElement("strong");
    name.textContent = file.name;
    const size = document.createElement("small");
    size.textContent = `${formatSize(file.size)} · 点击下载`;
    copy.append(name, size);
    link.append(icon, copy);
    grid.append(link);
  });
  panel.classList.remove("hidden");
}

function renderPostProcessing(job) {
  $("#postPanel").classList.remove("hidden");
  const burn = job.burn;
  const burnStatus = $("#burnStatus");
  burnStatus.className = `operation-status ${burn?.status || "idle"}`;
  $("p", burnStatus).textContent = burn?.message || "准备就绪";
  $("strong", burnStatus).textContent = `${burn?.progress || 0}%`;
  $("#burnButton").disabled = ["queued", "running"].includes(burn?.status);
  $("#burnError").textContent = burn?.error || "";

  const videoSelect = $("#uploadVideo");
  const previousSelection = videoSelect.value;
  videoSelect.replaceChildren();
  const videos = job.files.filter(file => file.name.toLowerCase().endsWith(".mp4"));
  videos.sort((a, b) => Number(b.name.includes("_hardsub_")) - Number(a.name.includes("_hardsub_")));
  videos.forEach(file => {
    const option = document.createElement("option");
    option.value = file.name;
    option.textContent = file.name.includes("_hardsub_") ? `硬字幕 · ${file.name}` : `原视频 · ${file.name}`;
    videoSelect.append(option);
  });
  if (videos.some(file => file.name === previousSelection)) videoSelect.value = previousSelection;

  if (!$("#uploadForm").dataset.initialized) {
    const fallbackTitle = videos[0]?.name.replace(/_(?:video|hardsub_(?:zh|dual))\.mp4$/i, "") || "";
    $("#biliTitle").value = (job.title || fallbackTitle).slice(0, 80);
    $("#biliDescription").value = "";
    $("#biliSource").value = job.source_url || "";
    if (state.biliCategories.length) {
      selectBiliTid(job.upload?.request?.tid || state.defaultTid);
    }
    $("#uploadForm").dataset.initialized = "true";
  }
  if (job.source_url && !$("#biliSource").value.trim()) {
    $("#biliSource").value = job.source_url;
  }

  const upload = job.upload;
  $("#uploadButton").disabled = ["queued", "running"].includes(upload?.status) || !state.biliup?.logged_in;
  $("#uploadError").textContent = upload?.error || "";
  const uploadLog = $("#uploadLog");
  if (upload?.logs?.length) {
    uploadLog.classList.remove("hidden");
    uploadLog.textContent = upload.logs.join("\n");
    uploadLog.scrollTop = uploadLog.scrollHeight;
  }
  if (upload?.status === "completed") {
    const result = upload.bvid ? `投稿成功：${upload.bvid}` : "投稿已提交，请到创作中心查看审核状态";
    $("#uploadError").textContent = result;
  } else if (upload?.status === "stale") {
    const history = upload.bvid ? `（历史稿件 ${upload.bvid}）` : "";
    $("#uploadError").textContent = `${upload.message}${history}`;
  }
}

async function pollJob() {
  if (!state.jobId) return;
  try {
    const job = await api(`/api/jobs/${state.jobId}`);
    renderJob(job);
    if (["completed", "failed"].includes(job.status) && !operationIsActive(job)) {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
    }
  } catch (error) {
    $("#formError").textContent = error.message;
    setJobRunning(false);
    clearInterval(state.pollTimer);
  }
}

async function restoreLatestJob() {
  try {
    const job = await api("/api/jobs/latest");
    if (!job) return;
    state.jobId = job.id;
    renderJob(job);
    if (["queued", "running"].includes(job.status) || operationIsActive(job)) {
      setJobRunning(true);
      state.pollTimer = setInterval(pollJob, 1000);
    }
  } catch (_) {}
}

async function submitBurn(event) {
  event.preventDefault();
  if (!state.jobId) return;
  $("#burnError").textContent = "";
  const subtitleType = new FormData(event.currentTarget).get("subtitle_type");
  try {
    const job = await api(`/api/jobs/${state.jobId}/burn`, {
      method: "POST",
      body: JSON.stringify({ subtitle_type: subtitleType }),
    });
    renderJob(job);
    ensurePolling();
  } catch (error) { $("#burnError").textContent = error.message; }
}

async function loadBiliupStatus() {
  try {
    state.biliup = await api("/api/bilibili/status");
    const strip = $("#biliLoginText");
    const button = $("#biliLoginButton");
    if (!state.biliup.installed) {
      strip.textContent = "未检测到 biliup";
      button.textContent = "查看安装说明";
    } else if (!state.biliup.logged_in) {
      strip.textContent = "biliup 已安装 · 尚未登录";
      button.textContent = "扫码登录";
    } else {
      strip.textContent = "B 站账号已登录";
      strip.parentElement.parentElement.classList.add("ready");
      button.textContent = "重新登录";
    }
    if (state.jobId) {
      const job = await api(`/api/jobs/${state.jobId}`);
      renderPostProcessing(job);
    }
  } catch (error) { $("#biliLoginText").textContent = error.message; }
}

async function launchBiliupLogin() {
  if (!state.biliup?.installed) {
    $("#uploadError").textContent = "请先安装 biliup 并设置 BILIUP_PATH；安装说明已写入 README_zh.md";
    return;
  }
  try {
    await api("/api/bilibili/login", { method: "POST", body: "{}" });
    $("#uploadError").textContent = "扫码窗口已打开；页面会自动检查登录状态";
    [3000, 8000, 15000, 30000].forEach(delay => setTimeout(loadBiliupStatus, delay));
  } catch (error) { $("#uploadError").textContent = error.message; }
}

async function submitUpload(event) {
  event.preventDefault();
  if (!state.jobId) return;
  $("#uploadError").textContent = "";
  const copyright = Number($("#biliCopyright").value);
  const payload = {
    video_name: $("#uploadVideo").value,
    title: $("#biliTitle").value.trim(),
    description: $("#biliDescription").value.trim(),
    tags: $("#biliTags").value.trim(),
    tid: Number($("#biliTid").value),
    copyright,
    source: copyright === 2 ? $("#biliSource").value.trim() : "",
    use_thumbnail: $("#useThumbnail").checked,
    confirm_publish: $("#confirmPublish").checked,
  };
  try {
    const job = await api(`/api/jobs/${state.jobId}/upload`, {
      method: "POST", body: JSON.stringify(payload),
    });
    renderJob(job);
    ensurePolling();
  } catch (error) { $("#uploadError").textContent = error.message; }
}

async function submitJob(event) {
  event.preventDefault();
  $("#formError").textContent = "";
  $("#resultsPanel").classList.add("hidden");
  $("#postPanel").classList.add("hidden");
  delete $("#uploadForm").dataset.initialized;
  resetEditor();
  const form = event.currentTarget;
  const payload = {
    url: $("#videoUrl").value.trim(),
    download_video: form.elements.download_video.checked,
    download_thumbnail: form.elements.download_thumbnail.checked,
    use_separator: form.elements.use_separator.checked,
    initial_prompt: $("#initialPrompt").value.trim(),
    auto_split_subtitles: $("#autoSplitSubtitles").checked,
    subtitle_density: $("#subtitleDensity").value,
    subtitle_max_lines: Number($("#subtitleMaxLines").value),
  };
  try {
    setJobRunning(true);
    const job = await api("/api/jobs", { method: "POST", body: JSON.stringify(payload) });
    state.jobId = job.id;
    renderJob(job);
    state.pollTimer = setInterval(pollJob, 1000);
    pollJob();
  } catch (error) {
    setJobRunning(false);
    $("#formError").textContent = error.message;
  }
}

function editorContent(document = state.editor.document) {
  if (!document) return "";
  return JSON.stringify({ cues: document.cues, styles: document.styles });
}

function cloneEditorDocument() {
  return JSON.parse(JSON.stringify(state.editor.document));
}

function updateEditorSaveState(message = "") {
  const dirty = editorContent() !== state.editor.savedContent;
  const status = $("#editorSaveState");
  status.className = dirty ? "dirty" : "saved";
  status.textContent = message || (dirty ? "有未保存修改" : "所有修改已保存");
  $("#saveSubtitle").disabled = !dirty || Boolean(state.editor.document?.operation_active);
  $("#undoSubtitle").disabled = !state.editor.undo.length;
  $("#redoSubtitle").disabled = !state.editor.redo.length;
  return dirty;
}

function pushEditorUndo(snapshot = null) {
  const value = snapshot || JSON.stringify(state.editor.document);
  if (state.editor.undo.at(-1) !== value) state.editor.undo.push(value);
  state.editor.undo = state.editor.undo.slice(-50);
  state.editor.redo = [];
}

function beginEditorChange() {
  if (!state.editor.pendingSnapshot) {
    state.editor.pendingSnapshot = JSON.stringify(state.editor.document);
  }
}

function commitEditorChange() {
  if (state.editor.pendingSnapshot && state.editor.pendingSnapshot !== JSON.stringify(state.editor.document)) {
    pushEditorUndo(state.editor.pendingSnapshot);
  }
  state.editor.pendingSnapshot = null;
  updateEditorSaveState();
}

function resetEditor() {
  const editor = state.editor;
  if (editor.exactUrl) URL.revokeObjectURL(editor.exactUrl);
  Object.assign(editor, {
    document: null, loadedJobId: null, selectedId: null, previewMode: "dual",
    undo: [], redo: [], savedContent: "", pendingSnapshot: null, exactUrl: null,
  });
  $("#editorCueCount").textContent = "0";
  $("#editorWorkspace").classList.add("hidden");
  $("#editorEmpty").classList.remove("hidden");
  $("#subtitleVideo").removeAttribute("src");
}

function formatCueTime(seconds) {
  const value = Math.max(0, Number(seconds) || 0);
  const hours = Math.floor(value / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  const secs = (value % 60).toFixed(3).padStart(6, "0");
  return hours ? `${hours}:${String(minutes).padStart(2, "0")}:${secs}` : `${String(minutes).padStart(2, "0")}:${secs}`;
}

function parseCueTime(value) {
  const text = String(value).trim();
  if (/^\d+(?:\.\d+)?$/.test(text)) return Number(text);
  const parts = text.split(":").map(Number);
  if (parts.some(Number.isNaN) || ![2, 3].includes(parts.length)) return NaN;
  if (parts.length === 2) return parts[0] * 60 + parts[1];
  return parts[0] * 3600 + parts[1] * 60 + parts[2];
}

function selectedCue() {
  return state.editor.document?.cues.find(cue => cue.id === state.editor.selectedId) || null;
}

function cueAtTime(time) {
  return state.editor.document?.cues.find(cue => time >= cue.start && time < cue.end) || null;
}

function localEditorWarnings() {
  const cues = state.editor.document?.cues || [];
  const warnings = [];
  cues.forEach((cue, index) => {
    if (cue.start < 0 || cue.end <= cue.start) warnings.push(`第 ${index + 1} 行结束时间必须晚于开始时间`);
    if (!cue.jp.trim() && !cue.zh.trim()) warnings.push(`第 ${index + 1} 行没有字幕内容`);
  });
  for (let index = 1; index < cues.length; index += 1) {
    if (cues[index].start < cues[index - 1].end) warnings.push(`第 ${index} 行与第 ${index + 1} 行时间重叠`);
  }
  return warnings;
}

function renderEditorWarnings() {
  const warnings = localEditorWarnings();
  $("#editorWarnings").textContent = warnings.length
    ? `时间提示：${warnings.slice(0, 3).join("；")}${warnings.length > 3 ? ` 等 ${warnings.length} 处` : ""}`
    : "";
}

function applyPreviewStyle(element, style) {
  const stage = $("#videoStage");
  const video = $("#subtitleVideo");
  const documentVideo = state.editor.document.video;
  const sourceWidth = video.videoWidth || documentVideo.width || 1920;
  const sourceHeight = video.videoHeight || documentVideo.height || 1080;
  const scale = Math.min(stage.clientWidth / sourceWidth, stage.clientHeight / sourceHeight);
  const shownWidth = sourceWidth * scale;
  const shownHeight = sourceHeight * scale;
  const offsetX = (stage.clientWidth - shownWidth) / 2;
  const offsetY = (stage.clientHeight - shownHeight) / 2;
  const alignment = Number(style.alignment);
  const column = ((alignment - 1) % 3) + 1;
  const row = Math.ceil(alignment / 3);
  const margin = Number(style.margin_v) * scale;
  const horizontalMargin = shownWidth * 0.04;
  element.style.left = "auto";
  element.style.right = "auto";
  element.style.top = "auto";
  element.style.bottom = "auto";
  const transforms = [];
  if (column === 1) {
    element.style.left = `${offsetX + horizontalMargin}px`;
    element.style.textAlign = "left";
  } else if (column === 2) {
    element.style.left = `${offsetX + shownWidth / 2}px`;
    element.style.textAlign = "center";
    transforms.push("translateX(-50%)");
  } else {
    element.style.right = `${offsetX + horizontalMargin}px`;
    element.style.textAlign = "right";
  }
  if (row === 3) {
    element.style.top = `${offsetY + margin}px`;
  } else if (row === 2) {
    element.style.top = `${offsetY + shownHeight / 2}px`;
    transforms.push("translateY(-50%)");
  } else {
    element.style.bottom = `${offsetY + margin}px`;
  }
  const outline = Math.max(.25, Number(style.outline) * scale);
  const shadow = Number(style.shadow) * scale;
  element.style.transform = transforms.join(" ");
  element.style.fontFamily = `"${style.font_name}", sans-serif`;
  element.style.fontSize = `${Math.max(8, Number(style.font_size) * scale)}px`;
  element.style.fontWeight = style.bold ? "700" : "400";
  element.style.color = style.primary_color;
  element.style.webkitTextStroke = `${outline}px ${style.outline_color}`;
  element.style.paintOrder = "stroke fill";
  element.style.textShadow = shadow ? `${shadow}px ${shadow}px ${Math.max(1, shadow)}px rgba(0,0,0,.85)` : "none";
}

function updateSubtitlePreview() {
  const document = state.editor.document;
  if (!document) return;
  const current = cueAtTime($("#subtitleVideo").currentTime || 0) || selectedCue();
  const zh = $("#previewZh");
  const jp = $("#previewJp");
  if (!current) {
    zh.textContent = "";
    jp.textContent = "";
    return;
  }
  zh.textContent = current.zh;
  jp.textContent = state.editor.previewMode === "dual" ? current.jp : "";
  applyPreviewStyle(zh, document.styles[state.editor.previewMode === "dual" ? "dual_zh" : "zh_only"]);
  applyPreviewStyle(jp, document.styles.dual_jp);
}

function updateActiveCue() {
  const video = $("#subtitleVideo");
  $("#videoTimecode").textContent = formatCueTime(video.currentTime || 0);
  const active = cueAtTime(video.currentTime || 0);
  $$(".cue-row", $("#cueTable")).forEach(row => row.classList.toggle("active", row.dataset.id === active?.id));
  updateSubtitlePreview();
}

function renderCueTable() {
  const table = $("#cueTable");
  table.replaceChildren();
  const header = document.createElement("div");
  header.className = "cue-table-header";
  ["#", "开始", "结束", "日文原文", "中文译文"].forEach(text => {
    const cell = document.createElement("span"); cell.textContent = text; header.append(cell);
  });
  table.append(header);
  const cues = state.editor.document.cues;
  cues.forEach((cue, index) => {
    const row = document.createElement("div");
    row.className = `cue-row ${cue.id === state.editor.selectedId ? "selected" : ""}`;
    if (cue.end <= cue.start || (!cue.jp.trim() && !cue.zh.trim())) row.classList.add("invalid");
    if (index > 0 && cue.start < cues[index - 1].end) row.classList.add("overlap");
    row.dataset.id = cue.id;
    const number = document.createElement("span");
    number.className = "cue-index"; number.textContent = String(index + 1).padStart(2, "0");
    const start = document.createElement("input"); start.value = formatCueTime(cue.start); start.setAttribute("aria-label", `第 ${index + 1} 行开始时间`);
    const end = document.createElement("input"); end.value = formatCueTime(cue.end); end.setAttribute("aria-label", `第 ${index + 1} 行结束时间`);
    const jp = document.createElement("textarea"); jp.value = cue.jp; jp.setAttribute("aria-label", `第 ${index + 1} 行日文`);
    const zh = document.createElement("textarea"); zh.value = cue.zh; zh.setAttribute("aria-label", `第 ${index + 1} 行中文`);
    [start, end, jp, zh].forEach(input => input.addEventListener("focus", beginEditorChange));
    start.addEventListener("input", () => { const value = parseCueTime(start.value); if (Number.isFinite(value)) cue.start = Math.max(0, Number(value.toFixed(3))); updateSubtitlePreview(); updateEditorSaveState(); });
    end.addEventListener("input", () => { const value = parseCueTime(end.value); if (Number.isFinite(value)) cue.end = Math.max(0, Number(value.toFixed(3))); updateSubtitlePreview(); updateEditorSaveState(); });
    jp.addEventListener("input", () => { cue.jp = jp.value; updateSubtitlePreview(); updateEditorSaveState(); });
    zh.addEventListener("input", () => { cue.zh = zh.value; updateSubtitlePreview(); updateEditorSaveState(); });
    [start, end, jp, zh].forEach(input => input.addEventListener("change", () => {
      commitEditorChange();
      state.editor.document.cues.sort((a, b) => a.start - b.start || a.end - b.end);
      renderCueTable(); renderEditorWarnings();
    }));
    row.addEventListener("click", event => {
      state.editor.selectedId = cue.id;
      $$(".cue-row", table).forEach(item => item.classList.toggle("selected", item.dataset.id === cue.id));
      if (!["INPUT", "TEXTAREA"].includes(event.target.tagName)) $("#subtitleVideo").currentTime = cue.start;
      updateSubtitlePreview();
    });
    row.append(number, start, end, jp, zh);
    table.append(row);
  });
  $("#editorCueCount").textContent = cues.length;
  $("#cueSummary").textContent = `${cues.length} 个片段`;
  renderEditorWarnings();
  updateActiveCue();
}

function loadStyleControls() {
  const style = state.editor.document.styles[$("#styleTrack").value];
  $("#styleFont").value = style.font_name;
  $("#styleSize").value = style.font_size;
  $("#stylePrimary").value = style.primary_color;
  $("#styleOutlineColor").value = style.outline_color;
  $("#styleOutline").value = style.outline;
  $("#styleShadow").value = style.shadow;
  $("#styleAlignment").value = String(style.alignment);
  $("#styleMarginV").value = style.margin_v;
  $("#styleBold").checked = style.bold;
  updateSubtitlePreview();
}

function updateStyleFromControls() {
  const style = state.editor.document.styles[$("#styleTrack").value];
  style.font_name = $("#styleFont").value.trim();
  style.font_size = Number($("#styleSize").value);
  style.primary_color = $("#stylePrimary").value.toUpperCase();
  style.outline_color = $("#styleOutlineColor").value.toUpperCase();
  style.outline = Number($("#styleOutline").value);
  style.shadow = Number($("#styleShadow").value);
  style.alignment = Number($("#styleAlignment").value);
  style.margin_v = Number($("#styleMarginV").value);
  style.bold = $("#styleBold").checked;
  updateSubtitlePreview();
  updateEditorSaveState();
}

function renderEditor() {
  const document = state.editor.document;
  $("#editorEmpty").classList.add("hidden");
  $("#editorWorkspace").classList.remove("hidden");
  $("#editorTitle").textContent = document.job_title || document.title || "字幕工作台";
  state.editor.selectedId = state.editor.selectedId || document.cues[0]?.id || null;
  const video = $("#subtitleVideo");
  if (document.video_url && video.getAttribute("src") !== document.video_url) {
    video.src = document.video_url;
  } else if (!document.video_url) {
    video.removeAttribute("src");
  }
  $("#exactPreviewButton").disabled = !document.video_url;
  $(".preview-note").textContent = document.video_url
    ? "实时预览用于快速编辑；精确预览由 FFmpeg 按最终 ASS 渲染。"
    : "当前任务没有下载原视频；仍可编辑字幕，但视频和精确帧预览不可用。";
  loadStyleControls();
  renderCueTable();
  updateEditorSaveState();
  $("#editorError").textContent = document.operation_active ? "压制或上传进行中，当前只能查看字幕" : "";
}

async function loadEditor(force = false) {
  if (!state.jobId || state.job?.status !== "completed") return;
  if (!force && state.editor.loadedJobId === state.jobId && state.editor.document) return;
  $("#editorError").textContent = "正在载入字幕…";
  const document = await api(`/api/jobs/${state.jobId}/subtitles`);
  state.editor.document = document;
  state.editor.loadedJobId = state.jobId;
  state.editor.undo = [];
  state.editor.redo = [];
  state.editor.pendingSnapshot = null;
  state.editor.savedContent = editorContent(document);
  state.editor.selectedId = document.cues[0]?.id || null;
  renderEditor();
  $("#editorError").textContent = "";
}

async function saveEditor() {
  const document = state.editor.document;
  if (!document) return false;
  $("#editorError").textContent = "";
  updateEditorSaveState("正在安全保存并备份…");
  try {
    const saved = await api(`/api/jobs/${state.jobId}/subtitles`, {
      method: "PUT",
      body: JSON.stringify({ revision: document.revision, cues: document.cues, styles: document.styles }),
    });
    state.editor.document = saved;
    state.editor.savedContent = editorContent(saved);
    state.editor.undo = [];
    state.editor.redo = [];
    renderEditor();
    const job = await api(`/api/jobs/${state.jobId}`);
    renderJob(job);
    updateEditorSaveState("已保存 · zh.ass 与 dual.ass 已同步");
    return true;
  } catch (error) {
    $("#editorError").textContent = error.message;
    updateEditorSaveState();
    return false;
  }
}

function undoEditor() {
  if (!state.editor.undo.length) return;
  state.editor.redo.push(JSON.stringify(state.editor.document));
  state.editor.document = JSON.parse(state.editor.undo.pop());
  state.editor.pendingSnapshot = null;
  renderEditor();
}

function redoEditor() {
  if (!state.editor.redo.length) return;
  state.editor.undo.push(JSON.stringify(state.editor.document));
  state.editor.document = JSON.parse(state.editor.redo.pop());
  state.editor.pendingSnapshot = null;
  renderEditor();
}

function addCue() {
  const document = state.editor.document; if (!document) return;
  pushEditorUndo();
  const start = Number(($("#subtitleVideo").currentTime || 0).toFixed(3));
  const cue = { id: `cue-${Date.now().toString(36)}`, start, end: start + 2, jp: "", zh: "新字幕" };
  document.cues.push(cue); document.cues.sort((a, b) => a.start - b.start);
  state.editor.selectedId = cue.id; renderCueTable(); updateEditorSaveState();
}

function deleteSelectedCue() {
  const cue = selectedCue(); if (!cue || state.editor.document.cues.length <= 1) return;
  pushEditorUndo();
  const index = state.editor.document.cues.indexOf(cue);
  state.editor.document.cues.splice(index, 1);
  state.editor.selectedId = state.editor.document.cues[Math.min(index, state.editor.document.cues.length - 1)]?.id || null;
  renderCueTable(); updateEditorSaveState();
}

function splitValue(value) {
  const text = String(value); if (text.length < 2) return [text, ""];
  const middle = Math.ceil(text.length / 2); return [text.slice(0, middle).trim(), text.slice(middle).trim()];
}

function splitSelectedCue() {
  const cue = selectedCue(); if (!cue) return;
  let at = $("#subtitleVideo").currentTime;
  if (!(at > cue.start && at < cue.end)) at = (cue.start + cue.end) / 2;
  if (at - cue.start < .05 || cue.end - at < .05) return;
  pushEditorUndo();
  const [jp1, jp2] = splitValue(cue.jp); const [zh1, zh2] = splitValue(cue.zh);
  const next = { id: `cue-${Date.now().toString(36)}`, start: Number(at.toFixed(3)), end: cue.end, jp: jp2, zh: zh2 };
  cue.end = Number(at.toFixed(3)); cue.jp = jp1; cue.zh = zh1;
  const index = state.editor.document.cues.indexOf(cue); state.editor.document.cues.splice(index + 1, 0, next);
  state.editor.selectedId = next.id; renderCueTable(); updateEditorSaveState();
}

function mergeSelectedCue() {
  const cue = selectedCue(); if (!cue) return;
  const index = state.editor.document.cues.indexOf(cue); const next = state.editor.document.cues[index + 1];
  if (!next) return;
  pushEditorUndo();
  cue.end = Math.max(cue.end, next.end);
  cue.jp = [cue.jp, next.jp].filter(Boolean).join(" "); cue.zh = [cue.zh, next.zh].filter(Boolean).join(" ");
  state.editor.document.cues.splice(index + 1, 1); renderCueTable(); updateEditorSaveState();
}

function nudgeSelectedCue(delta) {
  const cue = selectedCue(); if (!cue) return;
  pushEditorUndo();
  const duration = cue.end - cue.start;
  cue.start = Math.max(0, Number((cue.start + delta).toFixed(3)));
  cue.end = Number((cue.start + duration).toFixed(3));
  state.editor.document.cues.sort((a, b) => a.start - b.start); renderCueTable(); updateEditorSaveState();
}

function setSelectedCueBoundary(boundary) {
  const cue = selectedCue(); if (!cue) return;
  const time = Number(($("#subtitleVideo").currentTime || 0).toFixed(3));
  if (boundary === "start" && time >= cue.end) { $("#editorError").textContent = "开始时间必须早于结束时间"; return; }
  if (boundary === "end" && time <= cue.start) { $("#editorError").textContent = "结束时间必须晚于开始时间"; return; }
  pushEditorUndo(); cue[boundary] = time;
  state.editor.document.cues.sort((a, b) => a.start - b.start); renderCueTable(); updateEditorSaveState();
}

async function showExactPreview() {
  if (!state.editor.document) return;
  if (updateEditorSaveState()) {
    const saved = await saveEditor(); if (!saved) return;
  }
  const button = $("#exactPreviewButton"); button.disabled = true; button.textContent = "正在渲染…";
  $("#editorError").textContent = "";
  try {
    const response = await fetch(`/api/jobs/${state.jobId}/subtitles/preview`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ timestamp: $("#subtitleVideo").currentTime || 0, subtitle_type: state.editor.previewMode }),
    });
    if (!response.ok) {
      let message = `精确预览失败 (${response.status})`;
      try { message = (await response.json()).detail || message; } catch (_) {}
      throw new Error(message);
    }
    if (state.editor.exactUrl) URL.revokeObjectURL(state.editor.exactUrl);
    state.editor.exactUrl = URL.createObjectURL(await response.blob());
    $("#exactPreviewImage").src = state.editor.exactUrl;
    $("#exactPreviewResult").classList.remove("hidden");
  } catch (error) { $("#editorError").textContent = error.message; }
  finally { button.disabled = false; button.textContent = "精确预览当前帧"; }
}

function resetGlossaryForm() {
  $("#termId").value = "";
  $("#sourceTerm").value = "";
  $("#targetTerm").value = "";
  $("#termNote").value = "";
  $("#glossaryFormTitle").textContent = "添加术语";
  $("#saveTerm").textContent = "保存术语";
  $("#cancelEdit").classList.add("hidden");
  $("#glossaryError").textContent = "";
}

function startTermEdit(term) {
  $("#termId").value = term.id;
  $("#sourceTerm").value = term.source;
  $("#targetTerm").value = term.target;
  $("#termNote").value = term.note || "";
  $("#glossaryFormTitle").textContent = "编辑术语";
  $("#saveTerm").textContent = "保存修改";
  $("#cancelEdit").classList.remove("hidden");
  $("#sourceTerm").focus();
}

function renderGlossary() {
  const list = $("#glossaryList");
  list.replaceChildren();
  $("#termCount").textContent = state.terms.length;
  $("#termTotal").textContent = `${state.terms.length} 个术语`;
  if (!state.terms.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.innerHTML = "<strong>术语库还是空的</strong><span>添加角色名、作品名或固定表达，让翻译保持一致。</span>";
    list.append(empty);
    return;
  }
  state.terms.forEach(term => {
    const row = document.createElement("article");
    row.className = `term-row ${term.enabled ? "" : "disabled"}`;
    const pair = document.createElement("div");
    pair.className = "term-pair";
    const source = document.createElement("div");
    source.className = "term-word";
    const sourceStrong = document.createElement("strong");
    sourceStrong.textContent = term.source;
    const sourceSmall = document.createElement("small");
    sourceSmall.textContent = term.note || "日文原词";
    source.append(sourceStrong, sourceSmall);
    const arrow = document.createElement("span");
    arrow.className = "term-arrow";
    arrow.textContent = "→";
    const target = document.createElement("div");
    target.className = "term-word";
    const targetStrong = document.createElement("strong");
    targetStrong.textContent = term.target;
    const targetSmall = document.createElement("small");
    targetSmall.textContent = term.enabled ? "已启用" : "已停用";
    target.append(targetStrong, targetSmall);
    pair.append(source, arrow, target);

    const menu = document.createElement("div");
    menu.className = "term-menu";
    const menuButton = document.createElement("button");
    menuButton.type = "button";
    menuButton.textContent = "•••";
    menuButton.setAttribute("aria-label", `管理术语 ${term.source}`);
    menuButton.onclick = () => menu.classList.toggle("open");
    const actions = document.createElement("div");
    actions.className = "term-actions";
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.textContent = term.enabled ? "停用" : "启用";
    toggle.onclick = () => updateTerm(term.id, { enabled: !term.enabled });
    const edit = document.createElement("button");
    edit.type = "button";
    edit.textContent = "编辑";
    edit.onclick = () => startTermEdit(term);
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "delete";
    remove.textContent = "删除";
    remove.onclick = () => deleteTerm(term);
    actions.append(toggle, edit, remove);
    menu.append(menuButton, actions);
    row.append(pair, menu);
    list.append(row);
  });
}

async function loadGlossary() {
  try {
    state.terms = await api("/api/glossary");
    renderGlossary();
  } catch (error) {
    $("#glossaryError").textContent = error.message;
  }
}

async function submitTerm(event) {
  event.preventDefault();
  const id = $("#termId").value;
  const payload = {
    source: $("#sourceTerm").value.trim(),
    target: $("#targetTerm").value.trim(),
    note: $("#termNote").value.trim(),
    enabled: true,
  };
  try {
    await api(id ? `/api/glossary/${id}` : "/api/glossary", {
      method: id ? "PATCH" : "POST",
      body: JSON.stringify(payload),
    });
    resetGlossaryForm();
    await loadGlossary();
  } catch (error) {
    $("#glossaryError").textContent = error.message;
  }
}

async function updateTerm(id, changes) {
  try {
    await api(`/api/glossary/${id}`, { method: "PATCH", body: JSON.stringify(changes) });
    await loadGlossary();
  } catch (error) { $("#glossaryError").textContent = error.message; }
}

async function deleteTerm(term) {
  if (!confirm(`确定删除术语“${term.source}”吗？`)) return;
  try {
    await api(`/api/glossary/${term.id}`, { method: "DELETE" });
    if ($("#termId").value === term.id) resetGlossaryForm();
    await loadGlossary();
  } catch (error) { $("#glossaryError").textContent = error.message; }
}

document.addEventListener("DOMContentLoaded", () => {
  $$(".tab").forEach(button => button.addEventListener("click", () => switchView(button.dataset.view)));
  $("#jobForm").addEventListener("submit", submitJob);
  $("#burnForm").addEventListener("submit", submitBurn);
  $("#uploadForm").addEventListener("submit", submitUpload);
  $("#biliLoginButton").addEventListener("click", launchBiliupLogin);
  $("#biliCategory").addEventListener("change", event => populateBiliTid(event.target.value));
  $("#biliTid").addEventListener("change", event => {
    $("#biliTidValue").textContent = event.target.value || "--";
  });
  $("#glossaryForm").addEventListener("submit", submitTerm);
  $("#cancelEdit").addEventListener("click", resetGlossaryForm);
  $("#editorBackToTask").addEventListener("click", () => switchView("task"));
  $("#saveSubtitle").addEventListener("click", saveEditor);
  $("#reloadSubtitle").addEventListener("click", async () => {
    if (updateEditorSaveState() && !confirm("放弃尚未保存的字幕修改并重新载入吗？")) return;
    await loadEditor(true);
  });
  $("#undoSubtitle").addEventListener("click", undoEditor);
  $("#redoSubtitle").addEventListener("click", redoEditor);
  $("#addCue").addEventListener("click", addCue);
  $("#deleteCue").addEventListener("click", deleteSelectedCue);
  $("#splitCue").addEventListener("click", splitSelectedCue);
  $("#mergeCue").addEventListener("click", mergeSelectedCue);
  $("#setCueStart").addEventListener("click", () => setSelectedCueBoundary("start"));
  $("#setCueEnd").addEventListener("click", () => setSelectedCueBoundary("end"));
  $$('[data-nudge]').forEach(button => button.addEventListener("click", () => nudgeSelectedCue(Number(button.dataset.nudge))));
  $("#subtitleVideo").addEventListener("timeupdate", updateActiveCue);
  $("#subtitleVideo").addEventListener("seeked", updateActiveCue);
  $("#subtitleVideo").addEventListener("loadedmetadata", updateSubtitlePreview);
  $("#styleTrack").addEventListener("change", () => { if (state.editor.document) loadStyleControls(); });
  ["styleFont", "styleSize", "stylePrimary", "styleOutlineColor", "styleOutline", "styleShadow", "styleAlignment", "styleMarginV", "styleBold"].forEach(id => {
    const control = $(`#${id}`);
    control.addEventListener("focus", beginEditorChange);
    control.addEventListener("input", updateStyleFromControls);
    control.addEventListener("change", () => { updateStyleFromControls(); commitEditorChange(); });
  });
  $$('[data-preview-mode]').forEach(button => button.addEventListener("click", () => {
    state.editor.previewMode = button.dataset.previewMode;
    $$('[data-preview-mode]').forEach(item => item.classList.toggle("active", item === button));
    updateSubtitlePreview();
  }));
  $("#exactPreviewButton").addEventListener("click", showExactPreview);
  $("#closeExactPreview").addEventListener("click", () => $("#exactPreviewResult").classList.add("hidden"));
  window.addEventListener("resize", updateSubtitlePreview);
  window.addEventListener("beforeunload", event => {
    if (state.editor.document && editorContent() !== state.editor.savedContent) {
      event.preventDefault(); event.returnValue = "";
    }
  });
  document.addEventListener("keydown", event => {
    if (!$("#editorView").classList.contains("active") || !state.editor.document || !event.ctrlKey) return;
    const key = event.key.toLowerCase();
    if (key === "s") { event.preventDefault(); saveEditor(); }
    else if (key === "z" && !event.shiftKey) { event.preventDefault(); undoEditor(); }
    else if (key === "y" || (key === "z" && event.shiftKey)) { event.preventDefault(); redoEditor(); }
  });
  document.addEventListener("click", event => {
    $$(".term-menu.open").forEach(menu => { if (!menu.contains(event.target)) menu.classList.remove("open"); });
  });
  checkHealth();
  loadBiliupStatus();
  loadBilibiliCategories();
  loadGlossary();
  restoreLatestJob();
});
