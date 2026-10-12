const $ = (id) => document.getElementById(id);
const state = { sessionId: null, busy: false, traceId: null, navigationVersion: 0,
  token: sessionStorage.getItem("agentAdminToken") || "" };

function notice(message, error = false) {
  const box = $("notice");
  box.textContent = message;
  box.classList.toggle("error", error);
  box.hidden = !message;
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (state.token) headers.set("Authorization", `Bearer ${state.token}`);
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    let detail = `请求失败（HTTP ${response.status}）`;
    try { detail = (await response.json()).detail || detail; } catch (_) { /* non-JSON error */ }
    throw new Error(detail);
  }
  return response.status === 204 ? null : response.json();
}

function setBusy(busy) {
  state.busy = busy;
  $("send-button").disabled = busy;
  $("message-input").disabled = busy;
  $("new-chat").disabled = busy;
  $("logout").disabled = busy;
}

function showWelcome() {
  $("welcome").hidden = $("messages").children.length > 0;
}

function appendMessage(role, content, pending = false) {
  const row = document.createElement("article");
  row.className = `message ${role}${pending ? " pending" : ""}`;
  if (role === "assistant") {
    const avatar = document.createElement("div");
    avatar.className = "avatar";
    avatar.textContent = "✦";
    row.append(avatar);
  }
  const body = document.createElement("div");
  body.className = "message-body";
  const text = document.createElement("div");
  text.className = "message-content";
  text.textContent = content;
  body.append(text);
  row.append(body);
  $("messages").append(row);
  showWelcome();
  $("chat-scroll").scrollTop = $("chat-scroll").scrollHeight;
  return { row, text };
}

function clearConversation() {
  $("messages").replaceChildren();
  $("conversation-title").textContent = "新会话";
  $("delete-session").hidden = true;
  $("trace-list").replaceChildren();
  const empty = document.createElement("p");
  empty.className = "muted";
  empty.textContent = "完成一次对话后显示执行记录。";
  $("trace-list").append(empty);
  state.traceId = null;
  showWelcome();
}

async function loadSessions() {
  const sessions = [];
  const pageSize = 100;
  for (let offset = 0; ; offset += pageSize) {
    const page = await api(`/api/sessions?limit=${pageSize}&offset=${offset}`);
    if (!state.token) return;
    sessions.push(...page);
    if (page.length < pageSize) break;
  }
  const list = $("session-list");
  list.replaceChildren();
  if (!sessions.length) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = "暂无历史会话";
    list.append(empty);
  }
  for (const session of sessions) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `session-item${session.id === state.sessionId ? " active" : ""}`;
    const icon = document.createElement("span");
    icon.className = "session-icon";
    icon.textContent = "◷";
    const title = document.createElement("span");
    title.textContent = session.title;
    button.append(icon, title);
    button.addEventListener("click", () => openSession(session.id));
    list.append(button);
  }
  $("status-dot").classList.add("connected");
  $("connection-status").textContent = "服务已连接";
}

async function openSession(id) {
  if (state.busy) return;
  const navigationVersion = ++state.navigationVersion;
  try {
    const session = await api(`/api/sessions/${encodeURIComponent(id)}`);
    if (navigationVersion !== state.navigationVersion || state.busy) return;
    state.sessionId = id;
    clearConversation();
    $("conversation-title").textContent = session.title;
    $("delete-session").hidden = false;
    for (const message of session.messages) appendMessage(message.role, message.content);
    await loadSessions();
    if (navigationVersion !== state.navigationVersion) return;
    $("sidebar").classList.remove("open");
    notice("");
  } catch (error) {
    if (navigationVersion === state.navigationVersion) notice(error.message, true);
  }
}

function newChat() {
  if (state.busy) return;
  state.navigationVersion += 1;
  state.sessionId = null;
  clearConversation();
  loadSessions().catch((error) => notice(error.message, true));
  $("sidebar").classList.remove("open");
  notice("");
  $("message-input").focus();
}

async function deleteSession() {
  if (!state.sessionId || state.busy) return;
  if (!window.confirm("确定删除这段会话及其全部消息吗？此操作无法撤销。")) return;
  try {
    await api(`/api/sessions/${encodeURIComponent(state.sessionId)}`, { method: "DELETE" });
    newChat();
    notice("会话已删除。 ");
  } catch (error) { notice(error.message, true); }
}

function parseEvent(block) {
  let name = "";
  const data = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) name = line.slice(6).trim();
    if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
  }
  return { name, data: JSON.parse(data.join("\n")) };
}

async function streamChat(message, onDelta) {
  const response = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream",
      Authorization: `Bearer ${state.token}` },
    body: JSON.stringify({ message, session_id: state.sessionId }),
  });
  if (!response.ok) {
    let detail = `发送失败（HTTP ${response.status}）`;
    try { detail = (await response.json()).detail || detail; } catch (_) { /* non-JSON error */ }
    throw new Error(detail);
  }
  if (!response.body || !response.headers.get("content-type")?.startsWith("text/event-stream")) {
    throw new Error("后端未返回流式响应。");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let done = null;
  let text = "";
  while (true) {
    const packet = await reader.read();
    buffer += decoder.decode(packet.value || new Uint8Array(), { stream: !packet.done });
    buffer = buffer.replace(/\r\n/g, "\n");
    let boundary;
    while ((boundary = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      if (!block.trim()) continue;
      const event = parseEvent(block);
      if (event.name === "delta") {
        text += event.data.text;
        onDelta(text);
      } else if (event.name === "done") {
        done = event.data;
      } else if (event.name === "error") {
        throw new Error(event.data.message || "Agent 暂时无法完成请求。");
      }
    }
    if (packet.done) break;
  }
  if (!done || done.answer !== text.trim()) throw new Error("回答传输中断，请刷新会话核对历史。");
  return done;
}

async function sendMessage(raw) {
  const message = raw.trim();
  if (!message || state.busy) return;
  state.navigationVersion += 1;
  setBusy(true);
  notice("");
  $("message-input").value = "";
  appendMessage("user", message);
  const reply = appendMessage("assistant", "", true);
  try {
    const done = await streamChat(message, (text) => {
      reply.text.textContent = text;
      $("chat-scroll").scrollTop = $("chat-scroll").scrollHeight;
    });
    reply.row.classList.remove("pending");
    state.sessionId = done.session_id;
    state.traceId = done.trace_id;
    $("delete-session").hidden = false;
    try {
      await Promise.all([loadSessions(), loadTrace(done.trace_id)]);
      const detail = await api(`/api/sessions/${encodeURIComponent(state.sessionId)}`);
      $("conversation-title").textContent = detail.title;
    } catch (refreshError) {
      notice(`回答已保存，但列表或 Trace 刷新失败：${refreshError.message}`, true);
    }
  } catch (error) {
    reply.row.classList.remove("pending");
    reply.text.textContent = "回答未完成或未保存。";
    notice(`${error.message} 请刷新会话核对历史，再决定是否重发。`, true);
  } finally { setBusy(false); $("message-input").focus(); }
}

function formatSize(bytes) {
  return bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

async function loadKnowledge() {
  const documents = await api("/api/knowledge");
  if (!state.token) return;
  const list = $("documents");
  list.replaceChildren();
  if (!documents.length) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = "暂无知识文档。上传 TXT 或 PDF 开始使用。";
    list.append(empty);
  }
  for (const doc of documents) {
    const row = document.createElement("div");
    row.className = "document";
    const icon = document.createElement("span");
    icon.className = "document-icon";
    icon.textContent = doc.name.toLowerCase().endsWith(".pdf") ? "▤" : "▥";
    const info = document.createElement("div");
    info.className = "document-info";
    const title = document.createElement("div");
    title.className = "document-name";
    title.textContent = doc.name;
    title.title = doc.name;
    const meta = document.createElement("div");
    meta.className = "document-meta";
    meta.textContent = `${formatSize(doc.size_bytes)} · ${new Date(doc.updated_at).toLocaleDateString("zh-CN")}`;
    info.append(title, meta);
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "document-delete";
    remove.setAttribute("aria-label", `删除 ${doc.name}`);
    remove.textContent = "×";
    remove.addEventListener("click", () => deleteKnowledge(doc.name));
    row.append(icon, info, remove);
    list.append(row);
  }
}

async function uploadKnowledge(file) {
  if (!file) return;
  if (!/\.(txt|pdf)$/i.test(file.name)) { notice("只支持 TXT 或 PDF 文件。", true); return; }
  if (file.size > 10 * 1024 * 1024) { notice("文件不能超过 10 MB。", true); return; }
  let uploadAttempted = false;
  try {
    const existing = await api("/api/knowledge");
    if (existing.some((item) => item.name === file.name) &&
        !window.confirm(`覆盖 ${file.name} 并更新索引吗？`)) return;
    notice("正在上传并更新知识库索引…");
    uploadAttempted = true;
    await api(`/api/knowledge/${encodeURIComponent(file.name)}`, {
      method: "PUT", headers: { "Content-Type": "application/octet-stream" }, body: file,
    });
    await loadKnowledge();
    notice(`${file.name} 已上传并完成索引。`);
  } catch (error) {
    await loadKnowledge().catch(() => {});
    notice(uploadAttempted
      ? `${error.message} 文件可能已保存，可点击“同步索引”重试。`
      : error.message, true);
  }
}

async function deleteKnowledge(name) {
  if (!window.confirm(`删除 ${name} 并从知识库移除吗？此操作无法撤销。`)) return;
  try {
    await api(`/api/knowledge/${encodeURIComponent(name)}`, { method: "DELETE" });
    await loadKnowledge();
    notice(`${name} 已删除。`);
  } catch (error) {
    await loadKnowledge().catch(() => {});
    notice(`${error.message} 可点击“同步索引”重试。`, true);
  }
}

async function syncKnowledge() {
  notice("正在同步知识库索引…");
  try {
    const result = await api("/api/knowledge/sync", { method: "POST" });
    await loadKnowledge();
    notice(`索引已同步：新增 ${result.added}，保留 ${result.kept}，删除 ${result.deleted}。`);
  } catch (error) { notice(error.message, true); }
}

async function loadTrace(id) {
  const trace = await api(`/api/traces/${encodeURIComponent(id)}`);
  const list = $("trace-list");
  list.replaceChildren();
  if (!trace.events.length) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = `暂无 Trace 事件 · ${id.slice(0, 8)}`;
    list.append(empty);
  }
  for (const event of trace.events) {
    if (event.event === "request.start" || event.event === "request.response") continue;
    const row = document.createElement("div");
    row.className = "trace-item";
    const title = document.createElement("div");
    title.className = "trace-name";
    title.textContent = event.event;
    const parts = [];
    if (event.tool_name) parts.push(event.tool_name);
    if (event.status) parts.push(event.status);
    if (event.duration_ms !== undefined) parts.push(`${Math.round(event.duration_ms)} ms`);
    if (event.doc_count !== undefined) parts.push(`${event.doc_count} 文档`);
    if (event.input_tokens !== undefined || event.output_tokens !== undefined) {
      parts.push(`${event.input_tokens || 0}/${event.output_tokens || 0} tokens`);
    }
    const meta = document.createElement("div");
    meta.className = "trace-meta";
    meta.textContent = parts.join(" · ") || event.timestamp || "";
    row.append(title, meta);
    list.append(row);
  }
}

$("new-chat").addEventListener("click", newChat);
$("delete-session").addEventListener("click", deleteSession);
$("menu-button").addEventListener("click", () => $("sidebar").classList.toggle("open"));
$("chat-form").addEventListener("submit", (event) => {
  event.preventDefault();
  sendMessage($("message-input").value);
});
$("message-input").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    sendMessage($("message-input").value);
  }
});
document.querySelectorAll("[data-prompt]").forEach((button) => {
  button.addEventListener("click", () => sendMessage(button.dataset.prompt));
});
$("file-input").addEventListener("change", (event) => {
  uploadKnowledge(event.target.files[0]).finally(() => { event.target.value = ""; });
});
$("sync-knowledge").addEventListener("click", syncKnowledge);

async function enterWorkspace() {
  await api("/api/knowledge");
  sessionStorage.setItem("agentAdminToken", state.token);
  $("auth-screen").hidden = true;
  $("auth-error").hidden = true;
  loadSessions().catch((error) => {
    $("connection-status").textContent = "服务未连接";
    notice(error.message, true);
  });
  loadKnowledge().catch((error) => notice(error.message, true));
}

$("auth-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  state.token = $("admin-token").value;
  try {
    await enterWorkspace();
    $("admin-token").value = "";
  } catch (error) {
    state.token = "";
    sessionStorage.removeItem("agentAdminToken");
    $("auth-error").textContent = error.message;
    $("auth-error").hidden = false;
  }
});

$("logout").addEventListener("click", () => {
  state.token = "";
  sessionStorage.removeItem("agentAdminToken");
  state.navigationVersion += 1;
  state.sessionId = null;
  clearConversation();
  $("session-list").replaceChildren();
  $("documents").replaceChildren();
  $("auth-screen").hidden = false;
  $("admin-token").focus();
});

if (state.token) enterWorkspace().catch((error) => {
  state.token = "";
  sessionStorage.removeItem("agentAdminToken");
  $("auth-error").textContent = error.message;
  $("auth-error").hidden = false;
});
