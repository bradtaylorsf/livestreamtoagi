const DEFAULT_API_BASE = "http://127.0.0.1:8010";
const POLL_MS = 1000;
const STATUS_LABELS = new Set(["idle", "talking", "building", "active", "waiting", "error"]);

const params = new URLSearchParams(window.location.search);
const apiBase = (params.get("api") || DEFAULT_API_BASE).replace(/\/$/, "");
const statusUrl = `${apiBase}/api/stream/agent-status`;

const agentsEl = document.getElementById("overlay-agents");
const connectionEl = document.getElementById("overlay-connection");
const updatedEl = document.getElementById("overlay-updated-value");
const topicEl = document.getElementById("overlay-topic-value");
const rows = new Map();

function setConnection(state, label) {
  connectionEl.dataset.state = state;
  connectionEl.textContent = label;
}

function statusLabel(status) {
  if (!STATUS_LABELS.has(status)) return "idle";
  return status;
}

function formatTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function createRow(agent) {
  const row = document.createElement("div");
  row.className = "agent-row";
  row.dataset.agentId = agent.id;

  const dot = document.createElement("span");
  dot.className = "status-dot";
  dot.setAttribute("aria-hidden", "true");

  const name = document.createElement("span");
  name.className = "agent-name";

  const status = document.createElement("span");
  status.className = "agent-status";

  row.append(dot, name, status);
  agentsEl.appendChild(row);

  const record = { row, name, status };
  rows.set(agent.id, record);
  return record;
}

function renderAgents(agents) {
  const seen = new Set();
  let currentTopic = null;

  for (const agent of agents) {
    seen.add(agent.id);
    const record = rows.get(agent.id) || createRow(agent);
    const normalizedStatus = statusLabel(agent.status);

    record.row.dataset.status = normalizedStatus;
    record.name.textContent = agent.display_name || agent.id;
    record.status.textContent = normalizedStatus;

    if (!currentTopic && agent.current_topic) {
      currentTopic = agent.current_topic;
    }
  }

  for (const [agentId, record] of rows.entries()) {
    if (!seen.has(agentId)) {
      record.row.remove();
      rows.delete(agentId);
    }
  }

  topicEl.textContent = currentTopic || "-";
}

async function refresh() {
  try {
    const response = await fetch(statusUrl, {
      cache: "no-store",
      headers: { Accept: "application/json" },
    });
    if (!response.ok) {
      throw new Error(`status ${response.status}`);
    }

    const payload = await response.json();
    renderAgents(Array.isArray(payload.agents) ? payload.agents : []);
    updatedEl.textContent = formatTime(payload.updated_at);
    setConnection("online", "ONLINE");
  } catch (error) {
    setConnection("offline", "OFFLINE");
  }
}

refresh();
window.setInterval(refresh, POLL_MS);
