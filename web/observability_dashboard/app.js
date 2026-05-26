const dateInput = document.querySelector("#dateInput");
const refreshBtn = document.querySelector("#refreshBtn");
const metricsEl = document.querySelector("#metrics");
const traceListEl = document.querySelector("#traceList");
const traceDetailEl = document.querySelector("#traceDetail");

dateInput.value = new Date().toISOString().slice(0, 10);
refreshBtn.addEventListener("click", loadDashboard);
dateInput.addEventListener("change", loadDashboard);

async function loadDashboard() {
  const date = dateInput.value;
  const [summary, traces] = await Promise.all([
    fetchJson(`/api/observability/summary?date=${date}`),
    fetchJson(`/api/traces?date=${date}`),
  ]);
  renderMetrics(summary);
  renderTraceList(traces.traces || []);
}

async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
}

function renderMetrics(summary) {
  const cost = summary.cost || {};
  const cards = [
    ["Trace 数", summary.trace_count || 0],
    ["事件数", summary.event_count || 0],
    ["总 Token", cost.total_tokens || 0],
    ["估算成本", `$${Number(cost.total_cost_usd || 0).toFixed(4)}`],
    ["平均延迟", `${summary.avg_latency_ms || 0} ms`],
    ["熔断次数", (summary.event_count_by_type || {}).circuit_breaker_triggered || 0],
  ];
  metricsEl.innerHTML = cards
    .map(([label, value]) => `<article class="metric"><span>${label}</span><strong>${value}</strong></article>`)
    .join("");
}

function renderTraceList(traces) {
  if (!traces.length) {
    traceListEl.innerHTML = `<div class="empty">当天没有 trace 记录</div>`;
    return;
  }
  traceListEl.innerHTML = traces
    .map(
      (trace) => `
        <button class="traceRow" data-trace-id="${escapeHtml(trace.trace_id)}">
          <span class="time">${escapeHtml(trace.last_at || "")}</span>
          <span class="query">${escapeHtml(trace.user_query || "")}</span>
          <span class="meta">${escapeHtml(trace.framework_id || "unrouted")} · ${trace.total_tokens || 0} tokens · ${escapeHtml(trace.status || "")}</span>
          <span class="flags">${(trace.risk_flags || []).map((flag) => `<b>${escapeHtml(flag)}</b>`).join("")}</span>
        </button>
      `
    )
    .join("");

  traceListEl.querySelectorAll(".traceRow").forEach((row) => {
    row.addEventListener("click", () => loadTraceDetail(row.dataset.traceId));
  });
}

async function loadTraceDetail(traceId) {
  const date = dateInput.value;
  const detail = await fetchJson(`/api/traces/${encodeURIComponent(traceId)}?date=${date}`);
  const events = detail.events || [];
  if (!events.length) {
    traceDetailEl.innerHTML = `<div class="empty">没有找到事件</div>`;
    return;
  }
  traceDetailEl.innerHTML = events
    .map((event) => {
      const tokenUsage = event.token_usage || {};
      const flags = (event.risk_flags || []).map((flag) => `<b>${escapeHtml(flag)}</b>`).join("");
      return `
        <article class="event">
          <div class="eventHead">
            <strong>${escapeHtml(event.event_type || "")}</strong>
            <span>${escapeHtml(event.timestamp || "")}</span>
          </div>
          <div class="eventMeta">
            ${escapeHtml(event.agent_role || "unknown")} · ${escapeHtml(event.status || "")} · ${event.latency_ms ?? "-"} ms
            · ${tokenUsage.total_tokens || 0} tokens
          </div>
          ${flags ? `<div class="flags">${flags}</div>` : ""}
          ${event.input_preview ? `<p><label>输入</label>${escapeHtml(event.input_preview)}</p>` : ""}
          ${event.output_preview ? `<p><label>输出</label>${escapeHtml(event.output_preview)}</p>` : ""}
        </article>
      `;
    })
    .join("");
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

loadDashboard().catch((error) => {
  metricsEl.innerHTML = `<article class="metric error"><span>加载失败</span><strong>${escapeHtml(error.message)}</strong></article>`;
});
