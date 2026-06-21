// apolo-dynamic-flow — panel.js
// Carga datos de telemetría y state, renderiza el panel.
// Funciona abriendo index.html directamente (file://) o via servidor.

const API = {
  // En modo servidor: usar endpoints relativos.
  // En modo file://: cargar archivos estáticos desde ../tests/ o path indicado.
  statePath: null,
  telemetryPath: null,
  blocksPath: null,
  toolRegistryPath: null,
};

// Configurar paths (se pueden pasar por query string)
const params = new URLSearchParams(window.location.search);
const repoRoot = params.get("repo") || ".";
const flowid = params.get("flowid") || "APOLO-LATEST";
const POLL_MS = 5000;

function $(sel) { return document.querySelector(sel); }
function $$(sel) { return document.querySelectorAll(sel); }

// ============================================================================
// Tab navigation
// ============================================================================

document.addEventListener("DOMContentLoaded", () => {
  $$("nav button").forEach(btn => {
    btn.addEventListener("click", () => {
      const tab = btn.dataset.tab;
      $$("nav button").forEach(b => b.classList.remove("active"));
      $$(".tab").forEach(t => t.classList.remove("active"));
      btn.classList.add("active");
      $(`#tab-${tab}`).classList.add("active");
    });
  });

  // Paths ABSOLUTOS (start with /) para que el servidor los resuelva desde repo_root.
  // El servidor sirve desde repoRoot, así que /plan/... → repoRoot/plan/...
  API.statePath = `/plan/active/${flowid}/FLOW-STATE.yaml`;
  API.telemetryPath = `/plan/active/${flowid}/telemetry.jsonl`;
  API.blocksPath = `/plan/active/${flowid}/BLOCK-LOG.yaml`;
  API.toolRegistryPath = `/.opencode/apolo-dynamic/TOOL-REGISTRY.yaml`;

  // Poll
  refresh();
  setInterval(refresh, POLL_MS);
});

// ============================================================================
// Refresh
// ============================================================================

async function refresh() {
  try {
    const [state, telemetry, blocks, registry] = await Promise.all([
      fetchYaml(API.statePath),
      fetchJsonl(API.telemetryPath),
      fetchYaml(API.blocksPath),
      fetchYaml(API.toolRegistryPath),
    ]);
    if (state) renderState(state);
    if (telemetry) renderTelemetry(telemetry);
    if (blocks) renderBlocks(blocks);
    if (registry) renderTools(registry);
    $("#updated-at").textContent = `Actualizado: ${new Date().toLocaleTimeString()}`;
  } catch (e) {
    console.warn("refresh failed", e);
  }
}

// ============================================================================
// Fetchers
// ============================================================================

async function fetchYaml(path) {
  try {
    const res = await fetch(path, { cache: "no-store" });
    if (!res.ok) return null;
    const text = await res.text();
    return parseYaml(text);
  } catch { return null; }
}

async function fetchJsonl(path) {
  try {
    const res = await fetch(path, { cache: "no-store" });
    if (!res.ok) return [];
    const text = await res.text();
    return text.trim().split("\n").filter(Boolean).map(line => {
      try { return JSON.parse(line); } catch { return null; }
    }).filter(Boolean);
  } catch { return []; }
}

// YAML parser minimal (mirror of common.py)
function parseYaml(text) {
  const lines = text.split("\n");
  const root = {};
  const stack = [{ indent: -1, node: root }];
  for (const raw of lines) {
    const line = raw.replace(/\s+$/, "");
    if (!line || line.trim().startsWith("#")) continue;
    const indent = line.length - line.trimStart().length;
    const trimmed = line.trim();
    while (stack.length > 1 && stack[stack.length - 1].indent >= indent) stack.pop();
    const parent = stack[stack.length - 1].node;
    if (trimmed.startsWith("- ")) {
      const value = trimmed.slice(2).trim();
      if (!Array.isArray(parent)) continue;
      if (value.includes(": ")) {
        const obj = {};
        const [k, ...rest] = value.split(": ");
        obj[k.trim()] = parseScalar(rest.join(": ").trim());
        parent.push(obj);
        stack.push({ indent: indent + 2, node: obj });
      } else {
        parent.push(parseScalar(value));
      }
      continue;
    }
    if (trimmed.includes(": ")) {
      const idx = trimmed.indexOf(": ");
      const key = trimmed.slice(0, idx).trim();
      const value = trimmed.slice(idx + 2).trim();
      if (value === "") {
        const child = {};
        parent[key] = child;
        stack.push({ indent: indent + 2, node: child });
      } else if (value === "[]") {
        parent[key] = [];
      } else if (value === "{}") {
        parent[key] = {};
      } else {
        parent[key] = parseScalar(value);
      }
    } else if (trimmed.endsWith(":")) {
      const key = trimmed.slice(0, -1).trim();
      const child = {};
      parent[key] = child;
      stack.push({ indent: indent + 2, node: child });
    }
  }
  return root;
}

function parseScalar(raw) {
  if (raw === "null" || raw === "~") return null;
  if (raw === "true") return true;
  if (raw === "false") return false;
  if (/^-?\d+$/.test(raw)) return parseInt(raw, 10);
  if (/^-?\d+\.\d+$/.test(raw)) return parseFloat(raw);
  if ((raw.startsWith('"') && raw.endsWith('"')) || (raw.startsWith("'") && raw.endsWith("'"))) {
    return raw.slice(1, -1);
  }
  return raw;
}

// ============================================================================
// Renderers
// ============================================================================

function renderState(state) {
  $("#flowid").textContent = state.flowid;
  $("#phase").textContent = `Phase: ${state.phase}`;
  $("#version").textContent = `v${state.version}`;

  // State summary
  const stateHtml = [
    { label: "Flow ID", value: state.flowid },
    { label: "Phase", value: state.phase },
    { label: "Version", value: state.version },
    { label: "Tokens", value: state.tokens_consumed_total ?? 0 },
    { label: "Tools absorbidas", value: (state.tools_absorbed ?? []).length },
    { label: "Hints activos", value: (state.operator_hints ?? []).filter(h => !h.resolved).length },
  ].map(r => `<div><span class="label">${r.label}</span><span class="value">${r.value}</span></div>`).join("");
  $("#state-summary").innerHTML = stateHtml;

  // Loops
  if (state.loops) {
    const loopsHtml = Object.entries(state.loops).map(([phase, c]) => {
      const counter = c;
      const pct = (counter.current / counter.max) * 100;
      const color = pct >= 100 ? "var(--critical)" : pct >= 50 ? "var(--warn)" : "var(--success)";
      return `<div>
        <span class="label">${phase}</span>
        <span class="value" style="color:${color}">${counter.current}/${counter.max}</span>
      </div>`;
    }).join("");
    $("#loops-grid").innerHTML = loopsHtml;
  }
}

function renderTelemetry(events) {
  if (!events.length) {
    $("#metrics").innerHTML = "<div>Sin eventos</div>";
    return;
  }

  // Stats
  const stats = {
    total: events.length,
    tokens: events.reduce((a, e) => a + (e.tokens || 0), 0),
    duration_ms: events.reduce((a, e) => a + (e.duration_ms || 0), 0),
    blocks_detected: events.filter(e => e.kind === "block-detected").length,
    tests_run: events.filter(e => e.kind === "test-run").length,
    tests_failed: events.filter(e => e.kind === "test-fail").length,
    rollbacks: events.filter(e => e.kind === "rollback").length,
    tools_absorbed: events.filter(e => e.kind === "tool-absorbed").length,
  };

  const metricsHtml = [
    { label: "Total eventos", value: stats.total },
    { label: "Tokens", value: stats.tokens.toLocaleString() },
    { label: "Duración total (ms)", value: stats.duration_ms.toLocaleString() },
    { label: "Bloqueos", value: stats.blocks_detected },
    { label: "Tests run", value: stats.tests_run },
    { label: "Tests fail", value: stats.tests_failed },
    { label: "Rollbacks", value: stats.rollbacks },
    { label: "Tools absorbed", value: stats.tools_absorbed },
  ].map(r => `<div><span class="label">${r.label}</span><span class="value">${r.value}</span></div>`).join("");
  $("#metrics").innerHTML = metricsHtml;

  // Phase chart
  const phaseDurations = {};
  events.forEach(e => {
    if (e.duration_ms) {
      phaseDurations[e.phase] = (phaseDurations[e.phase] || 0) + e.duration_ms;
    }
  });
  const maxPhase = Math.max(...Object.values(phaseDurations), 1);
  const phaseChartHtml = Object.entries(phaseDurations)
    .sort((a, b) => b[1] - a[1])
    .map(([phase, ms]) => `
      <div class="bar-row">
        <span class="bar-label">${phase}</span>
        <div class="bar-track"><div class="bar-fill" style="width: ${(ms / maxPhase) * 100}%"></div></div>
        <span class="bar-value">${ms}ms</span>
      </div>
    `).join("");
  $("#phase-chart").innerHTML = phaseChartHtml || "<div>Sin datos</div>";

  // Kind chart
  const kindCount = {};
  events.forEach(e => { kindCount[e.kind] = (kindCount[e.kind] || 0) + 1; });
  const maxKind = Math.max(...Object.values(kindCount), 1);
  const kindChartHtml = Object.entries(kindCount)
    .sort((a, b) => b[1] - a[1])
    .map(([kind, n]) => `
      <div class="bar-row">
        <span class="bar-label">${kind}</span>
        <div class="bar-track"><div class="bar-fill" style="width: ${(n / maxKind) * 100}%"></div></div>
        <span class="bar-value">${n}</span>
      </div>
    `).join("");
  $("#kind-chart").innerHTML = kindChartHtml;

  // Timeline table
  const last100 = events.slice(-100).reverse();
  const timelineHtml = last100.map(e => `
    <tr>
      <td>${e.at?.slice(11, 19) ?? "?"}</td>
      <td>${e.kind}</td>
      <td>${e.phase}</td>
      <td class="severity-${e.severity}">${e.severity}</td>
      <td>${escapeHtml(e.message || "")}</td>
    </tr>
  `).join("");
  $("#timeline-table tbody").innerHTML = timelineHtml;

  // Tokens
  $("#tokens-stats").innerHTML = `
    <div class="total">${stats.tokens.toLocaleString()}</div>
    <div>tokens consumidos en ${stats.total} eventos</div>
    <div style="margin-top:8px;color:var(--text-dim)">Promedio: ${Math.round(stats.tokens / Math.max(stats.total, 1))} tokens/evento</div>
  `;

  // Tests list
  const testEvents = events.filter(e => e.kind === "test-run" || e.kind === "test-fail").slice(-20).reverse();
  const testsHtml = testEvents.map(e => {
    const summary = e.payload?.summary;
    const cls = e.kind === "test-fail" ? "fail" : "";
    return `<div class="test-run ${cls}">
      <div class="header">
        <span><strong>${e.payload?.trigger || "?"}</strong> / ${e.payload?.kind || "?"}</span>
        <span>${e.at?.slice(11, 19) ?? "?"}</span>
      </div>
      <div>${summary ? `pass=${summary.passed}/${summary.total}` : escapeHtml(e.message || "")}</div>
      ${e.payload?.rollback_triggered ? '<div style="color:var(--warn);margin-top:4px">⚠ rollback triggered</div>' : ""}
    </div>`;
  }).join("");
  $("#tests-list").innerHTML = testsHtml || "<div>Sin runs de tests</div>";
}

function renderBlocks(blocksData) {
  const blocks = (blocksData.blocks || []).filter(b => b.status === "active");
  if (!blocks.length) {
    $("#blocks-list").innerHTML = "<div>Sin bloqueos activos ✓</div>";
    return;
  }
  const html = blocks.map(b => `
    <div class="block ${b.severity === "soft" ? "soft" : ""}">
      <div class="id">${b.id} [${b.severity}] ${b.kind} @ ${b.phase}</div>
      <div class="desc">${escapeHtml(b.description || "")}</div>
      ${b.suggested_resolution ? `<div class="suggested">→ ${escapeHtml(b.suggested_resolution)}</div>` : ""}
    </div>
  `).join("");
  $("#blocks-list").innerHTML = html;
}

function renderTools(registry) {
  const tools = registry.tools || [];
  const html = tools.map(t => `
    <tr>
      <td class="status-${t.status}">${t.status}</td>
      <td>${t.id}</td>
      <td>${t.kind}</td>
      <td>${(t.capabilities || []).join(", ")}</td>
    </tr>
  `).join("");
  $("#tools-table tbody").innerHTML = html;
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
