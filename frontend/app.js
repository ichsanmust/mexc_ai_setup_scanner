const API_BASE = "";
const JAKARTA_TZ = "Asia/Jakarta";

function parseBackendUtcDate(val) {
  if (!val) return null;
  if (val instanceof Date) return Number.isNaN(val.getTime()) ? null : val;
  if (typeof val === "number") {
    const d = new Date(val);
    return Number.isNaN(d.getTime()) ? null : d;
  }
  const raw = String(val).trim();
  if (!raw) return null;
  const hasTz = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(raw);
  const d = new Date(hasTz ? raw : `${raw}Z`);
  return Number.isNaN(d.getTime()) ? null : d;
}

function formatJakartaDateTime(val, withSeconds = false) {
  const d = parseBackendUtcDate(val);
  if (!d) return "-";
  const opts = {
    timeZone: JAKARTA_TZ,
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  };
  if (withSeconds) opts.second = "2-digit";
  return `${d.toLocaleString("id-ID", opts).replace(/\./g, ":")} WIB`;
}

function formatJakartaTime(val = new Date(), withSeconds = true) {
  const d = parseBackendUtcDate(val);
  if (!d) return "-";
  const opts = {
    timeZone: JAKARTA_TZ,
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  };
  if (withSeconds) opts.second = "2-digit";
  return `${d.toLocaleTimeString("en-GB", opts)} WIB`;
}

function formatChartJakartaTime(time) {
  if (typeof time !== "number" || !Number.isFinite(time)) return String(time || "");
  return formatJakartaDateTime(time * 1000, false);
}

function formatChartJakartaTickMark(time, tickMarkType) {
  if (typeof time !== "number" || !Number.isFinite(time)) return String(time || "");
  const d = new Date(time * 1000);
  if (tickMarkType === 0) {
    return d.toLocaleString("en-GB", { timeZone: JAKARTA_TZ, year: "numeric" });
  }
  if (tickMarkType === 1) {
    return d.toLocaleString("id-ID", { timeZone: JAKARTA_TZ, month: "short", year: "2-digit" });
  }
  if (tickMarkType === 2) {
    return d.toLocaleString("id-ID", { timeZone: JAKARTA_TZ, day: "2-digit", month: "short" });
  }
  if (tickMarkType === 4) {
    return d.toLocaleTimeString("en-GB", {
      timeZone: JAKARTA_TZ,
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
  }
  return d.toLocaleTimeString("en-GB", {
    timeZone: JAKARTA_TZ,
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

async function apiRequest(endpoint, options = {}) {
  const headers = { ...options.headers };
  if (options.body && !(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }

  const resp = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers,
    referrerPolicy: "no-referrer",
  });

  if (resp.status === 204) return null;
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    let errorMsg = `HTTP ${resp.status}`;
    if (typeof data.detail === "string") {
      errorMsg = data.detail;
    } else if (Array.isArray(data.detail)) {
      errorMsg = data.detail
        .map((err) => `${err.loc ? err.loc.slice(1).join(".") : "field"}: ${err.msg}`)
        .join("; ");
    } else if (data.detail && typeof data.detail === "object") {
      errorMsg = data.detail.message || JSON.stringify(data.detail);
    } else if (data.message) {
      errorMsg = data.message;
    }
    throw new Error(errorMsg);
  }
  return data;
}

const state = {
  statusFilter: "ALL",
  selectedSetup: null,
  chartInterval: "Min15",
  drawMode: "normal",
  drawnPositions: [],
  setupBox: null,
  activePositionId: null,
  nextPositionSeq: 1,
  chartBarsCount: 300,
  chartCandles: [],
  overlayRafPending: false,
  lastVolumeToggle: null,
  lastCandleTime: null,
  setups: [],
  setupsPage: 1,
  setupsPageSize: 20,
  setupsTotal: 0,
  runsPage: 1,
  runsPageSize: 10,
  runsTotal: 0,
  strategies: [],
  aiModels: [],
  aiSettings: null,
  evalFilter: "ALL",
  evalRows: [],
  chart: null,
  chartRefreshing: false,
  renderedSetupId: null,
  renderedInterval: null,
  liveChartTimer: null,
  candleSeries: null,
  volumeSeries: null,
  ema21Series: null,
  ema50Series: null,
  ema200Series: null,
  dssChart: null,
  dssSeries: null,
  dssSignalSeries: null,
  dssByTime: {},
  latestDssMain: null,
  latestDssSig: null,
  syncingTimeRange: false,
  priceLines: [],
  strategyChart: null,
};

function showErrorBanner(title, message) {
  const banner = document.getElementById("system-error-banner");
  document.getElementById("error-banner-title").textContent = title;
  document.getElementById("error-banner-msg").textContent = message;
  banner.classList.remove("hidden");
}

function hideErrorBanner() {
  document.getElementById("system-error-banner").classList.add("hidden");
}

function showToast(msg, isError = false) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.style.borderColor = isError ? "#ef4444" : "#3b82f6";
  el.classList.remove("hidden");
  setTimeout(() => el.classList.add("hidden"), 4500);
}

function fmtPrice(val) {
  if (val === null || val === undefined) return "-";
  const num = Number(val);
  if (num >= 1000) return num.toLocaleString("en-US", { maximumFractionDigits: 2 });
  if (num >= 1) return num.toLocaleString("en-US", { maximumFractionDigits: 4 });
  return num.toLocaleString("en-US", { maximumFractionDigits: 8 });
}

function statusBadge(setupOrStatus, manualActionAt = null) {
  const s =
    setupOrStatus && typeof setupOrStatus === "object"
      ? setupOrStatus
      : { status: setupOrStatus, manual_action_at: manualActionAt };
  const st = s.status;
  const map = {
    OPEN: { cls: "badge-open", tip: "Setup aktif dipantau otomatis oleh Tracker ke harga live MEXC" },
    ENTRY_HIT: { cls: "badge-entry-hit", tip: "Otomatis dari Tracker: harga pasar sudah menyentuh Entry, sedang menuju TP/SL" },
    HIT_TP: { cls: "badge-hit-tp", tip: "Harga menyentuh Take Profit terlebih dahulu (Win)" },
    HIT_SL: { cls: "badge-hit-sl", tip: "Harga menyentuh Stop Loss terlebih dahulu (Loss)" },
    EXPIRED: { cls: "badge-expired", tip: "Melewati batas Setup Expiry tanpa menyentuh TP/SL" },
    MANUAL_TAKEN: { cls: "badge-manual", tip: "Order dieksekusi manual & tetap dipantau otomatis ke TP/SL/Expired" },
    MANUAL_SKIPPED: { cls: "badge-neutral", tip: "Ditandai manual oleh user untuk dilewati (tidak diambil)" },
    CLOSED_MANUAL_TP: { cls: "badge-hit-tp", tip: "Posisi ditutup manual dengan Take Profit" },
    CLOSED_MANUAL_CL: { cls: "badge-hit-sl", tip: "Posisi ditutup manual dengan Cut Loss" },
  };
  const info = map[st] || { cls: "badge-neutral", tip: st };
  const tags = [`<span class="badge ${info.cls}" title="${info.tip}">${st}</span>`];

  if (s.entry_hit_at && st !== "OPEN" && st !== "ENTRY_HIT") {
    const entryAtStr = formatJakartaDateTime(s.entry_hit_at);
    tags.push(`<span class="badge badge-entry-hit" title="Sempat menyentuh Entry pada ${escapeHtml(entryAtStr)}">ENTRY</span>`);
  }
  if (!s.entry_hit_at && !s.manual_action_at && st === "HIT_SL") {
    tags.push(`<span class="badge badge-expired" title="Harga jebol SL sebelum menyentuh Limit Entry">NO ENTRY</span>`);
  }
  if (s.missed_tp_at && !s.entry_hit_at) {
    const tpPx = s.missed_tp_price ? fmtPrice(s.missed_tp_price) : "-";
    const tpAtStr = formatJakartaDateTime(s.missed_tp_at);
    tags.push(`<span class="badge badge-missed-tp" title="Harga menembus TP (${tpPx}) pada ${escapeHtml(tpAtStr)} tanpa menyentuh Limit Entry">TP NO ENTRY</span>`);
  }
  if (s.manual_action_at && (st === "HIT_TP" || st === "HIT_SL" || st === "EXPIRED" || st === "CLOSED_MANUAL_TP" || st === "CLOSED_MANUAL_CL")) {
    tags.push(`<span class="badge badge-manual" title="Setup ini sempat ditandai Taken manual">TAKEN</span>`);
  }
  return `<div style="display:flex; flex-wrap:wrap; gap:4px;">${tags.join("")}</div>`;
}

async function loadHealthAndStatus() {
  const [health, scannerStatus] = await Promise.all([
    apiRequest("/api/health"),
    apiRequest("/api/scanner/status"),
    loadScanRuns(),
  ]);

  const pill = document.getElementById("active-llm-pill");
  const label = document.getElementById("active-llm-label");
  label.textContent = `${health.active_provider} • ${health.active_model_id}${health.has_api_key ? "" : " (No API Key)"}`;
  pill.classList.toggle("warn", !health.has_api_key);

  const badge = document.getElementById("scanner-status-badge");
  const latestRun = scannerStatus.recent_runs && scannerStatus.recent_runs[0];
  const failedSummary = scannerStatus.last_run_summary && scannerStatus.last_run_summary.status === "FAILED"
    ? scannerStatus.last_run_summary
    : null;
  const failedRun = latestRun && latestRun.status === "FAILED" ? latestRun : null;

  renderScanRuns(scannerStatus);

  const trackerBtn = document.getElementById("btn-run-tracker");
  const trackerSec = scannerStatus.tracker_interval_seconds || 60;
  trackerBtn.textContent = `Check Outcomes (Auto: ${trackerSec}s)`;
  trackerBtn.title = `Tracker berjalan otomatis setiap ${trackerSec} detik untuk mengecek TP/SL/Expired setup OPEN. Klik untuk cek sekarang.`;

  badge.className = "badge";
  if (scannerStatus.is_running) {
    badge.classList.add("badge-open");
    badge.textContent = "Scanning...";
    badge.title = "";
  } else if (failedSummary || failedRun) {
    badge.classList.add("badge-hit-sl");
    badge.textContent = "Last Scan Failed";
    const errText = (failedSummary && failedSummary.error) || (failedRun && failedRun.error_message) || "Scan failed";
    const runId = (failedSummary && failedSummary.scan_run_id) || (failedRun && failedRun.id) || "-";
    badge.title = errText;
    showErrorBanner(`Scan Cycle #${runId} Gagal (${scannerStatus.mexc_base_url || "MEXC"})`, errText);
  } else if (latestRun && latestRun.error_message) {
    badge.classList.add("badge-expired");
    badge.textContent = "Scan Warning";
    badge.title = latestRun.error_message;
    showErrorBanner(`Scan Cycle #${latestRun.id} Selesai dengan Peringatan`, latestRun.error_message);
  } else if (scannerStatus.last_tracker_error) {
    badge.classList.add("badge-expired");
    badge.textContent = "Tracker Warning";
    badge.title = scannerStatus.last_tracker_error;
    showErrorBanner("Outcome Tracker Error", scannerStatus.last_tracker_error);
  } else {
    badge.classList.add("badge-neutral");
    badge.textContent = scannerStatus.auto_scan_enabled
      ? `Auto (${scannerStatus.scan_interval_minutes}m)`
      : "Manual Mode";
    badge.title = "";
    hideErrorBanner();
  }
  return scannerStatus;
}

function updatePaginationUI(prefix, page, pageSize, total) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const summaryEl = document.getElementById(`${prefix}-page-summary`);
  const infoEl = document.getElementById(`${prefix}-page-info`);
  const prevBtn = document.getElementById(`btn-${prefix}-prev`);
  const nextBtn = document.getElementById(`btn-${prefix}-next`);

  if (summaryEl) {
    if (total === 0) {
      summaryEl.textContent = "0 data";
    } else {
      const start = (page - 1) * pageSize + 1;
      const end = Math.min(total, page * pageSize);
      summaryEl.textContent = `${start}–${end} dari ${total}`;
    }
  }
  if (infoEl) infoEl.textContent = `Hal ${page} / ${totalPages}`;
  if (prevBtn) prevBtn.disabled = page <= 1;
  if (nextBtn) nextBtn.disabled = page >= totalPages;
}

async function loadScanRuns() {
  const offset = (state.runsPage - 1) * state.runsPageSize;
  let data = await apiRequest(`/api/scanner/runs?limit=${state.runsPageSize}&offset=${offset}`);
  state.runsTotal = data.total || 0;
  const maxPage = Math.max(1, Math.ceil(state.runsTotal / state.runsPageSize));
  if (state.runsPage > maxPage) {
    state.runsPage = maxPage;
    data = await apiRequest(
      `/api/scanner/runs?limit=${state.runsPageSize}&offset=${(state.runsPage - 1) * state.runsPageSize}`
    );
  }
  renderScanRunsList(data.items || []);
  updatePaginationUI("runs", state.runsPage, state.runsPageSize, state.runsTotal);
}

function renderScanRuns(scannerStatus) {
  const meta = document.getElementById("scan-runs-meta");
  const modeText = scannerStatus.auto_scan_enabled
    ? `AUTO (${scannerStatus.scan_interval_minutes}m)`
    : "MANUAL";
  meta.textContent = `Mode: ${modeText} • Top ${scannerStatus.top_n_pairs} Pairs • MEXC: ${scannerStatus.mexc_base_url || "-"}`;
}

function formatStrategyProfilesSummary(cfg, fallbackStrategy = "") {
  const tfMap = cfg && cfg.strategy_timeframes && typeof cfg.strategy_timeframes === "object"
    ? cfg.strategy_timeframes
    : null;
  if (tfMap && Object.keys(tfMap).length) {
    return Object.entries(tfMap)
      .map(([name, p]) => `${name} (${p.htf || "-"}/${p.ltf || "-"} • ${p.kline_limit || "-"}b • ${p.expiry_hours || "-"}j)`)
      .join(", ");
  }
  if (cfg && (cfg.htf_interval || cfg.ltf_interval)) {
    const strats = (cfg.active_strategies || []).join(", ") || fallbackStrategy || "-";
    return `${cfg.htf_interval || "-"} / ${cfg.ltf_interval || "-"} • Candles ${cfg.kline_limit || "-"} • ${strats}`;
  }
  return (cfg && Array.isArray(cfg.active_strategies) && cfg.active_strategies.join(", ")) || fallbackStrategy || "-";
}

function renderScanRunsList(runs) {
  const list = document.getElementById("scan-runs-list");
  if (!runs.length) {
    list.innerHTML = `<div class="subtitle-sm">Belum ada riwayat scan.</div>`;
    return;
  }

  list.innerHTML = runs
    .map((r) => {
      const cls = r.status === "FAILED" ? "failed" : "";
      const stBadge =
        r.status === "COMPLETED"
          ? "badge-hit-tp"
          : r.status === "FAILED"
            ? "badge-hit-sl"
            : "badge-open";
      const timeStr = r.started_at ? formatJakartaDateTime(r.started_at) : "-";
      const hasErr = Boolean(r.error_message);
      const errBadge = hasErr
        ? `<span class="badge ${r.status === "FAILED" ? "badge-hit-sl" : "badge-expired"}">Ada Info Error</span>`
        : `<span></span>`;
      const cfg = r.settings_snapshot || null;
      const cfgLine = cfg
        ? `<div class="subtitle-sm">${escapeHtml(formatStrategyProfilesSummary(cfg, r.strategy))}</div>`
        : `<div class="subtitle-sm">Strategi: ${escapeHtml(r.strategy || "-")}</div>`;
      return `
        <div class="scan-run-chip ${cls}">
          <div class="run-top">
            <strong><button type="button" class="run-id-chip" data-eval-run="${r.id}" title="Lihat detail &amp; settingan Scan Run #${r.id}">#${r.id}</button> &bull; ${timeStr}</strong>
            <span class="badge ${stBadge}">${r.status}</span>
          </div>
          <div class="subtitle-sm">Pair: ${r.top_pairs_count} | Pre: ${r.prefiltered_count} | AI: ${r.ai_analyzed_count} | Setup: <b>${r.setups_created_count}</b></div>
          ${cfgLine}
          <div class="scan-run-footer">
            ${errBadge}
            <button type="button" class="btn btn-secondary btn-sm" data-eval-run="${r.id}">Detail Evaluasi</button>
          </div>
        </div>`;
    })
    .join("");

  list.querySelectorAll("button[data-eval-run]").forEach((btn) => {
    btn.addEventListener("click", () => openScanEvaluationsModal(Number(btn.dataset.evalRun)));
  });
}

function buildScanSettingsHtml(cfg, fallbackStrategy) {
  if (!cfg) {
    return `<div><strong>Strategi:</strong> <code>${escapeHtml(fallbackStrategy || "-")}</code> <span class="subtitle-sm">(scan lama sebelum pencatatan snapshot setting)</span></div>`;
  }
  const stratLabel = Array.isArray(cfg.active_strategies) && cfg.active_strategies.length
    ? cfg.active_strategies.join(", ")
    : fallbackStrategy || "-";
  const maxVolStr = Number(cfg.max_24h_quote_volume || 0) > 0
    ? `$${Number(cfg.max_24h_quote_volume).toLocaleString("en-US")}`
    : "Unlimited";
  return `
    <div class="eval-settings-box">
      <div><strong>Settingan Scan Dipakai:</strong> Mode <b>${escapeHtml(cfg.scan_mode || "-")}</b> &bull; Top N: <b>${cfg.top_n_pairs ?? "-"}</b> &bull; Interval Scan: <b>${cfg.scan_interval_minutes ?? "-"}m</b> &bull; Tracker: <b>${cfg.tracker_interval_seconds ?? "-"}s</b> &bull; Strategi: <code>${escapeHtml(stratLabel)}</code></div>
      <div><strong>Profil Per-Strategi:</strong> <code>${escapeHtml(formatStrategyProfilesSummary(cfg, fallbackStrategy))}</code></div>
      <div><strong>Filter &amp; Risk:</strong> Vol 24h: <b>$${Number(cfg.min_24h_quote_volume || 0).toLocaleString("en-US")}</b> – <b>${maxVolStr}</b> &bull; ATR: <b>${cfg.min_atr_pct ?? "-"}%–${cfg.max_atr_pct ?? "-"}%</b> &bull; Min Conf: <b>${cfg.min_confidence ?? "-"}%</b> &bull; MEXC: <code>${escapeHtml(cfg.mexc_base_url || "-")}</code> &bull; LLM: Timeout ${cfg.llm_timeout_seconds ?? "-"}s / Concurrency ${cfg.llm_max_concurrency ?? "-"} / MaxTok ${cfg.llm_max_tokens ?? "-"}</div>
    </div>`;
}

function resolveSetupStrategyMeta(setup) {
  const sp = setup.strategy_profile || {};
  const stratObj = (state.strategies || []).find(
    (x) => String(x.name || "").toUpperCase() === String(setup.strategy_used || "").toUpperCase()
  );
  const runTfs = setup.scan_run_settings?.strategy_timeframes || {};
  const runProf = runTfs[setup.strategy_used] || runTfs[String(setup.strategy_used || "").toUpperCase()] || {};
  return {
    holdingPeriod: setup.holding_period || sp.holding_period || stratObj?.holding_period || null,
    tradeStyle: sp.trade_style || stratObj?.trade_style || null,
    htf: runProf.htf || sp.htf || stratObj?.suggested_htf || null,
    ltf: runProf.ltf || sp.ltf || stratObj?.suggested_ltf || null,
    klineLimit: runProf.kline_limit || sp.kline_limit || stratObj?.suggested_kline_limit || null,
    expiryHours: runProf.expiry_hours || sp.expiry_hours || stratObj?.suggested_expiry_hours || null,
  };
}

async function openScanEvaluationsModal(runId) {
  const modal = document.getElementById("scan-eval-modal");
  modal.classList.remove("hidden");
  document.getElementById("eval-modal-title").textContent = `Detail Evaluasi Scan #${runId}`;
  document.getElementById("eval-modal-summary").textContent = "Memuat data evaluasi...";
  document.getElementById("eval-modal-tbody").innerHTML =
    `<tr><td colspan="5" class="empty-cell">Memuat...</td></tr>`;

  try {
    const data = await apiRequest(`/api/scanner/runs/${runId}/evaluations`);
    const r = data.run;
    const cfg = r.settings_snapshot || null;
    const settingsHtml = buildScanSettingsHtml(cfg, r.strategy);
    const setupNames = (data.setups || []).map((s) => `${s.symbol} (${s.decision} ${s.strategy_used})`).join(", ");
    const startedTxt = r.started_at ? formatJakartaDateTime(r.started_at, true) : "-";
    const finishedTxt = r.finished_at ? formatJakartaDateTime(r.finished_at, true) : "-";
    document.getElementById("eval-modal-summary").innerHTML = `
      <div><strong>Status:</strong> ${r.status} &bull; <strong>Model:</strong> ${escapeHtml(r.llm_provider || "-")} / ${escapeHtml(r.llm_model || "-")}</div>
      <div><strong>Waktu:</strong> Mulai ${escapeHtml(startedTxt)} &bull; Selesai ${escapeHtml(finishedTxt)}</div>
      <div><strong>Ringkasan:</strong> Top Pair: ${r.top_pairs_count} | Lolos Pre-filter: ${r.prefiltered_count} | Dianalisis AI: ${r.ai_analyzed_count} | Setup Masuk: <b>${r.setups_created_count}</b></div>
      ${settingsHtml}
      ${setupNames ? `<div><strong>Setup Terbuat:</strong> ${escapeHtml(setupNames)}</div>` : ""}
      ${r.error_message ? `<div class="text-red"><strong>Error:</strong> ${escapeHtml(r.error_message)}</div>` : ""}
    `;
    const setupRows = (data.setups || []).map((s) => ({
      is_setup: true,
      setup_obj: s,
      symbol: s.symbol,
      strategy_used: s.strategy_used,
      raw_decision: s.decision,
      confidence: s.confidence,
      rejection_reason: `MASUK SETUP (${s.status}) • E: ${fmtPrice(s.entry_price)} | SL: ${fmtPrice(s.stop_loss)} | TP: ${fmtPrice(s.take_profit)} | R:R ${Number(s.risk_reward_ratio).toFixed(2)} — ${s.rationale}`,
    }));
    const evalOnlyRows = (data.evaluations || []).map((e) => ({ ...e, is_setup: false }));
    state.evalRows = [...setupRows, ...evalOnlyRows];
    state.evalFilter = "ALL";
    document.querySelectorAll("#eval-filter-tabs .tab").forEach((b) => {
      b.classList.toggle("active", b.dataset.evalFilter === "ALL");
    });
    renderEvalTable();
  } catch (err) {
    document.getElementById("eval-modal-summary").textContent = err.message;
    document.getElementById("eval-modal-tbody").innerHTML =
      `<tr><td colspan="5" class="empty-cell">Gagal memuat detail evaluasi.</td></tr>`;
  }
}

function renderEvalTable() {
  const filtered = state.evalRows.filter((e) => {
    if (state.evalFilter === "ALL") return true;
    if (state.evalFilter === "SETUP") return e.is_setup === true;
    if (e.is_setup) return false;
    if (state.evalFilter === "REJECTED") {
      return e.raw_decision === "LONG" || e.raw_decision === "SHORT";
    }
    return e.raw_decision === state.evalFilter;
  });

  const tbody = document.getElementById("eval-modal-tbody");
  if (!filtered.length) {
    tbody.innerHTML = `<tr><td colspan="5" class="empty-cell">Tidak ada catatan evaluasi untuk filter ini.</td></tr>`;
    return;
  }
  tbody.innerHTML = filtered
    .map((e) => {
      const badgeCls = e.is_setup
        ? e.raw_decision === "LONG"
          ? "badge-long"
          : "badge-short"
        : e.raw_decision === "ERROR"
          ? "badge-hit-sl"
          : "badge-neutral";
      const setupTag = e.is_setup ? ' <span class="badge badge-hit-tp">SETUP</span>' : "";
      const rowCls = e.is_setup ? ' class="active-model-row"' : "";
      return `
      <tr${rowCls}${e.is_setup ? ` data-eval-setup-id="${e.setup_obj.id}" title="Klik untuk lihat chart setup ini"` : ""}>
        <td><strong>${e.symbol}</strong></td>
        <td>${e.strategy_used}</td>
        <td><span class="badge ${badgeCls}">${e.raw_decision}</span>${setupTag}</td>
        <td>${e.confidence !== null && e.confidence !== undefined ? `${e.confidence}%` : "-"}</td>
        <td>${e.rejection_reason}</td>
      </tr>`;
    })
    .join("");

  tbody.querySelectorAll("tr[data-eval-setup-id]").forEach((tr) => {
    tr.addEventListener("click", () => {
      const sid = Number(tr.dataset.evalSetupId);
      const found = state.evalRows.find((r) => r.is_setup && r.setup_obj.id === sid);
      if (found) {
        document.getElementById("scan-eval-modal").classList.add("hidden");
        selectSetup(found.setup_obj);
      }
    });
  });
}

async function loadAnalytics() {
  const data = await apiRequest("/api/analytics/strategies");
  document.getElementById("kpi-total").textContent = data.total_setups;
  document.getElementById("kpi-open").textContent = data.open_count;
  document.getElementById("kpi-winrate").textContent = `${data.overall_win_rate_pct}%`;
  document.getElementById("kpi-rr").textContent = data.overall_avg_rr.toFixed(2);

  const miniGrid = document.getElementById("strategy-cards");
  miniGrid.innerHTML = data.strategies
    .map(
      (s) => `
      <div class="strategy-mini-item">
        <strong>${s.strategy_used}</strong>
        <div>Total: ${s.total_setups} | Win Rate: <b>${s.win_rate_pct}%</b></div>
        <div>TP: ${s.hit_tp_count} / SL: ${s.hit_sl_count} / Avg R:R ${s.avg_rr}</div>
      </div>`
    )
    .join("");

  const ctx = document.getElementById("strategyChart").getContext("2d");
  if (state.strategyChart) state.strategyChart.destroy();
  state.strategyChart = new Chart(ctx, {
    type: "bar",
    data: {
      labels: data.strategies.map((s) => s.strategy_used),
      datasets: [
        { label: "HIT_TP", data: data.strategies.map((s) => s.hit_tp_count), backgroundColor: "#42b72a" },
        { label: "HIT_SL", data: data.strategies.map((s) => s.hit_sl_count), backgroundColor: "#e41e3f" },
        { label: "OPEN", data: data.strategies.map((s) => s.open_count), backgroundColor: "#1877f2" },
        { label: "EXPIRED", data: data.strategies.map((s) => s.expired_count), backgroundColor: "#f59e0b" },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { labels: { color: "#050505", boxWidth: 12 } } },
      scales: {
        x: { ticks: { color: "#65676b" }, grid: { color: "#e4e6eb" } },
        y: { beginAtZero: true, ticks: { color: "#65676b", precision: 0 }, grid: { color: "#e4e6eb" } },
      },
    },
  });
}

async function loadSetups() {
  const params = new URLSearchParams();
  if (state.statusFilter !== "ALL") params.set("status", state.statusFilter);
  const strat = document.getElementById("filter-strategy").value;
  if (strat !== "ALL") params.set("strategy", strat);
  const sym = document.getElementById("filter-symbol").value.trim();
  if (sym) params.set("symbol", sym);
  const dateVal = document.getElementById("filter-date").value;
  if (dateVal) {
    params.set("date", dateVal);
    params.set("tz_offset", "-420");
  }

  params.set("limit", String(state.setupsPageSize));
  params.set("offset", String((state.setupsPage - 1) * state.setupsPageSize));

  let data = await apiRequest(`/api/setups?${params.toString()}`);
  state.setupsTotal = data.total || 0;
  const maxPage = Math.max(1, Math.ceil(state.setupsTotal / state.setupsPageSize));
  if (state.setupsPage > maxPage) {
    state.setupsPage = maxPage;
    params.set("offset", String((state.setupsPage - 1) * state.setupsPageSize));
    data = await apiRequest(`/api/setups?${params.toString()}`);
  }
  state.setups = data.items;
  updatePaginationUI("setups", state.setupsPage, state.setupsPageSize, state.setupsTotal);

  const tbody = document.getElementById("setups-tbody");
  if (!data.items.length) {
    tbody.innerHTML = `<tr><td colspan="8" class="empty-cell">Belum ada setup untuk filter ini.</td></tr>`;
    return;
  }

  tbody.innerHTML = data.items
    .map((s) => {
      const selectedCls = state.selectedSetup && state.selectedSetup.id === s.id ? "selected" : "";
      const dirBadge = s.decision === "LONG" ? "badge-long" : "badge-short";
      const meLine = s.manual_entry_price ? `<div class="text-accent">ME: ${fmtPrice(s.manual_entry_price)}</div>` : "";
      const closeLine = s.resolved_price ? `<div>Close: ${fmtPrice(s.resolved_price)}</div>` : "";
      const meta = resolveSetupStrategyMeta(s);
      const holdHtml = meta.holdingPeriod
        ? `<div class="subtitle-sm">Lama: <b>${escapeHtml(meta.holdingPeriod)}</b></div>`
        : "";
      const tfParts = [];
      if (meta.htf || meta.ltf) tfParts.push(`${meta.htf || "-"}/${meta.ltf || "-"}`);
      if (meta.klineLimit) tfParts.push(`${meta.klineLimit}b`);
      if (meta.expiryHours) tfParts.push(`Exp ${meta.expiryHours}j`);
      const runChip = s.scan_run_id
        ? ` <button type="button" class="run-id-chip" data-open-run="${s.scan_run_id}" title="Klik untuk melihat detail &amp; settingan Scan Run #${s.scan_run_id}">Run #${s.scan_run_id}</button>`
        : "";
      const tfLine =
        tfParts.length || runChip
          ? `<div class="subtitle-sm">${escapeHtml(tfParts.join(" \u2022 "))}${runChip}</div>`
          : "";
      return `
        <tr class="${selectedCls}" data-id="${s.id}">
          <td><strong>${s.symbol}</strong><br><small class="subtitle-sm">${formatJakartaDateTime(s.created_at)}</small></td>
          <td><span class="badge ${dirBadge}">${s.decision}</span></td>
          <td>
            <strong>${escapeHtml(s.strategy_used)}</strong>
            ${holdHtml}
            ${tfLine}
          </td>
          <td>
            <div>E: ${fmtPrice(s.entry_price)}</div>
            ${meLine}
            <div class="text-red">SL: ${fmtPrice(s.stop_loss)}</div>
            <div class="text-green">TP: ${fmtPrice(s.take_profit)}</div>
            ${closeLine}
          </td>
          <td>${Number(s.risk_reward_ratio).toFixed(2)}</td>
          <td>${s.confidence}%</td>
          <td>${statusBadge(s)}</td>
          <td><button type="button" class="btn btn-secondary btn-sm" data-edit-setup="${s.id}">Edit</button></td>
        </tr>`;
    })
    .join("");

  tbody.querySelectorAll("button[data-open-run]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const runId = Number(btn.dataset.openRun);
      if (runId) openScanEvaluationsModal(runId);
    });
  });

  tbody.querySelectorAll("button[data-edit-setup]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const id = Number(btn.dataset.editSetup);
      const found = state.setups.find((x) => x.id === id);
      if (found) {
        selectSetup(found);
        openEditStatusModal(found);
      }
    });
  });

  tbody.querySelectorAll("tr[data-id]").forEach((row) => {
    row.addEventListener("click", () => {
      const id = Number(row.dataset.id);
      const found = state.setups.find((x) => x.id === id);
      if (found) selectSetup(found);
    });
  });

  if (!state.selectedSetup && data.items.length) {
    selectSetup(data.items[0]);
  }
}

function updateDssLegend(mainVal, sigVal) {
  const mainEl = document.getElementById("dss-val-main");
  const sigEl = document.getElementById("dss-val-sig");
  if (mainEl) mainEl.textContent = mainVal !== null && mainVal !== undefined ? Number(mainVal).toFixed(2) : "-";
  if (sigEl) sigEl.textContent = sigVal !== null && sigVal !== undefined ? Number(sigVal).toFixed(2) : "-";
}

function initChartIfNeeded() {
  if (state.chart) return;
  const container = document.getElementById("candlestick-chart");
  const initialWidth = container.clientWidth || 800;
  state.chart = LightweightCharts.createChart(container, {
    width: initialWidth,
    height: container.clientHeight || 460,
    layout: { background: { color: "#ffffff" }, textColor: "#65676b" },
    grid: { vertLines: { color: "#f0f2f5" }, horzLines: { color: "#f0f2f5" } },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    handleScroll: {
      mouseWheel: true,
      pressedMouseMove: true,
      horzTouchDrag: true,
      vertTouchDrag: true,
    },
    handleScale: {
      axisPressedMouseMove: { time: true, price: true },
      axisDoubleClickReset: { time: true, price: true },
      mouseWheel: true,
      pinch: true,
    },
    kineticScroll: { mouse: true, touch: true },
    localization: { locale: "id-ID", timeFormatter: formatChartJakartaTime },
    timeScale: {
      timeVisible: true,
      secondsVisible: false,
      borderColor: "#dadde1",
      rightOffset: 10,
      tickMarkFormatter: formatChartJakartaTickMark,
    },
    rightPriceScale: { borderColor: "#dadde1", minimumWidth: 78, autoScale: true },
  });
  state.candleSeries = state.chart.addCandlestickSeries({
    upColor: "#16a34a",
    downColor: "#e41e3f",
    borderVisible: false,
    wickUpColor: "#16a34a",
    wickDownColor: "#e41e3f",
  });
  state.candleSeries.priceScale().applyOptions({
    scaleMargins: { top: 0.06, bottom: 0.24 },
  });
  state.volumeSeries = state.chart.addHistogramSeries({
    priceFormat: { type: "volume" },
    priceScaleId: "volume",
    lastValueVisible: false,
    priceLineVisible: false,
  });
  state.volumeSeries.priceScale().applyOptions({
    scaleMargins: { top: 0.78, bottom: 0 },
  });
  state.ema21Series = state.chart.addLineSeries({ color: "#1877f2", lineWidth: 1.5, title: "EMA21" });
  state.ema50Series = state.chart.addLineSeries({ color: "#d97706", lineWidth: 1.5, title: "EMA50" });
  state.ema200Series = state.chart.addLineSeries({ color: "#7c3aed", lineWidth: 1.5, title: "EMA200" });

  // Synced DSS Bressert (10 9 5 80 20 60) pane
  const dssContainer = document.getElementById("dss-chart");
  state.dssChart = LightweightCharts.createChart(dssContainer, {
    width: dssContainer.clientWidth || initialWidth,
    height: dssContainer.clientHeight || 170,
    layout: { background: { color: "#ffffff" }, textColor: "#65676b" },
    grid: { vertLines: { color: "#f0f2f5" }, horzLines: { color: "#f0f2f5" } },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: true },
    handleScale: { axisPressedMouseMove: { time: true, price: false }, mouseWheel: true, pinch: true },
    kineticScroll: { mouse: true, touch: true },
    localization: { locale: "id-ID", timeFormatter: formatChartJakartaTime },
    timeScale: {
      timeVisible: true,
      secondsVisible: false,
      borderColor: "#dadde1",
      rightOffset: 10,
      tickMarkFormatter: formatChartJakartaTickMark,
    },
    rightPriceScale: { borderColor: "#dadde1", autoScale: true, minimumWidth: 78 },
  });
  state.dssSeries = state.dssChart.addLineSeries({
    color: "#1877f2",
    lineWidth: 2,
    priceLineVisible: false,
    lastValueVisible: true,
    autoscaleInfoProvider: () => ({
      priceRange: { minValue: 0, maxValue: 100 },
      margins: { above: 6, below: 6 },
    }),
  });
  state.dssSignalSeries = state.dssChart.addLineSeries({
    color: "#e41e3f",
    lineWidth: 1.8,
    priceLineVisible: false,
    lastValueVisible: true,
    autoscaleInfoProvider: () => ({
      priceRange: { minValue: 0, maxValue: 100 },
      margins: { above: 6, below: 6 },
    }),
  });
  state.dssSeries.createPriceLine({
    price: 80,
    color: "rgba(228, 30, 63, 0.45)",
    lineWidth: 1,
    lineStyle: LightweightCharts.LineStyle.Dashed,
    axisLabelVisible: true,
    title: "80",
  });
  state.dssSeries.createPriceLine({
    price: 60,
    color: "#16a34a",
    lineWidth: 1.5,
    lineStyle: LightweightCharts.LineStyle.Solid,
    axisLabelVisible: true,
    title: "60",
  });
  state.dssSeries.createPriceLine({
    price: 20,
    color: "rgba(22, 163, 74, 0.45)",
    lineWidth: 1,
    lineStyle: LightweightCharts.LineStyle.Dashed,
    axisLabelVisible: true,
    title: "20",
  });

  state.chart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
    scheduleOverlayRender();
    if (state.syncingTimeRange || !range || !state.dssChart) return;
    state.syncingTimeRange = true;
    state.dssChart.timeScale().setVisibleLogicalRange(range);
    state.syncingTimeRange = false;
  });
  state.dssChart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
    if (state.syncingTimeRange || !range || !state.chart) return;
    state.syncingTimeRange = true;
    state.chart.timeScale().setVisibleLogicalRange(range);
    state.syncingTimeRange = false;
    scheduleOverlayRender();
  });

  let isChartPanning = false;
  container.addEventListener("pointerdown", () => {
    isChartPanning = true;
  });
  window.addEventListener("pointerup", () => {
    if (isChartPanning) {
      isChartPanning = false;
      scheduleOverlayRender();
    }
  });
  container.addEventListener("pointermove", () => {
    if (isChartPanning) scheduleOverlayRender();
  });
  container.addEventListener("wheel", () => {
    scheduleOverlayRender();
  }, { passive: true });
  container.addEventListener("dblclick", () => {
    setTimeout(scheduleOverlayRender, 30);
  });

  const handleCrosshair = (param) => {
    if (param && param.time && state.dssByTime[param.time]) {
      const pt = state.dssByTime[param.time];
      updateDssLegend(pt.dss, pt.sig);
    } else {
      updateDssLegend(state.latestDssMain, state.latestDssSig);
    }
  };
  state.chart.subscribeCrosshairMove(handleCrosshair);
  state.dssChart.subscribeCrosshairMove(handleCrosshair);

  new ResizeObserver(() => {
    state.chart.applyOptions({ width: container.clientWidth, height: container.clientHeight });
    scheduleOverlayRender();
  }).observe(container);
  new ResizeObserver(() => {
    if (dssContainer.clientWidth > 0 && dssContainer.clientHeight > 0) {
      state.dssChart.applyOptions({ width: dssContainer.clientWidth, height: dssContainer.clientHeight });
    }
  }).observe(dssContainer);
}

function scheduleOverlayRender() {
  if (state.overlayRafPending) return;
  state.overlayRafPending = true;
  requestAnimationFrame(() => {
    state.overlayRafPending = false;
    renderPositionOverlay();
  });
}

function formatPositionPrice(val) {
  const n = Number(val);
  if (!Number.isFinite(n)) return "-";
  if (n >= 1000) return n.toFixed(2);
  if (n >= 1) return n.toFixed(4);
  return n.toPrecision(6);
}

function roundPositionPrice(val) {
  const n = Number(val);
  if (!Number.isFinite(n)) return n;
  return Number(n.toFixed(n >= 1000 ? 2 : n >= 1 ? 4 : 8));
}

const SETUP_BOX_ID = 0;

function getAutoPositionSide() {
  if (state.selectedSetup && String(state.selectedSetup.decision).toUpperCase() === "SHORT") {
    return "SHORT";
  }
  return "LONG";
}

function buildSetupPositionBox(setup) {
  if (!setup) return null;
  const side = String(setup.decision).toUpperCase() === "SHORT" ? "SHORT" : "LONG";
  const hasManual =
    setup.manual_entry_price !== null &&
    setup.manual_entry_price !== undefined &&
    Number(setup.manual_entry_price) > 0;
  const entry = Number(hasManual ? setup.manual_entry_price : setup.entry_price);
  const sl = Number(setup.stop_loss);
  const tp = Number(setup.take_profit);
  if (!Number.isFinite(entry) || !Number.isFinite(sl) || !Number.isFinite(tp)) return null;

  let startIdx = Math.max(0, state.chartBarsCount - 28);
  if (setup.created_at && state.chartCandles.length) {
    const createdSec = Math.floor(new Date(setup.created_at + "Z").getTime() / 1000);
    if (Number.isFinite(createdSec)) {
      const idx = state.chartCandles.findIndex((c) => Number(c.time) >= createdSec);
      if (idx >= 0) {
        startIdx = Math.min(idx, Math.max(0, state.chartCandles.length - 6));
      }
    }
  }
  const endIdx = Math.max(startIdx + 18, state.chartBarsCount + 6);
  return {
    id: SETUP_BOX_ID,
    isSetupBox: true,
    setupId: setup.id,
    isManualEntry: hasManual,
    side,
    entry: roundPositionPrice(entry),
    sl: roundPositionPrice(sl),
    tp: roundPositionPrice(tp),
    startIdx,
    endIdx,
  };
}

function ensureSetupPositionBox() {
  if (state.drawMode !== "setup" || !state.selectedSetup) return null;
  if (!state.setupBox || state.setupBox.setupId !== state.selectedSetup.id) {
    state.setupBox = buildSetupPositionBox(state.selectedSetup);
  }
  return state.setupBox;
}

function findOverlayBoxById(id) {
  if (id === SETUP_BOX_ID) return state.setupBox;
  return state.drawnPositions.find((p) => p.id === id) || null;
}

function getAllVisibleBoxes() {
  const boxes = [];
  if (state.drawMode === "setup") {
    const sb = ensureSetupPositionBox();
    if (sb) boxes.push(sb);
  }
  for (const p of state.drawnPositions) boxes.push(p);
  return boxes;
}

function getActiveDrawnPosition() {
  const boxes = getAllVisibleBoxes();
  if (!boxes.length) return null;
  const matched = boxes.find((p) => p.id === state.activePositionId);
  if (matched) return matched;
  if (state.drawMode === "setup" && state.setupBox) return state.setupBox;
  return boxes[boxes.length - 1];
}

function updateDrawModeButtonLabel() {
  const drawBtn = document.getElementById("btn-mode-draw");
  if (drawBtn) {
    drawBtn.textContent = state.selectedSetup ? `Mode Gambar (${getAutoPositionSide()})` : "Mode Gambar";
  }
  const setupBtn = document.getElementById("btn-mode-setup");
  if (setupBtn) {
    setupBtn.textContent = state.selectedSetup ? `Kotak Setup (${getAutoPositionSide()})` : "Kotak Setup";
  }
}

function updatePositionToolBar() {
  updateDrawModeButtonLabel();
  const bar = document.getElementById("position-tool-bar");
  const summary = document.getElementById("pos-bar-summary");
  const fromSetupBtn = document.getElementById("btn-pos-from-setup");
  const applyBtn = document.getElementById("btn-pos-apply");
  const clearBtn = document.getElementById("btn-pos-clear");
  if (!bar || !summary) return;

  const isSetupMode = state.drawMode === "setup";
  const isDrawMode = state.drawMode === "draw";
  const visibleBoxes = getAllVisibleBoxes();
  const pos = getActiveDrawnPosition();
  bar.classList.toggle("hidden", !isDrawMode && !isSetupMode && !visibleBoxes.length);

  if (fromSetupBtn) {
    fromSetupBtn.textContent = "\u21ba Dari Setup";
    fromSetupBtn.classList.toggle("hidden", !isDrawMode);
  }

  if (!pos) {
    const autoSide = getAutoPositionSide();
    const zoneDesc = autoSide === "LONG" ? "hijau di atas, merah di bawah" : "merah di atas, hijau di bawah";
    if (isSetupMode) {
      summary.innerHTML = `<b>Kotak Setup</b> aktif — pilih salah satu setup di tabel untuk menampilkan kotak Entry/SL/TP otomatis.`;
    } else {
      summary.innerHTML = state.selectedSetup
        ? `<b>Mode Gambar (${autoSide})</b> (${zoneDesc}) — klik di chart untuk pasang posisi, atau klik <b>Dari Setup</b>.`
        : `<b>Mode Gambar</b> aktif — pilih salah satu setup di tabel terlebih dahulu agar arah LONG/SHORT otomatis mengikuti setup.`;
    }
    if (applyBtn) applyBtn.classList.add("hidden");
    if (clearBtn) clearBtn.classList.add("hidden");
    return;
  }

  const risk = Math.abs(pos.entry - pos.sl);
  const reward = Math.abs(pos.tp - pos.entry);
  const rr = risk > 0 ? reward / risk : 0;
  const slPct = pos.entry > 0 ? (risk / pos.entry) * 100 : 0;
  const tpPct = pos.entry > 0 ? (reward / pos.entry) * 100 : 0;
  const badgeCls = pos.side === "LONG" ? "badge-long" : "badge-short";
  const sourceTag = pos.isSetupBox
    ? ` <span class="badge badge-neutral">${pos.isManualEntry ? "Manual" : "AI"}</span>`
    : "";
  const modeHint = isSetupMode
    ? ` <span class="subtitle-sm">&bull; Mode View (hover kotak untuk R:R; pilih Mode Gambar untuk edit SL/TP)</span>`
    : state.drawMode === "normal"
      ? ` <span class="subtitle-sm">&bull; Pilih Mode Gambar untuk edit garis</span>`
      : "";

  summary.innerHTML = `<span class="badge ${badgeCls}">${pos.side}</span>${sourceTag} E: <b>${formatPositionPrice(pos.entry)}</b> &bull; <span class="text-red">SL: <b>${formatPositionPrice(pos.sl)}</b> (-${slPct.toFixed(2)}%)</span> &bull; <span class="text-green">TP: <b>${formatPositionPrice(pos.tp)}</b> (+${tpPct.toFixed(2)}%)</span> &bull; R:R: <b>${rr.toFixed(2)}</b>${modeHint}`;
  if (fromSetupBtn) fromSetupBtn.classList.toggle("hidden", !isDrawMode);
  if (applyBtn) applyBtn.classList.toggle("hidden", isSetupMode || !state.selectedSetup);
  if (clearBtn) clearBtn.classList.toggle("hidden", isSetupMode || pos.isSetupBox || state.drawnPositions.length === 0);
}

function renderPositionOverlay() {
  const overlay = document.getElementById("position-overlay");
  if (!overlay) return;
  const boxes = getAllVisibleBoxes();
  updatePositionToolBar();

  const isPlacing = state.drawMode === "draw";
  const isInteractive = state.drawMode === "draw";

  overlay.classList.toggle("placing", isPlacing);
  overlay.classList.toggle("interactive", isInteractive && boxes.length > 0);

  if (!boxes.length || !state.chart || !state.candleSeries) {
    overlay.innerHTML = "";
    return;
  }

  const ts = state.chart.timeScale();
  const cs = state.candleSeries;
  const chartEl = document.getElementById("candlestick-chart");
  const plotW = Math.max(0, (typeof ts.width === "function" ? ts.width() : 0) || ((chartEl ? chartEl.clientWidth : 800) - 78));
  const plotH = Math.max(0, (chartEl ? chartEl.clientHeight : 460) - 26);
  if (plotW > 0) overlay.style.width = `${plotW}px`;
  if (plotH > 0) overlay.style.height = `${plotH}px`;

  const active = getActiveDrawnPosition();
  const html = [];

  boxes.forEach((pos) => {
    const x1 = ts.logicalToCoordinate(Math.round(pos.startIdx));
    const x2Raw = ts.logicalToCoordinate(Math.round(pos.endIdx));
    const yEntry = cs.priceToCoordinate(pos.entry);
    const yTp = cs.priceToCoordinate(pos.tp);
    const ySl = cs.priceToCoordinate(pos.sl);

    if (x1 === null || yEntry === null || yTp === null || ySl === null) return;
    const x2 = x2Raw !== null ? x2Raw : x1 + 120;

    const left = Math.min(x1, x2);
    const width = Math.max(40, Math.abs(x2 - x1));
    const topY = Math.min(yEntry, yTp, ySl);
    const bottomY = Math.max(yEntry, yTp, ySl);
    const boxH = Math.max(12, bottomY - topY);

    // LONG: TP di atas Entry (hijau atas, merah bawah); SHORT: SL di atas Entry (merah atas, hijau bawah)
    const profitTop = Math.min(yEntry, yTp) - topY;
    const profitH = Math.max(1, Math.abs(yTp - yEntry));
    const lossTop = Math.min(yEntry, ySl) - topY;
    const lossH = Math.max(1, Math.abs(ySl - yEntry));
    const relTp = yTp - topY;
    const relSl = ySl - topY;
    const relEntry = yEntry - topY;

    const risk = Math.abs(pos.entry - pos.sl);
    const reward = Math.abs(pos.tp - pos.entry);
    const rr = risk > 0 ? (reward / risk).toFixed(2) : "0.00";
    const slPct = pos.entry > 0 ? ((risk / pos.entry) * 100).toFixed(2) : "0.00";
    const tpPct = pos.entry > 0 ? ((reward / pos.entry) * 100).toFixed(2) : "0.00";
    const isActive = active && active.id === pos.id;
    const isReadonly = state.drawMode !== "draw";
    const entryTag = pos.isSetupBox ? (pos.isManualEntry ? `${pos.side} (M)` : `${pos.side} (AI)`) : pos.side;

    html.push(`
      <div class="pos-box${isActive && !isReadonly ? " active" : ""}${isReadonly ? " readonly" : ""}" data-pos-id="${pos.id}" data-pos-handle="move" style="left:${left}px;top:${topY}px;width:${width}px;height:${boxH}px;">
        <div class="pos-zone-profit" style="top:${profitTop}px;height:${profitH}px;"></div>
        <div class="pos-zone-loss" style="top:${lossTop}px;height:${lossH}px;"></div>
        <div class="pos-rr-hover-badge">R:R 1 : ${rr}</div>
        <div class="pos-handle pos-handle-tp" data-pos-id="${pos.id}" data-pos-handle="tp" style="top:${relTp}px;">
          <span class="pos-dot"></span>
          <span class="pos-label pos-label-tp">TP ${formatPositionPrice(pos.tp)} (+${tpPct}% | ${rr}R)</span>
        </div>
        <div class="pos-handle pos-handle-entry" data-pos-id="${pos.id}" data-pos-handle="entry" style="top:${relEntry}px;">
          <span class="pos-dot"></span>
          <span class="pos-label pos-label-entry">${entryTag} ${formatPositionPrice(pos.entry)}</span>
        </div>
        <div class="pos-handle pos-handle-sl" data-pos-id="${pos.id}" data-pos-handle="sl" style="top:${relSl}px;">
          <span class="pos-dot"></span>
          <span class="pos-label pos-label-sl">SL ${formatPositionPrice(pos.sl)} (-${slPct}%)</span>
        </div>
        <div class="pos-handle-edge-r" data-pos-id="${pos.id}" data-pos-handle="resize-r" title="Geser lebar kotak"></div>
      </div>
    `);
  });

  overlay.innerHTML = html.join("");
}

function createPositionAtClick(side, clientX, clientY) {
  if (!state.selectedSetup) {
    showToast("Pilih salah satu setup terlebih dahulu untuk menggambar posisi.", true);
    return;
  }
  if (!state.chart || !state.candleSeries) {
    showToast("Chart belum siap, tunggu candlestick termuat.", true);
    return;
  }
  const chartEl = document.getElementById("candlestick-chart");
  const rect = chartEl.getBoundingClientRect();
  const relX = clientX - rect.left;
  const relY = clientY - rect.top;

  const clickPrice = state.candleSeries.coordinateToPrice(relY);
  const clickLogical = state.chart.timeScale().coordinateToLogical(relX);
  if (clickPrice === null || !Number.isFinite(clickPrice) || clickPrice <= 0 || clickLogical === null) {
    showToast("Klik tepat di area candlestick chart untuk memasang posisi.", true);
    return;
  }

  const topPrice = state.candleSeries.coordinateToPrice(20);
  const botPrice = state.candleSeries.coordinateToPrice(Math.max(60, rect.height - 50));
  const visibleSpan = topPrice && botPrice ? Math.abs(topPrice - botPrice) : clickPrice * 0.04;
  const riskUnit = Math.max(visibleSpan * 0.14, clickPrice * 0.005);

  const isLong = side === "LONG";
  const baseIdx = Math.round(clickLogical);
  const id = state.nextPositionSeq++;
  const newPos = {
    id,
    side,
    entry: roundPositionPrice(clickPrice),
    sl: roundPositionPrice(isLong ? Math.max(clickPrice * 0.05, clickPrice - riskUnit) : clickPrice + riskUnit),
    tp: roundPositionPrice(isLong ? clickPrice + riskUnit * 2 : Math.max(clickPrice * 0.05, clickPrice - riskUnit * 2)),
    startIdx: baseIdx,
    endIdx: baseIdx + 20,
  };
  state.drawnPositions = [newPos];
  state.activePositionId = id;
  renderPositionOverlay();
  return newPos;
}

function createPositionFromSelectedSetup() {
  const s = state.selectedSetup;
  if (!s) return;
  if (state.drawMode === "setup") {
    state.setupBox = buildSetupPositionBox(s);
    state.activePositionId = SETUP_BOX_ID;
    renderPositionOverlay();
    return;
  }
  const built = buildSetupPositionBox(s);
  if (!built) return;
  const id = state.nextPositionSeq++;
  state.drawnPositions = [{
    ...built,
    id,
    isSetupBox: false,
  }];
  state.activePositionId = id;
  setDrawMode("draw");
}

function syncSetupPriceLines() {
  if (!state.candleSeries) return;
  for (const pl of state.priceLines) {
    state.candleSeries.removePriceLine(pl);
  }
  state.priceLines = [];
  if (state.drawMode === "setup" || !state.selectedSetup) return;

  const setup = state.selectedSetup;
  const nextLines = [];
  const hasManualEntry =
    setup.manual_entry_price !== null &&
    setup.manual_entry_price !== undefined &&
    Number(setup.manual_entry_price) > 0;
  if (hasManualEntry && Math.abs(Number(setup.manual_entry_price) - Number(setup.entry_price)) > 1e-12) {
    nextLines.push(
      state.candleSeries.createPriceLine({
        price: setup.entry_price,
        color: "#9ca3af",
        lineWidth: 1,
        lineStyle: LightweightCharts.LineStyle.Dashed,
        axisLabelVisible: true,
        title: "AI ENTRY",
      }),
      state.candleSeries.createPriceLine({
        price: setup.manual_entry_price,
        color: "#6b21a8",
        lineWidth: 2,
        lineStyle: LightweightCharts.LineStyle.Solid,
        axisLabelVisible: true,
        title: "ENTRY (MANUAL)",
      })
    );
  } else {
    nextLines.push(
      state.candleSeries.createPriceLine({
        price: hasManualEntry ? setup.manual_entry_price : setup.entry_price,
        color: "#1877f2",
        lineWidth: 2,
        lineStyle: LightweightCharts.LineStyle.Dashed,
        axisLabelVisible: true,
        title: hasManualEntry ? "ENTRY (MANUAL)" : `ENTRY (${setup.entry_type})`,
      })
    );
  }
  nextLines.push(
    state.candleSeries.createPriceLine({
      price: setup.stop_loss,
      color: "#e41e3f",
      lineWidth: 2,
      lineStyle: LightweightCharts.LineStyle.Solid,
      axisLabelVisible: true,
      title: "STOP LOSS",
    }),
    state.candleSeries.createPriceLine({
      price: setup.take_profit,
      color: "#16a34a",
      lineWidth: 2,
      lineStyle: LightweightCharts.LineStyle.Solid,
      axisLabelVisible: true,
      title: "TAKE PROFIT",
    })
  );
  state.priceLines = nextLines;
}

function setDrawMode(mode) {
  state.drawMode = mode;
  document.querySelectorAll(".btn-chip[data-draw-mode]").forEach((b) => {
    b.classList.toggle("active", b.dataset.drawMode === mode);
  });
  if (mode === "setup" && state.selectedSetup) {
    ensureSetupPositionBox();
    state.activePositionId = SETUP_BOX_ID;
  }
  syncSetupPriceLines();
  renderPositionOverlay();
}

function fitAndUnlockChart() {
  if (!state.chart || !state.candleSeries) return;
  state.chart.priceScale("right").applyOptions({ autoScale: true });
  state.candleSeries.priceScale().applyOptions({ autoScale: true });
  state.chart.timeScale().fitContent();
  if (state.dssChart) {
    state.dssChart.priceScale("right").applyOptions({ autoScale: true });
    const r = state.chart.timeScale().getVisibleLogicalRange();
    if (r) state.dssChart.timeScale().setVisibleLogicalRange(r);
  }
  // Unlock autoScale after initial fit frame so user can drag chart freely up/down & left/right
  requestAnimationFrame(() => {
    if (state.chart && state.candleSeries) {
      state.candleSeries.priceScale().applyOptions({ autoScale: false });
      state.chart.priceScale("right").applyOptions({ autoScale: false });
      renderPositionOverlay();
    }
  });
}

async function renderSetupChart(setup, isLiveRefresh = false) {
  if (!setup || state.chartRefreshing) return;
  state.chartRefreshing = true;
  initChartIfNeeded();
  document.getElementById("chart-title").textContent = `${setup.symbol} (${setup.decision}) — ${setup.strategy_used}`;

  const isNewContext =
    state.renderedSetupId !== setup.id || state.renderedInterval !== state.chartInterval;

  try {
    const chartData = await apiRequest(`/api/charts/${setup.symbol}?interval=${state.chartInterval}&limit=300`);
    const candles = chartData.candles || [];
    state.chartCandles = candles;
    state.chartBarsCount = candles.length || 300;
    if (isNewContext) state.setupBox = null;
    const showVolume = document.getElementById("toggle-volume")?.checked ?? true;
    const showEma = document.getElementById("toggle-ema")?.checked ?? false;
    const showDss = document.getElementById("toggle-dss")?.checked ?? true;

    const latestCandle = candles.length ? candles[candles.length - 1] : null;
    const canIncrementalUpdate =
      !isNewContext &&
      isLiveRefresh &&
      latestCandle &&
      state.lastCandleTime &&
      latestCandle.time >= state.lastCandleTime &&
      state.lastVolumeToggle === showVolume;

    if (canIncrementalUpdate) {
      state.candleSeries.update(latestCandle);
      if (showVolume) {
        state.volumeSeries.update({
          time: latestCandle.time,
          value: latestCandle.volume,
          color: latestCandle.close >= latestCandle.open ? "rgba(16, 185, 129, 0.45)" : "rgba(239, 68, 68, 0.45)",
        });
      }
      if (showEma) {
        if (chartData.ema21?.length) state.ema21Series.update(chartData.ema21[chartData.ema21.length - 1]);
        if (chartData.ema50?.length) state.ema50Series.update(chartData.ema50[chartData.ema50.length - 1]);
        if (chartData.ema200?.length) state.ema200Series.update(chartData.ema200[chartData.ema200.length - 1]);
      }
    } else {
      state.candleSeries.setData(candles);
      if (state.lastVolumeToggle !== showVolume || isNewContext) {
        state.candleSeries.priceScale().applyOptions({
          scaleMargins: { top: 0.06, bottom: showVolume ? 0.24 : 0.06 },
        });
        state.lastVolumeToggle = showVolume;
      }
      state.volumeSeries.setData(
        showVolume
          ? candles.map((c) => ({
              time: c.time,
              value: c.volume,
              color: c.close >= c.open ? "rgba(16, 185, 129, 0.45)" : "rgba(239, 68, 68, 0.45)",
            }))
          : []
      );
      state.ema21Series.setData(showEma ? chartData.ema21 : []);
      state.ema50Series.setData(showEma ? chartData.ema50 : []);
      state.ema200Series.setData(showEma ? chartData.ema200 : []);
    }
    state.lastCandleTime = latestCandle ? latestCandle.time : null;

    const dssWrap = document.getElementById("dss-chart-wrap");
    if (dssWrap) dssWrap.classList.toggle("hidden", !showDss);
    const dssArr = chartData.dss || [];
    const sigArr = chartData.dss_signal || [];
    state.dssByTime = {};
    for (let i = 0; i < dssArr.length; i += 1) {
      const t = dssArr[i].time;
      state.dssByTime[t] = {
        dss: dssArr[i].value,
        sig: sigArr[i] ? sigArr[i].value : null,
      };
    }
    state.latestDssMain = dssArr.length ? dssArr[dssArr.length - 1].value : null;
    state.latestDssSig = sigArr.length ? sigArr[sigArr.length - 1].value : null;
    updateDssLegend(state.latestDssMain, state.latestDssSig);

    if (showDss && state.dssChart) {
      if (canIncrementalUpdate && dssArr.length && sigArr.length) {
        state.dssSeries.update(dssArr[dssArr.length - 1]);
        state.dssSignalSeries.update(sigArr[sigArr.length - 1]);
      } else {
        state.dssSeries.setData(dssArr);
        state.dssSignalSeries.setData(sigArr);
        const dssEl = document.getElementById("dss-chart");
        if (dssEl && dssEl.clientWidth > 0 && dssEl.clientHeight > 0) {
          state.dssChart.applyOptions({
            width: dssEl.clientWidth,
            height: dssEl.clientHeight,
          });
        }
        state.dssChart.priceScale("right").applyOptions({ autoScale: true });
      }
    } else if (state.dssSeries && state.dssSignalSeries) {
      state.dssSeries.setData([]);
      state.dssSignalSeries.setData([]);
    }

    const lastCandle = latestCandle;
    const liveStr = lastCandle ? ` • Live: ${fmtPrice(lastCandle.close)}` : "";
    document.getElementById("chart-subtitle").textContent =
      `Interval ${state.chartInterval}${liveStr} • Status: ${setup.status} • Update ${formatJakartaTime()}`;

    if (isNewContext || !isLiveRefresh) {
      syncSetupPriceLines();
      if (isNewContext) {
        fitAndUnlockChart();
      }
      state.renderedSetupId = setup.id;
      state.renderedInterval = state.chartInterval;
    }
    scheduleOverlayRender();
  } catch (err) {
    if (!isLiveRefresh) {
      showToast(`Gagal memuat chart ${setup.symbol}: ${err.message}`, true);
    }
  } finally {
    state.chartRefreshing = false;
  }
}

function selectSetup(setup) {
  const symbolChanged = state.selectedSetup && state.selectedSetup.symbol !== setup.symbol;
  state.selectedSetup = setup;
  state.setupBox = null;
  if (symbolChanged && state.drawnPositions.length) {
    state.drawnPositions = [];
    state.activePositionId = null;
  }
  renderPositionOverlay();
  document.querySelectorAll("#setups-tbody tr[data-id]").forEach((tr) => {
    tr.classList.toggle("selected", Number(tr.dataset.id) === setup.id);
  });

  const effEntry = setup.manual_entry_price ?? setup.entry_price;
  document.getElementById("setup-detail-body").classList.remove("hidden");
  document.getElementById("d-entry-type").textContent = setup.manual_entry_price ? "MANUAL" : setup.entry_type;
  document.getElementById("d-entry").textContent = fmtPrice(effEntry);
  document.getElementById("d-sl").textContent = fmtPrice(setup.stop_loss);
  document.getElementById("d-tp").textContent = fmtPrice(setup.take_profit);
  document.getElementById("d-rr-conf").textContent = `${Number(setup.risk_reward_ratio).toFixed(2)}R / ${setup.confidence}%`;
  document.getElementById("d-regime").textContent = setup.market_regime;
  document.getElementById("d-ai-model").textContent = `${setup.llm_provider || "-"} / ${setup.llm_model || "-"}`;
  document.getElementById("d-expires").textContent = formatJakartaDateTime(setup.expires_at);
  document.getElementById("d-manual-entry").textContent = setup.manual_entry_price
    ? `${fmtPrice(setup.manual_entry_price)} (AI: ${fmtPrice(setup.entry_price)})`
    : "-";
  document.getElementById("d-resolved-price").textContent = setup.resolved_price
    ? fmtPrice(setup.resolved_price)
    : "-";

  const scanRefBox = document.getElementById("d-scan-run-box");
  if (scanRefBox) {
    const meta = resolveSetupStrategyMeta(setup);
    const runBadge = setup.scan_run_id
      ? `<button type="button" class="run-id-chip" id="btn-detail-run-chip" title="Klik untuk melihat detail Scan Run #${setup.scan_run_id}">Scan Run #${setup.scan_run_id}</button>`
      : `<span class="badge badge-neutral">Tanpa Scan Run</span>`;
    const runTimeStr = setup.scan_run_started_at
      ? ` &bull; <span class="subtitle-sm">${escapeHtml(formatJakartaDateTime(setup.scan_run_started_at))}</span>`
      : "";
    const runEvalBtn = setup.scan_run_id
      ? `<button type="button" class="btn btn-secondary btn-sm" id="btn-detail-open-run">Lihat Evaluasi Scan #${setup.scan_run_id}</button>`
      : "";
    const profBits = [
      meta.holdingPeriod ? `Lama Trade: <b>${escapeHtml(meta.holdingPeriod)}</b>` : null,
      meta.tradeStyle ? `Gaya: <b>${escapeHtml(meta.tradeStyle)}</b>` : null,
      meta.htf || meta.ltf ? `TF: <b>${escapeHtml(meta.htf || "-")}/${escapeHtml(meta.ltf || "-")}</b>` : null,
      meta.klineLimit ? `Candles: <b>${meta.klineLimit}</b>` : null,
      meta.expiryHours ? `Expiry: <b>${meta.expiryHours}j</b>` : null,
    ]
      .filter(Boolean)
      .join(" &bull; ");
    scanRefBox.classList.remove("hidden");
    scanRefBox.innerHTML = `
      <div class="scan-ref-header">
        <div><strong>Referensi Scan &amp; Experiment:</strong> ${runBadge}${runTimeStr}</div>
        ${runEvalBtn}
      </div>
      ${profBits ? `<div><strong>Strategi (${escapeHtml(setup.strategy_used)}):</strong> ${profBits}</div>` : ""}
      ${buildScanSettingsHtml(setup.scan_run_settings, setup.strategy_used)}
    `;
    const openDetailRun = () => {
      if (setup.scan_run_id) openScanEvaluationsModal(setup.scan_run_id);
    };
    document.getElementById("btn-detail-open-run")?.addEventListener("click", openDetailRun);
    document.getElementById("btn-detail-run-chip")?.addEventListener("click", openDetailRun);
  }
  document.getElementById("d-rationale").textContent = setup.rationale;
  document.getElementById("d-invalidation").textContent = setup.invalidation_reason;
  document.getElementById("manual-entry-input").value = setup.manual_entry_price ?? "";
  document.getElementById("manual-notes-input").value = setup.manual_notes || "";

  const ltf = setup.features_snapshot?.ltf_15m || {};
  const htf = setup.features_snapshot?.htf_1h || {};
  const ticker = setup.features_snapshot?.market_ticker || {};
  document.getElementById("d-indicators").innerHTML = `
    <div class="snap-item"><span>HTF 1H Bias</span><strong>${htf.ema_bias || "-"}</strong></div>
    <div class="snap-item"><span>LTF RSI 14</span><strong>${ltf.rsi14 ?? "-"}</strong></div>
    <div class="snap-item"><span>LTF Vol Ratio</span><strong>${ltf.volume_ratio ?? "-"}x</strong></div>
    <div class="snap-item"><span>Funding Rate</span><strong>${ticker.funding_rate ?? "-"}</strong></div>
    <div class="snap-item"><span>Support (15m)</span><strong>${fmtPrice(ltf.nearest_support)}</strong></div>
    <div class="snap-item"><span>Resistance (15m)</span><strong>${fmtPrice(ltf.nearest_resistance)}</strong></div>
    <div class="snap-item"><span>ATR 14 (15m)</span><strong>${fmtPrice(ltf.atr14)} (${ltf.atr_pct ?? "-"}%)</strong></div>
    <div class="snap-item"><span>24h Volume</span><strong>$${Number(ticker.quote_volume_24h || 0).toLocaleString()}</strong></div>
  `;

  renderSetupHistory(setup);
  renderSetupChart(setup);
}

function renderSetupHistory(setup) {
  const box = document.getElementById("d-history-list");
  if (!box) return;
  const aiPay = setup.ai_payload || {};
  const initEntry = aiPay.entry_price ?? setup.entry_price;
  const initSl = aiPay.stop_loss ?? setup.stop_loss;
  const initTp = aiPay.take_profit ?? setup.take_profit;
  const createdBaselineHtml = `<div class="history-item"><div><span class="badge badge-open">CREATED</span> <strong>Setup dibuat oleh sistem (AI ${escapeHtml(setup.entry_type || "-")})</strong> &bull; E: <b>${fmtPrice(initEntry)}</b> &bull; SL: <b>${fmtPrice(initSl)}</b> &bull; TP: <b>${fmtPrice(initTp)}</b></div><span class="subtitle-sm">${escapeHtml(formatJakartaDateTime(setup.created_at))}</span></div>`;

  const rows = [];
  if (Array.isArray(setup.status_history) && setup.status_history.length) {
    const hasCreated = setup.status_history.some((h) => h && h.event === "CREATED");
    if (!hasCreated) {
      rows.push(createdBaselineHtml);
    }
    for (const h of setup.status_history) {
      const timeTxt = h.at ? formatJakartaDateTime(h.at) : "-";
      if (h.event === "CREATED") {
        const cEntry = h.price ?? initEntry;
        const cSl = h.stop_loss ?? initSl;
        const cTp = h.take_profit ?? initTp;
        rows.push(
          `<div class="history-item"><div><span class="badge badge-open">CREATED</span> <strong>Setup dibuat oleh sistem (AI ${escapeHtml(setup.entry_type || "-")})</strong> &bull; E: <b>${fmtPrice(cEntry)}</b> &bull; SL: <b>${fmtPrice(cSl)}</b> &bull; TP: <b>${fmtPrice(cTp)}</b></div><span class="subtitle-sm">${escapeHtml(timeTxt)}</span></div>`
        );
        continue;
      }
      const pxTxt = h.price ? ` @ ${fmtPrice(h.price)}` : "";
      const slTpTxt =
        h.stop_loss != null && h.take_profit != null && (h.event === "MANUAL_TAKEN" || h.event === "RESET_OPEN")
          ? ` (SL: ${fmtPrice(h.stop_loss)}, TP: ${fmtPrice(h.take_profit)})`
          : "";
      rows.push(
        `<div class="history-item"><div><span class="badge badge-neutral">${escapeHtml(h.event || h.status)}</span> <strong>${escapeHtml(h.note || h.status || "")}</strong>${pxTxt}${slTpTxt}</div><span class="subtitle-sm">${escapeHtml(timeTxt)}</span></div>`
      );
    }
  } else {
    rows.push(createdBaselineHtml);
    if (setup.entry_hit_at) {
      rows.push(`<div class="history-item"><div><span class="badge badge-entry-hit">ENTRY_HIT</span> Tersentuh Entry @ ${fmtPrice(setup.entry_price)}</div><span class="subtitle-sm">${escapeHtml(formatJakartaDateTime(setup.entry_hit_at))}</span></div>`);
    }
    if (setup.missed_tp_at) {
      rows.push(`<div class="history-item"><div><span class="badge badge-missed-tp">TP NO ENTRY</span> Harga tembus TP @ ${fmtPrice(setup.missed_tp_price)} tanpa Entry</div><span class="subtitle-sm">${escapeHtml(formatJakartaDateTime(setup.missed_tp_at))}</span></div>`);
    }
    if (setup.resolved_at) {
      rows.push(`<div class="history-item"><div><span class="badge badge-neutral">${escapeHtml(setup.status)}</span> Selesai @ ${fmtPrice(setup.resolved_price)}</div><span class="subtitle-sm">${escapeHtml(formatJakartaDateTime(setup.resolved_at))}</span></div>`);
    }
  }
  box.innerHTML = rows.join("");
}

function parseOptionalFloatText(raw) {
  if (raw === null || raw === undefined) return null;
  const clean = String(raw).trim().replace(",", ".");
  if (!clean) return null;
  const num = Number(clean);
  return Number.isFinite(num) && num > 0 ? num : NaN;
}

async function updateManualStatus(newStatus, overrides = null) {
  if (!state.selectedSetup) return;
  const notes = overrides ? overrides.manual_notes : document.getElementById("manual-notes-input").value;
  let manualEntry = null;
  let resolvedPrice = null;
  let stopLoss = null;
  let takeProfit = null;

  if (overrides) {
    manualEntry = overrides.manual_entry_price;
    resolvedPrice = overrides.resolved_price;
    stopLoss = overrides.stop_loss ?? null;
    takeProfit = overrides.take_profit ?? null;
  } else if (newStatus === "MANUAL_TAKEN") {
    const parsed = parseOptionalFloatText(document.getElementById("manual-entry-input").value);
    if (Number.isNaN(parsed)) {
      showToast("Harga entry aktual harus berupa angka positif.", true);
      return false;
    }
    manualEntry = parsed;
  }

  try {
    const bodyObj = {
      status: newStatus,
      manual_entry_price: manualEntry,
      resolved_price: resolvedPrice,
      manual_notes: notes,
    };
    if (stopLoss !== null) bodyObj.stop_loss = stopLoss;
    if (takeProfit !== null) bodyObj.take_profit = takeProfit;

    const updated = await apiRequest(`/api/setups/${state.selectedSetup.id}/status`, {
      method: "PATCH",
      body: JSON.stringify(bodyObj),
    });
    state.selectedSetup = updated;
    selectSetup(updated);
    showToast(`Setup ${updated.symbol} diperbarui ke ${updated.status}`);
    await Promise.all([loadSetups(), loadAnalytics()]);
    return true;
  } catch (err) {
    showToast(err.message, true);
    return false;
  }
}

function syncEditStatusFields(setup) {
  const statusVal = document.getElementById("edit-status-select").value;
  const entryWrap = document.getElementById("edit-manual-entry-wrap");
  const riskWrap = document.getElementById("edit-risk-levels-wrap");
  const closeWrap = document.getElementById("edit-close-price-wrap");
  const closeLabel = document.getElementById("edit-close-price-label");
  const closeInput = document.getElementById("edit-close-price");

  const showEntry =
    statusVal === "MANUAL_TAKEN" ||
    statusVal === "CLOSED_MANUAL_TP" ||
    statusVal === "CLOSED_MANUAL_CL";
  const showRiskLevels =
    statusVal === "MANUAL_TAKEN" ||
    statusVal === "ENTRY_HIT" ||
    statusVal === "OPEN";
  const showClose = statusVal === "CLOSED_MANUAL_TP" || statusVal === "CLOSED_MANUAL_CL";

  entryWrap.classList.toggle("hidden", !showEntry);
  if (riskWrap) riskWrap.classList.toggle("hidden", !showRiskLevels);
  closeWrap.classList.toggle("hidden", !showClose);

  if (statusVal === "CLOSED_MANUAL_TP") {
    closeLabel.textContent = "Harga Close TP (Take Profit)";
    if (!closeInput.value && setup) closeInput.value = setup.resolved_price ?? setup.take_profit ?? "";
  } else if (statusVal === "CLOSED_MANUAL_CL") {
    closeLabel.textContent = "Harga Close CL (Cut Loss)";
    if (!closeInput.value && setup) closeInput.value = setup.resolved_price ?? setup.stop_loss ?? "";
  }
}

function openEditStatusModal(setup) {
  if (!setup) return;
  state.editingSetup = setup;
  document.getElementById("edit-status-title").textContent = `Edit Status: ${setup.symbol} (${setup.decision})`;

  const sel = document.getElementById("edit-status-select");
  const allowed = new Set(["OPEN", "ENTRY_HIT", "MANUAL_TAKEN", "MANUAL_SKIPPED", "CLOSED_MANUAL_TP", "CLOSED_MANUAL_CL", "EXPIRED"]);
  sel.value = allowed.has(setup.status) ? setup.status : "MANUAL_TAKEN";

  document.getElementById("edit-manual-entry").value = setup.manual_entry_price ?? setup.entry_price ?? "";
  document.getElementById("edit-stop-loss").value = setup.stop_loss ?? "";
  document.getElementById("edit-take-profit").value = setup.take_profit ?? "";
  document.getElementById("edit-close-price").value = setup.resolved_price ?? "";
  document.getElementById("edit-manual-notes").value = setup.manual_notes || "";

  syncEditStatusFields(setup);
  document.getElementById("edit-status-modal").classList.remove("hidden");
}

// --- AI Models & Provider Settings Modal ---

function syncScanIntervalState() {
  const checked = document.querySelector('input[name="scan_mode"]:checked');
  const isManual = checked ? checked.value === "manual" : false;
  const intervalInput = document.getElementById("cfg-scan-interval");
  intervalInput.disabled = isManual;
  intervalInput.title = isManual
    ? "Nonaktif pada mode Manual Only. Pilih Auto Scan untuk mengatur interval."
    : "Jeda waktu antar siklus auto-scan (menit).";
}

function escapeHtml(raw) {
  return String(raw ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function renderStrategyFilterDropdown() {
  const select = document.getElementById("filter-strategy");
  if (!select) return;
  const prevVal = select.value || "ALL";
  const names = state.strategies.map((s) => s.name);
  select.innerHTML =
    `<option value="ALL">Semua Strategi</option>` +
    names.map((n) => `<option value="${escapeHtml(n)}">${escapeHtml(n)}</option>`).join("");
  if (prevVal === "ALL" || names.includes(prevVal)) {
    select.value = prevVal;
  }
}

async function loadStrategies() {
  try {
    state.strategies = await apiRequest("/api/strategies");
    renderStrategyFilterDropdown();
  } catch (err) {
    console.warn("Failed loading strategies:", err);
  }
}

function renderStrategySettingsUI(activeList = null) {
  const activeSet = new Set(
    activeList !== null
      ? activeList
      : state.strategies.filter((s) => s.is_active).map((s) => s.name)
  );

  const checksWrap = document.getElementById("cfg-strategy-list");
  if (checksWrap) {
    if (!state.strategies.length) {
      checksWrap.innerHTML = `<span class="subtitle-sm">Belum ada strategi di database.</span>`;
    } else {
      checksWrap.innerHTML = state.strategies
        .map(
          (s) => `
          <label class="strategy-check-item" title="${escapeHtml(s.description || s.display_name || s.name)} | Tipe: ${escapeHtml(s.trade_style || "-")} | Lama: ${escapeHtml(s.holding_period || "-")} | Sugesti: HTF ${escapeHtml(s.suggested_htf || "-")} / LTF ${escapeHtml(s.suggested_ltf || "-")}">
            <input type="checkbox" name="cfg_strategy" value="${escapeHtml(s.name)}" ${activeSet.has(s.name) ? "checked" : ""} />
            <div class="strategy-check-body">
              <div class="strategy-check-title">${escapeHtml(s.name)}</div>
              <div class="strategy-check-meta">${escapeHtml(s.trade_style || "CUSTOM")} &bull; ${escapeHtml(s.holding_period || "-")} &bull; HTF ${escapeHtml(s.suggested_htf || "-")} / LTF ${escapeHtml(s.suggested_ltf || "-")} &bull; R:R ${Number(s.min_rr).toFixed(1)}</div>
            </div>
          </label>`
        )
        .join("");
    }
  }

  const countEl = document.getElementById("strategies-count");
  if (countEl) {
    const activeCount = state.strategies.filter((s) => s.is_active).length;
    countEl.textContent = `Menampilkan ${state.strategies.length} strategi (${activeCount} aktif)`;
  }

  const tbody = document.getElementById("strategies-tbody");
  if (!tbody) return;
  if (!state.strategies.length) {
    tbody.innerHTML = `<tr><td colspan="6" class="empty-cell">Belum ada strategi di database.</td></tr>`;
    return;
  }

  tbody.innerHTML = state.strategies
    .map(
      (s) => `
      <tr class="${s.is_active ? "active-model-row" : ""}">
        <td>
          <strong>${escapeHtml(s.name)}</strong>
          ${s.trade_style ? `<span class="badge badge-open">${escapeHtml(s.trade_style)}</span>` : ""}
          ${s.is_builtin ? '<span class="badge badge-neutral">Built-in</span>' : '<span class="badge badge-manual">Custom</span>'}
          ${s.display_name && s.display_name !== s.name ? `<br><small class="subtitle-sm">${escapeHtml(s.display_name)}</small>` : ""}
          <br><small class="subtitle-sm">${escapeHtml(s.description || (s.prompt_text || "").slice(0, 100))}</small>
        </td>
        <td><small>${escapeHtml(s.holding_period || "-")}</small></td>
        <td>
          <code>HTF ${escapeHtml(s.suggested_htf || "-")} / LTF ${escapeHtml(s.suggested_ltf || "-")}</code>
          <br><small class="subtitle-sm">Candles ${s.suggested_kline_limit || 250} • Expiry ${s.suggested_expiry_hours || 12}j</small>
        </td>
        <td><code>${Number(s.min_rr).toFixed(2)}</code></td>
        <td>${s.is_active ? '<span class="badge badge-hit-tp">ACTIVE</span>' : '<span class="badge badge-neutral">Inactive</span>'}</td>
        <td>
          <button type="button" class="btn btn-secondary btn-sm" data-strat-act="toggle" data-id="${s.id}">${s.is_active ? "Nonaktifkan" : "Aktifkan"}</button>
          <button type="button" class="btn btn-primary btn-sm" data-strat-act="edit" data-id="${s.id}">Edit</button>
          ${s.is_builtin ? "" : `<button type="button" class="btn btn-danger btn-sm" data-strat-act="delete" data-id="${s.id}">Hapus</button>`}
        </td>
      </tr>`
    )
    .join("");

  tbody.querySelectorAll("button[data-strat-act]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = Number(btn.dataset.id);
      const act = btn.dataset.stratAct;
      const target = state.strategies.find((x) => x.id === id);
      try {
        if (act === "toggle") {
          const updated = await apiRequest(`/api/strategies/${id}/toggle`, { method: "POST" });
          showToast(`${updated.name}: ${updated.is_active ? "AKTIF" : "NONAKTIF"}`);
          await Promise.all([loadAIModalData(false), loadAnalytics()]);
        } else if (act === "edit" && target) {
          openStrategyForm(target);
        } else if (act === "delete" && target) {
          await apiRequest(`/api/strategies/${id}`, { method: "DELETE" });
          showToast(`Strategi ${target.name} dihapus.`);
          await Promise.all([loadAIModalData(false), loadAnalytics()]);
        }
      } catch (err) {
        showToast(err.message, true);
      }
    });
  });
}

function normalizeIntervalOption(raw, fallback) {
  if (!raw) return fallback;
  const val = String(raw).trim();
  const map = {
    "5m": "Min5",
    min5: "Min5",
    "15m": "Min15",
    min15: "Min15",
    "30m": "Min30",
    min30: "Min30",
    "1h": "Min60",
    "60m": "Min60",
    min60: "Min60",
    "4h": "Hour4",
    hour4: "Hour4",
    "1d": "Day1",
    day1: "Day1",
  };
  return map[val.toLowerCase()] || val;
}

function setSelectOrFallback(selectId, value, fallback) {
  const sel = document.getElementById(selectId);
  if (!sel) return;
  const target = value || fallback;
  const exists = Array.from(sel.options).some((opt) => opt.value === target);
  sel.value = exists ? target : fallback;
}

function populateStrategyFormFields(strat = null) {
  const data = strat || {};
  document.getElementById("strat-code").value = data.name || "";
  document.getElementById("strat-display-name").value = data.display_name || "";
  document.getElementById("strat-min-rr").value = data.min_rr ?? 1.5;
  document.getElementById("strat-is-active").checked =
    data.is_active !== undefined ? Boolean(data.is_active) : true;
  setSelectOrFallback(
    "strat-style",
    data.trade_style ? String(data.trade_style).trim().toUpperCase() : "INTRADAY",
    "INTRADAY"
  );
  document.getElementById("strat-holding-period").value =
    data.holding_period !== undefined && data.holding_period !== null ? data.holding_period : "4 - 24 Jam";
  setSelectOrFallback(
    "strat-suggested-htf",
    normalizeIntervalOption(data.suggested_htf, "Min60"),
    "Min60"
  );
  setSelectOrFallback(
    "strat-suggested-ltf",
    normalizeIntervalOption(data.suggested_ltf, "Min15"),
    "Min15"
  );
  document.getElementById("strat-suggested-limit").value = data.suggested_kline_limit || 250;
  document.getElementById("strat-suggested-expiry").value = data.suggested_expiry_hours || 12;
  document.getElementById("strat-description").value = data.description || "";
  document.getElementById("strat-prompt-text").value = data.prompt_text || "";
}

function openStrategyForm(strat = null) {
  const card = document.getElementById("strategy-form-card");
  const isEdit = Boolean(strat);
  document.getElementById("strategy-form-title").textContent = isEdit
    ? `Edit Strategi: ${strat.name}`
    : "Tambah Strategi Baru ke Database";
  document.getElementById("edit-strategy-id").value = isEdit ? String(strat.id) : "";
  const codeEl = document.getElementById("strat-code");
  codeEl.disabled = false;
  const fileEl = document.getElementById("strat-json-file");
  if (fileEl) fileEl.value = "";
  populateStrategyFormFields(strat);
  card.classList.remove("hidden");
  card.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

async function handleStrategyJsonUpload(event) {
  const input = event.target;
  const file = input.files && input.files[0];
  if (!file) return;

  try {
    let rawText = (await file.text()).trim();
    const fenceMatch = rawText.match(/```(?:json)?\s*([\s\S]*?)```/i);
    if (fenceMatch) {
      rawText = fenceMatch[1].trim();
    }
    const parsed = JSON.parse(rawText);

    if (Array.isArray(parsed)) {
      if (!parsed.length) {
        showToast("File JSON array kosong.", true);
        return;
      }
      let okCount = 0;
      const errors = [];
      for (const item of parsed) {
        if (!item || typeof item !== "object" || !item.name || !item.prompt_text) {
          errors.push("Item tidak memiliki name/prompt_text");
          continue;
        }
        try {
          await apiRequest("/api/strategies", {
            method: "POST",
            body: JSON.stringify({
              name: String(item.name).trim(),
              display_name: item.display_name ? String(item.display_name).trim() : String(item.name).trim(),
              description: item.description ? String(item.description).trim() : null,
              trade_style: item.trade_style ? String(item.trade_style).trim().toUpperCase() : "INTRADAY",
              holding_period: item.holding_period ? String(item.holding_period).trim() : null,
              suggested_htf: normalizeIntervalOption(item.suggested_htf, "Min60"),
              suggested_ltf: normalizeIntervalOption(item.suggested_ltf, "Min15"),
              suggested_kline_limit: Number(item.suggested_kline_limit) || 250,
              suggested_expiry_hours: Number(item.suggested_expiry_hours) || 12,
              prompt_text: String(item.prompt_text).trim(),
              min_rr: Number(item.min_rr) || 1.5,
              is_active: item.is_active !== undefined ? Boolean(item.is_active) : true,
            }),
          });
          okCount += 1;
        } catch (err) {
          errors.push(`${item.name}: ${err.message}`);
        }
      }
      if (okCount > 0) {
        await Promise.all([loadAIModalData(false), loadAnalytics(), loadSetups()]);
      }
      if (errors.length) {
        showToast(`Impor ${okCount} strategi selesai, ${errors.length} gagal: ${errors[0]}`, okCount === 0);
      } else {
        document.getElementById("strategy-form-card").classList.add("hidden");
        showToast(`Berhasil mengimpor ${okCount} strategi dari ${file.name}.`);
      }
      return;
    }

    if (!parsed || typeof parsed !== "object") {
      showToast("Format JSON harus berupa objek strategi atau array objek.", true);
      return;
    }

    populateStrategyFormFields(parsed);
    showToast(`File '${file.name}' dimuat ke form. Periksa lalu klik Simpan Strategi.`);
  } catch (err) {
    showToast(`Gagal membaca JSON: ${err.message}`, true);
  } finally {
    input.value = "";
  }
}

async function saveStrategyForm() {
  const editId = document.getElementById("edit-strategy-id").value.trim();
  const code = document.getElementById("strat-code").value.trim();
  const displayName = document.getElementById("strat-display-name").value.trim();
  const minRr = parseNumField("strat-min-rr", 1.5);
  const isActive = document.getElementById("strat-is-active").checked;
  const tradeStyle = document.getElementById("strat-style").value;
  const holdingPeriod = document.getElementById("strat-holding-period").value.trim();
  const suggestedHtf = document.getElementById("strat-suggested-htf").value;
  const suggestedLtf = document.getElementById("strat-suggested-ltf").value;
  const suggestedLimit = parseNumField("strat-suggested-limit", 250);
  const suggestedExpiry = parseNumField("strat-suggested-expiry", 12);
  const description = document.getElementById("strat-description").value.trim();
  const promptText = document.getElementById("strat-prompt-text").value.trim();

  if (!code) {
    showToast("Kode strategi wajib diisi.", true);
    return;
  }
  if (!promptText || promptText.length < 10) {
    showToast("Isi teks prompt aturan AI minimal 10 karakter.", true);
    return;
  }

  try {
    if (editId) {
      const saved = await apiRequest(`/api/strategies/${editId}`, {
        method: "PUT",
        body: JSON.stringify({
          name: code,
          display_name: displayName || code,
          description,
          trade_style: tradeStyle,
          holding_period: holdingPeriod || null,
          suggested_htf: suggestedHtf,
          suggested_ltf: suggestedLtf,
          suggested_kline_limit: suggestedLimit,
          suggested_expiry_hours: suggestedExpiry,
          prompt_text: promptText,
          min_rr: minRr,
          is_active: isActive,
        }),
      });
      showToast(`Strategi ${saved.name} diperbarui.`);
    } else {
      const created = await apiRequest("/api/strategies", {
        method: "POST",
        body: JSON.stringify({
          name: code,
          display_name: displayName || code,
          description: description || null,
          trade_style: tradeStyle,
          holding_period: holdingPeriod || null,
          suggested_htf: suggestedHtf,
          suggested_ltf: suggestedLtf,
          suggested_kline_limit: suggestedLimit,
          suggested_expiry_hours: suggestedExpiry,
          prompt_text: promptText,
          min_rr: minRr,
          is_active: isActive,
        }),
      });
      showToast(`Strategi baru ${created.name} disimpan ke database.`);
    }
    document.getElementById("strategy-form-card").classList.add("hidden");
    await Promise.all([loadAIModalData(false), loadAnalytics(), loadSetups()]);
  } catch (err) {
    showToast(err.message, true);
  }
}

async function loadAIModalData(syncFilterToActiveProvider = false) {
  const [data, scannerCfg, stratList] = await Promise.all([
    apiRequest("/api/ai/models"),
    apiRequest("/api/scanner/settings"),
    apiRequest("/api/strategies"),
  ]);
  const cfg = data.settings;
  state.aiModels = data.models || [];
  state.aiSettings = cfg;
  state.strategies = stratList || [];
  renderStrategyFilterDropdown();

  const modeVal = scannerCfg.auto_scan_enabled ? "auto" : "manual";
  const modeRadio = document.querySelector(`input[name="scan_mode"][value="${modeVal}"]`);
  if (modeRadio) modeRadio.checked = true;
  document.getElementById("cfg-scan-interval").value = scannerCfg.scan_interval_minutes;
  syncScanIntervalState();
  document.getElementById("cfg-tracker-interval").value = scannerCfg.tracker_interval_seconds;
  document.getElementById("cfg-top-n-pairs").value = scannerCfg.top_n_pairs;
  document.getElementById("cfg-mexc-base-url").value = scannerCfg.mexc_base_url || "";
  document.getElementById("cfg-mexc-proxy-url").value = scannerCfg.mexc_proxy_url || "";
  document.getElementById("cfg-mexc-concurrency").value = scannerCfg.mexc_max_concurrency;
  document.getElementById("cfg-llm-timeout").value = scannerCfg.llm_timeout_seconds;
  document.getElementById("cfg-llm-concurrency").value = scannerCfg.llm_max_concurrency;
  document.getElementById("cfg-llm-max-tokens").value = scannerCfg.llm_max_tokens ?? 1500;
  setGroupedNumberValue("cfg-min-vol", "cfg-min-vol-hint", scannerCfg.min_24h_quote_volume, false);
  setGroupedNumberValue("cfg-max-vol", "cfg-max-vol-hint", scannerCfg.max_24h_quote_volume, true);
  document.getElementById("cfg-min-confidence").value = scannerCfg.min_confidence;
  document.getElementById("cfg-min-atr").value = scannerCfg.min_atr_pct;
  document.getElementById("cfg-max-atr").value = scannerCfg.max_atr_pct;

  renderStrategySettingsUI(scannerCfg.active_strategies || []);

  const radio = document.querySelector(`input[name="active_provider"][value="${cfg.active_provider}"]`);
  if (radio) radio.checked = true;
  highlightSelectedProviderCard(cfg.active_provider);

  if (syncFilterToActiveProvider && cfg.active_provider) {
    document.getElementById("ai-filter-provider").value = cfg.active_provider;
    document.getElementById("new-model-provider").value = cfg.active_provider;
  }

  document.getElementById("cfg-cmd-url").value = cfg.commandcode_base_url || "";
  document.getElementById("cfg-cmd-key").value = "";
  document.getElementById("cfg-cmd-key-status").textContent = cfg.has_commandcode_api_key
    ? `(${cfg.commandcode_api_key_masked})`
    : "(belum diisi)";

  document.getElementById("cfg-or-url").value = cfg.openrouter_base_url || "";
  document.getElementById("cfg-or-key").value = "";
  document.getElementById("cfg-or-key-status").textContent = cfg.has_openrouter_api_key
    ? `(${cfg.openrouter_api_key_masked})`
    : "(belum diisi)";

  document.getElementById("cfg-custom-url").value = cfg.custom_llm_base_url || "";
  document.getElementById("cfg-custom-key").value = "";
  document.getElementById("cfg-custom-key-status").textContent = cfg.has_custom_llm_api_key
    ? `(${cfg.custom_llm_api_key_masked})`
    : "(belum diisi)";

  renderAIModelsTable();
}

function isFreeModel(m) {
  const mid = (m.model_id || "").toLowerCase();
  const name = (m.name || "").toLowerCase();
  const desc = (m.description || "").toLowerCase();
  return mid.endsWith(":free") || mid === "openrouter/free" || name.includes("[free]") || desc.startsWith("free");
}

function highlightSelectedProviderCard(providerValue) {
  document.querySelectorAll(".provider-card").forEach((card) => {
    const radio = card.querySelector('input[name="active_provider"]');
    card.classList.toggle("selected", Boolean(radio && radio.value === providerValue));
  });
}

function renderAIModelsTable() {
  const providerFilter = document.getElementById("ai-filter-provider").value;
  const freeOnly = document.getElementById("ai-filter-free").checked;
  const search = document.getElementById("ai-filter-search").value.trim().toLowerCase();

  const filtered = state.aiModels.filter((m) => {
    if (providerFilter !== "ALL" && m.provider !== providerFilter) return false;
    if (freeOnly && !isFreeModel(m)) return false;
    if (search) {
      const hay = `${m.name} ${m.model_id} ${m.description || ""}`.toLowerCase();
      if (!hay.includes(search)) return false;
    }
    return true;
  });

  document.getElementById("ai-models-count").textContent =
    `Menampilkan ${filtered.length} dari ${state.aiModels.length} model`;

  const tbody = document.getElementById("ai-models-tbody");
  if (!filtered.length) {
    tbody.innerHTML = `<tr><td colspan="5" class="empty-cell">Tidak ada model AI yang cocok dengan filter ini.</td></tr>`;
    return;
  }

  tbody.innerHTML = filtered
    .map(
      (m) => `
      <tr class="${m.is_active ? "active-model-row" : ""}">
        <td>
          <strong>${m.name}</strong>${isFreeModel(m) ? '<span class="badge badge-free">FREE</span>' : ""}
          <br><small class="subtitle-sm">${m.description || ""}</small>
        </td>
        <td><code>${m.model_id}</code></td>
        <td><span class="badge badge-neutral">${m.provider}</span></td>
        <td>${m.is_active ? '<span class="badge badge-hit-tp">ACTIVE</span>' : '<span class="badge badge-neutral">Inactive</span>'}</td>
        <td>
          ${m.is_active ? "" : `<button class="btn btn-primary btn-sm" data-act="activate" data-id="${m.id}">Pilih / Aktifkan</button>`}
          ${m.is_active ? "" : `<button class="btn btn-danger btn-sm" data-act="delete" data-id="${m.id}">Hapus</button>`}
        </td>
      </tr>`
    )
    .join("");

  tbody.querySelectorAll("button[data-act]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = Number(btn.dataset.id);
      const act = btn.dataset.act;
      try {
        if (act === "activate") {
          const res = await apiRequest(`/api/ai/models/${id}/activate`, { method: "POST" });
          showToast(res.message);
        } else if (act === "delete") {
          await apiRequest(`/api/ai/models/${id}`, { method: "DELETE" });
          showToast("Model AI dihapus.");
        }
        await Promise.all([loadAIModalData(false), loadHealthAndStatus()]);
      } catch (err) {
        showToast(err.message, true);
      }
    });
  });
}

function formatGroupedInt(val) {
  const num = Number(val);
  if (!Number.isFinite(num) || num <= 0) return "0";
  return Math.round(num).toLocaleString("en-US");
}

function parseGroupedInt(raw, fallback = 0) {
  if (raw === null || raw === undefined) return fallback;
  const digits = String(raw).replace(/[^0-9]/g, "");
  if (!digits) return fallback;
  const num = Number(digits);
  return Number.isFinite(num) ? num : fallback;
}

function humanUsdtHint(num, isMax = false) {
  const n = Number(num || 0);
  if (!Number.isFinite(n) || n <= 0) {
    return isMax ? "0 = Tanpa batas atas" : "$0 (Semua volume)";
  }
  if (n >= 1_000_000_000) {
    return `$${(n / 1_000_000_000).toFixed(2).replace(/\.?0+$/, "")} Miliar USDT`;
  }
  if (n >= 1_000_000) {
    return `$${(n / 1_000_000).toFixed(2).replace(/\.?0+$/, "")} Juta USDT`;
  }
  if (n >= 1_000) {
    return `$${(n / 1_000).toFixed(1).replace(/\.0$/, "")} Ribu USDT`;
  }
  return `$${n.toLocaleString("en-US")} USDT`;
}

function setGroupedNumberValue(inputId, hintId, value, isMax = false) {
  const el = document.getElementById(inputId);
  const hintEl = document.getElementById(hintId);
  const num = Math.max(0, Math.round(Number(value || 0)));
  if (el) el.value = formatGroupedInt(num);
  if (hintEl) hintEl.textContent = humanUsdtHint(num, isMax);
}

function bindGroupedNumberInput(inputId, hintId, isMax = false) {
  const el = document.getElementById(inputId);
  const hintEl = document.getElementById(hintId);
  if (!el) return;
  el.addEventListener("input", () => {
    const raw = el.value;
    const caretPos = el.selectionStart || 0;
    const digitsRight = raw.slice(caretPos).replace(/[^0-9]/g, "").length;
    const digits = raw.replace(/[^0-9]/g, "");
    if (!digits) {
      el.value = "";
      if (hintEl) hintEl.textContent = humanUsdtHint(0, isMax);
      return;
    }
    const num = Number(digits);
    const formatted = Math.round(num).toLocaleString("en-US");
    el.value = formatted;
    if (hintEl) hintEl.textContent = humanUsdtHint(num, isMax);
    let newCaret = formatted.length;
    let seenRight = 0;
    for (let i = formatted.length - 1; i >= 0; i -= 1) {
      if (seenRight >= digitsRight) {
        newCaret = i + 1;
        break;
      }
      if (/[0-9]/.test(formatted[i])) seenRight += 1;
      if (i === 0 && seenRight >= digitsRight) newCaret = 0;
    }
    el.setSelectionRange(newCaret, newCaret);
  });
  el.addEventListener("blur", () => {
    const num = parseGroupedInt(el.value, 0);
    setGroupedNumberValue(inputId, hintId, num, isMax);
  });
}

function parseNumField(id, fallback = null) {
  const raw = document.getElementById(id).value;
  if (raw === null || raw === undefined || String(raw).trim() === "") return fallback;
  const parsed = Number(String(raw).trim().replace(",", "."));
  return Number.isFinite(parsed) ? parsed : fallback;
}

async function saveScannerSettings() {
  const checked = document.querySelector('input[name="scan_mode"]:checked');
  const autoScan = checked ? checked.value === "auto" : true;
  const activeStrategies = Array.from(
    document.querySelectorAll('input[name="cfg_strategy"]:checked')
  ).map((cb) => cb.value);

  if (!activeStrategies.length) {
    showToast("Pilih minimal 1 strategi aktif.", true);
    return;
  }

  const minVol = parseGroupedInt(document.getElementById("cfg-min-vol").value, 0);
  const maxVol = parseGroupedInt(document.getElementById("cfg-max-vol").value, 0);
  if (maxVol > 0 && minVol > maxVol) {
    showToast("Min 24h Quote Volume tidak boleh lebih besar dari Max 24h Quote Volume.", true);
    return;
  }

  const payload = {
    auto_scan_enabled: autoScan,
    scan_interval_minutes: parseNumField("cfg-scan-interval"),
    tracker_interval_seconds: parseNumField("cfg-tracker-interval"),
    top_n_pairs: parseNumField("cfg-top-n-pairs"),
    active_strategies: activeStrategies,
    mexc_base_url: document.getElementById("cfg-mexc-base-url").value.trim(),
    mexc_proxy_url: document.getElementById("cfg-mexc-proxy-url").value.trim(),
    mexc_max_concurrency: parseNumField("cfg-mexc-concurrency"),
    llm_timeout_seconds: parseNumField("cfg-llm-timeout"),
    llm_max_concurrency: parseNumField("cfg-llm-concurrency"),
    llm_max_tokens: parseNumField("cfg-llm-max-tokens"),
    min_24h_quote_volume: minVol,
    max_24h_quote_volume: maxVol,
    min_confidence: parseNumField("cfg-min-confidence"),
    min_atr_pct: parseNumField("cfg-min-atr"),
    max_atr_pct: parseNumField("cfg-max-atr"),
  };

  try {
    const saved = await apiRequest("/api/scanner/settings", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    showToast(`Tersimpan: ${saved.scan_mode} • Top ${saved.top_n_pairs} • ${saved.mexc_base_url}`);
    await Promise.all([loadAIModalData(false), loadHealthAndStatus(), loadAnalytics()]);
  } catch (err) {
    showToast(err.message, true);
  }
}

async function saveAISettings() {
  const checked = document.querySelector('input[name="active_provider"]:checked');
  const payload = {
    active_provider: checked ? checked.value : "commandcode",
    commandcode_base_url: document.getElementById("cfg-cmd-url").value,
    commandcode_api_key: document.getElementById("cfg-cmd-key").value || null,
    openrouter_base_url: document.getElementById("cfg-or-url").value,
    openrouter_api_key: document.getElementById("cfg-or-key").value || null,
    custom_llm_base_url: document.getElementById("cfg-custom-url").value,
    custom_llm_api_key: document.getElementById("cfg-custom-key").value || null,
  };
  try {
    await apiRequest("/api/ai/settings", { method: "POST", body: JSON.stringify(payload) });
    showToast("Pengaturan provider AI berhasil disimpan ke MySQL.");
    await Promise.all([loadAIModalData(), loadHealthAndStatus()]);
  } catch (err) {
    showToast(err.message, true);
  }
}

async function testAIConnection() {
  const resultEl = document.getElementById("ai-test-result");
  resultEl.textContent = "Menguji koneksi...";
  const checked = document.querySelector('input[name="active_provider"]:checked');
  const provider = checked ? checked.value : "commandcode";

  let baseUrl = document.getElementById("cfg-cmd-url").value;
  let apiKey = document.getElementById("cfg-cmd-key").value;
  if (provider === "openrouter") {
    baseUrl = document.getElementById("cfg-or-url").value;
    apiKey = document.getElementById("cfg-or-key").value;
  } else if (provider === "custom") {
    baseUrl = document.getElementById("cfg-custom-url").value;
    apiKey = document.getElementById("cfg-custom-key").value;
  }

  try {
    const res = await apiRequest("/api/ai/test", {
      method: "POST",
      body: JSON.stringify({
        provider,
        base_url: baseUrl || null,
        api_key: apiKey || null,
      }),
    });
    resultEl.textContent = res.message;
    resultEl.style.color = res.success ? "#10b981" : "#ef4444";
  } catch (err) {
    resultEl.textContent = err.message;
    resultEl.style.color = "#ef4444";
  }
}

async function addAIModel() {
  const name = document.getElementById("new-model-name").value.trim();
  const model_id = document.getElementById("new-model-id").value.trim();
  const provider = document.getElementById("new-model-provider").value;
  if (!name || !model_id) {
    showToast("Nama model dan Model ID wajib diisi.", true);
    return;
  }
  try {
    await apiRequest("/api/ai/models", {
      method: "POST",
      body: JSON.stringify({ name, model_id, provider }),
    });
    document.getElementById("new-model-name").value = "";
    document.getElementById("new-model-id").value = "";
    document.getElementById("add-model-card").classList.add("hidden");
    showToast(`Model '${name}' ditambahkan.`);
    await loadAIModalData();
  } catch (err) {
    showToast(err.message, true);
  }
}

function wireEvents() {
  document.querySelectorAll("#status-tabs .tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#status-tabs .tab").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      state.statusFilter = btn.dataset.status;
      state.setupsPage = 1;
      loadSetups();
    });
  });

  document.getElementById("btn-toggle-status-legend").addEventListener("click", () => {
    document.getElementById("status-legend-box").classList.toggle("hidden");
  });
  document.getElementById("btn-close-status-legend").addEventListener("click", () => {
    document.getElementById("status-legend-box").classList.add("hidden");
  });

  document.getElementById("filter-strategy").addEventListener("change", () => {
    state.setupsPage = 1;
    loadSetups();
  });
  document.getElementById("filter-date").addEventListener("change", () => {
    state.setupsPage = 1;
    loadSetups();
  });
  document.getElementById("btn-clear-date").addEventListener("click", () => {
    document.getElementById("filter-date").value = "";
    state.setupsPage = 1;
    loadSetups();
  });
  document.getElementById("filter-symbol").addEventListener("input", () => {
    clearTimeout(window.__symDebounce);
    window.__symDebounce = setTimeout(() => {
      state.setupsPage = 1;
      loadSetups();
    }, 250);
  });

  document.getElementById("setups-per-page").addEventListener("change", (e) => {
    state.setupsPageSize = Number(e.target.value) || 20;
    state.setupsPage = 1;
    loadSetups();
  });
  document.getElementById("btn-setups-prev").addEventListener("click", () => {
    if (state.setupsPage > 1) {
      state.setupsPage -= 1;
      loadSetups();
    }
  });
  document.getElementById("btn-setups-next").addEventListener("click", () => {
    const maxPage = Math.max(1, Math.ceil(state.setupsTotal / state.setupsPageSize));
    if (state.setupsPage < maxPage) {
      state.setupsPage += 1;
      loadSetups();
    }
  });

  document.getElementById("runs-per-page").addEventListener("change", (e) => {
    state.runsPageSize = Number(e.target.value) || 10;
    state.runsPage = 1;
    loadScanRuns();
  });
  document.getElementById("btn-runs-prev").addEventListener("click", () => {
    if (state.runsPage > 1) {
      state.runsPage -= 1;
      loadScanRuns();
    }
  });
  document.getElementById("btn-runs-next").addEventListener("click", () => {
    const maxPage = Math.max(1, Math.ceil(state.runsTotal / state.runsPageSize));
    if (state.runsPage < maxPage) {
      state.runsPage += 1;
      loadScanRuns();
    }
  });
  bindGroupedNumberInput("cfg-min-vol", "cfg-min-vol-hint", false);
  bindGroupedNumberInput("cfg-max-vol", "cfg-max-vol-hint", true);

  document.querySelectorAll(".copy-btn[data-copy-field]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!state.selectedSetup) return;
      const field = btn.dataset.copyField;
      const rawVal =
        field === "entry_price"
          ? (state.selectedSetup.manual_entry_price ?? state.selectedSetup.entry_price)
          : state.selectedSetup[field];
      if (rawVal === null || rawVal === undefined) return;
      const text = String(rawVal);
      try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          await navigator.clipboard.writeText(text);
        } else {
          const ta = document.createElement("textarea");
          ta.value = text;
          document.body.appendChild(ta);
          ta.select();
          document.execCommand("copy");
          document.body.removeChild(ta);
        }
        const prev = btn.textContent;
        btn.textContent = "Copied!";
        btn.classList.add("copied");
        showToast(`Disalin: ${text}`);
        setTimeout(() => {
          btn.textContent = prev;
          btn.classList.remove("copied");
        }, 1200);
      } catch (err) {
        showToast(`Gagal copy: ${err.message}`, true);
      }
    });
  });

  document.getElementById("btn-close-eval-modal").addEventListener("click", () => {
    document.getElementById("scan-eval-modal").classList.add("hidden");
  });
  document.querySelectorAll("#eval-filter-tabs .tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#eval-filter-tabs .tab").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      state.evalFilter = btn.dataset.evalFilter;
      renderEvalTable();
    });
  });

  document.querySelectorAll(".btn-chip[data-draw-mode]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const mode = btn.dataset.drawMode || "normal";
      setDrawMode(mode);
    });
  });

  document.getElementById("btn-pos-from-setup")?.addEventListener("click", () => {
    if (!state.selectedSetup) {
      showToast("Pilih salah satu setup terlebih dahulu.", true);
      return;
    }
    createPositionFromSelectedSetup();
  });

  const deleteActiveDrawnPosition = () => {
    const active = getActiveDrawnPosition();
    if (!active || active.isSetupBox) return false;
    state.drawnPositions = state.drawnPositions.filter((p) => p.id !== active.id);
    state.activePositionId = state.drawnPositions.length
      ? state.drawnPositions[state.drawnPositions.length - 1].id
      : state.drawMode === "setup"
        ? SETUP_BOX_ID
        : null;
    renderPositionOverlay();
    return true;
  };

  document.getElementById("btn-pos-clear")?.addEventListener("click", deleteActiveDrawnPosition);

  document.addEventListener("keydown", (e) => {
    if (e.key !== "Delete" && e.key !== "Backspace") return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const target = e.target;
    if (
      target &&
      (target.isContentEditable ||
        (typeof target.closest === "function" && target.closest("input, textarea, select, [contenteditable]")))
    ) {
      return;
    }
    const anyModalOpen = ["ai-modal", "edit-status-modal", "scan-eval-modal"].some((id) => {
      const el = document.getElementById(id);
      return el && !el.classList.contains("hidden");
    });
    if (anyModalOpen) return;
    if (deleteActiveDrawnPosition()) {
      e.preventDefault();
    }
  });

  document.getElementById("btn-pos-apply")?.addEventListener("click", () => {
    const pos = getActiveDrawnPosition();
    if (!state.selectedSetup || !pos) return;
    openEditStatusModal(state.selectedSetup);
    const sel = document.getElementById("edit-status-select");
    sel.value = "MANUAL_TAKEN";
    document.getElementById("edit-manual-entry").value = pos.entry;
    document.getElementById("edit-stop-loss").value = pos.sl;
    document.getElementById("edit-take-profit").value = pos.tp;
    syncEditStatusFields(state.selectedSetup);
  });

  const posOverlay = document.getElementById("position-overlay");
  const stageEl = document.getElementById("candlestick-stage");
  if (stageEl && posOverlay) {
    const clearHoveredBoxes = () => {
      posOverlay.querySelectorAll(".pos-box.is-hovered").forEach((el) => el.classList.remove("is-hovered"));
    };
    stageEl.addEventListener("pointermove", (e) => {
      const boxes = posOverlay.querySelectorAll(".pos-box");
      if (!boxes.length) return;
      const oRect = posOverlay.getBoundingClientRect();
      const mx = e.clientX - oRect.left;
      const my = e.clientY - oRect.top;
      let matched = null;
      boxes.forEach((boxEl) => {
        const bx = boxEl.offsetLeft;
        const by = boxEl.offsetTop;
        const bw = boxEl.offsetWidth;
        const bh = boxEl.offsetHeight;
        if (mx >= bx && mx <= bx + bw && my >= by && my <= by + bh) {
          matched = boxEl;
        }
      });
      boxes.forEach((boxEl) => {
        boxEl.classList.toggle("is-hovered", boxEl === matched);
      });
    });
    stageEl.addEventListener("pointerleave", clearHoveredBoxes);
  }

  if (posOverlay) {
    posOverlay.addEventListener("pointerdown", (e) => {
      if (state.drawMode !== "draw") return;

      const handleEl = e.target.closest("[data-pos-handle]");
      if (!handleEl) {
        if (state.drawMode !== "draw") return;
        e.preventDefault();
        e.stopPropagation();
        const created = createPositionAtClick(getAutoPositionSide(), e.clientX, e.clientY);
        if (!created) return;
        const startX = e.clientX;
        const chartEl = document.getElementById("candlestick-chart");
        const onCreateMove = (ev) => {
          if (Math.abs(ev.clientX - startX) < 6 || !state.chart) return;
          const rect = chartEl.getBoundingClientRect();
          const curLog = state.chart.timeScale().coordinateToLogical(ev.clientX - rect.left);
          if (curLog !== null) {
            created.endIdx = Math.max(created.startIdx + 4, Math.round(curLog));
            renderPositionOverlay();
          }
        };
        const onCreateUp = () => {
          window.removeEventListener("pointermove", onCreateMove);
          window.removeEventListener("pointerup", onCreateUp);
        };
        window.addEventListener("pointermove", onCreateMove);
        window.addEventListener("pointerup", onCreateUp);
        return;
      }

      const targetId = Number(handleEl.dataset.posId);
      const pos = findOverlayBoxById(targetId);
      if (!pos) return;

      state.activePositionId = pos.id;
      e.preventDefault();
      e.stopPropagation();

      const handle = handleEl.dataset.posHandle;
      const chartEl = document.getElementById("candlestick-chart");
      const rect = chartEl.getBoundingClientRect();
      const startPrice = state.candleSeries.coordinateToPrice(e.clientY - rect.top);
      const startLogical = state.chart.timeScale().coordinateToLogical(e.clientX - rect.left);
      const orig = { ...pos };

      const onMove = (ev) => {
        if (!state.candleSeries || !state.chart) return;
        const curRect = chartEl.getBoundingClientRect();
        const curPrice = state.candleSeries.coordinateToPrice(ev.clientY - curRect.top);
        const curLogical = state.chart.timeScale().coordinateToLogical(ev.clientX - curRect.left);
        const isLong = pos.side === "LONG";
        const minGap = Math.max(orig.entry * 0.0005, 1e-8);

        if (handle === "tp" && curPrice !== null) {
          pos.tp = roundPositionPrice(isLong ? Math.max(pos.entry + minGap, curPrice) : Math.min(pos.entry - minGap, curPrice));
        } else if (handle === "sl" && curPrice !== null) {
          pos.sl = roundPositionPrice(isLong ? Math.min(pos.entry - minGap, curPrice) : Math.max(pos.entry + minGap, curPrice));
        } else if (handle === "entry" && curPrice !== null) {
          const lowBound = isLong ? pos.sl + minGap : pos.tp + minGap;
          const highBound = isLong ? pos.tp - minGap : pos.sl - minGap;
          pos.entry = roundPositionPrice(Math.min(highBound, Math.max(lowBound, curPrice)));
        } else if (handle === "resize-r" && curLogical !== null) {
          pos.endIdx = Math.max(pos.startIdx + 4, curLogical);
        } else if (handle === "move") {
          if (curPrice !== null && startPrice !== null) {
            const dp = curPrice - startPrice;
            if (orig.sl + dp > 0 && orig.tp + dp > 0 && orig.entry + dp > 0) {
              pos.entry = roundPositionPrice(orig.entry + dp);
              pos.sl = roundPositionPrice(orig.sl + dp);
              pos.tp = roundPositionPrice(orig.tp + dp);
            }
          }
          if (curLogical !== null && startLogical !== null) {
            const dl = curLogical - startLogical;
            pos.startIdx = orig.startIdx + dl;
            pos.endIdx = orig.endIdx + dl;
          }
        }
        renderPositionOverlay();
      };

      const onUp = () => {
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
      };
      renderPositionOverlay();
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
    });
  }

  document.getElementById("btn-reset-chart-view")?.addEventListener("click", () => {
    fitAndUnlockChart();
    showToast("Tampilan & skala harga chart di-reset (mode drag bebas tetap aktif).");
  });

  document.querySelectorAll(".btn-chip[data-interval]").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".btn-chip[data-interval]").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      state.chartInterval = btn.dataset.interval;
      if (state.selectedSetup) renderSetupChart(state.selectedSetup);
    });
  });

  document.getElementById("toggle-ema").addEventListener("change", () => {
    if (state.selectedSetup) renderSetupChart(state.selectedSetup);
  });
  document.getElementById("toggle-volume").addEventListener("change", () => {
    if (state.selectedSetup) renderSetupChart(state.selectedSetup);
  });
  document.getElementById("toggle-dss").addEventListener("change", () => {
    if (state.selectedSetup) renderSetupChart(state.selectedSetup);
  });

  document.getElementById("btn-mark-taken").addEventListener("click", () => updateManualStatus("MANUAL_TAKEN"));
  document.getElementById("btn-mark-skipped").addEventListener("click", () => updateManualStatus("MANUAL_SKIPPED"));
  document.getElementById("btn-open-edit-status").addEventListener("click", () => {
    if (state.selectedSetup) openEditStatusModal(state.selectedSetup);
  });
  document.getElementById("btn-close-edit-status").addEventListener("click", () => {
    document.getElementById("edit-status-modal").classList.add("hidden");
  });
  document.getElementById("btn-cancel-edit-status").addEventListener("click", () => {
    document.getElementById("edit-status-modal").classList.add("hidden");
  });
  document.getElementById("edit-status-select").addEventListener("change", () => {
    document.getElementById("edit-close-price").value = "";
    syncEditStatusFields(state.editingSetup);
  });
  document.getElementById("btn-save-edit-status").addEventListener("click", async () => {
    const statusVal = document.getElementById("edit-status-select").value;
    const entryParsed = parseOptionalFloatText(document.getElementById("edit-manual-entry").value);
    const slParsed = parseOptionalFloatText(document.getElementById("edit-stop-loss").value);
    const tpParsed = parseOptionalFloatText(document.getElementById("edit-take-profit").value);
    const closeParsed = parseOptionalFloatText(document.getElementById("edit-close-price").value);

    if (Number.isNaN(entryParsed)) {
      showToast("Harga entry manual harus berupa angka positif.", true);
      return;
    }
    if (Number.isNaN(slParsed) || Number.isNaN(tpParsed)) {
      showToast("Stop Loss dan Take Profit harus berupa angka positif.", true);
      return;
    }
    if (statusVal === "CLOSED_MANUAL_TP" || statusVal === "CLOSED_MANUAL_CL") {
      if (closeParsed === null || Number.isNaN(closeParsed)) {
        showToast("Harga close (TP / CL) wajib diisi angka positif.", true);
        return;
      }
    }

    const canSendRisk = statusVal === "MANUAL_TAKEN" || statusVal === "ENTRY_HIT" || statusVal === "OPEN";
    const ok = await updateManualStatus(statusVal, {
      manual_entry_price:
        statusVal === "MANUAL_TAKEN" || statusVal === "CLOSED_MANUAL_TP" || statusVal === "CLOSED_MANUAL_CL"
          ? entryParsed
          : null,
      stop_loss: canSendRisk ? slParsed : null,
      take_profit: canSendRisk ? tpParsed : null,
      resolved_price:
        statusVal === "CLOSED_MANUAL_TP" || statusVal === "CLOSED_MANUAL_CL" ? closeParsed : null,
      manual_notes: document.getElementById("edit-manual-notes").value,
    });
    if (ok) {
      document.getElementById("edit-status-modal").classList.add("hidden");
    }
  });

  document.getElementById("btn-dismiss-error").addEventListener("click", hideErrorBanner);

  document.getElementById("btn-run-scan").addEventListener("click", async () => {
    const scanBtn = document.getElementById("btn-run-scan");
    try {
      hideErrorBanner();
      scanBtn.disabled = true;
      scanBtn.textContent = "Scanning...";
      const res = await apiRequest("/api/scanner/run", { method: "POST" });
      showToast(res.message);

      if (!res.started) {
        scanBtn.disabled = false;
        scanBtn.textContent = "Run Scan Now";
        await loadHealthAndStatus();
        return;
      }

      const prevRunId = res.prev_run_id || 0;
      let checks = 0;
      const timer = setInterval(async () => {
        checks += 1;
        try {
          const st = await loadHealthAndStatus();
          const latest = st.recent_runs && st.recent_runs[0];
          const hasFinishedNewRun = latest && latest.id > prevRunId && latest.status !== "RUNNING";
          if ((!st.is_running && (hasFinishedNewRun || checks >= 5)) || checks >= 300) {
            clearInterval(timer);
            scanBtn.disabled = false;
            scanBtn.textContent = "Run Scan Now";
            await Promise.all([loadSetups(), loadAnalytics()]);
            if (latest && latest.status === "FAILED") {
              showToast(`Scan #${latest.id} gagal: ${latest.error_message || "Cek banner error"}`, true);
            } else if (latest && latest.status === "COMPLETED") {
              showToast(`Scan #${latest.id} selesai: ${latest.setups_created_count} setup baru.`);
            }
          }
        } catch (pollErr) {
          clearInterval(timer);
          scanBtn.disabled = false;
          scanBtn.textContent = "Run Scan Now";
          showErrorBanner("Gagal Memantau Status Scan", pollErr.message);
        }
      }, 2000);
    } catch (err) {
      scanBtn.disabled = false;
      scanBtn.textContent = "Run Scan Now";
      showErrorBanner("Gagal Menjalankan Scan", err.message);
      showToast(err.message, true);
    }
  });

  document.getElementById("btn-run-tracker").addEventListener("click", async () => {
    try {
      const res = await apiRequest("/api/tracker/run", { method: "POST" });
      hideErrorBanner();
      showToast(
        `Checked ${res.checked} setup(s): EntryHit=${res.entry_hit || 0}, TP=${res.hit_tp}, SL=${res.hit_sl}, Exp=${res.expired}`
      );
      await Promise.all([loadSetups(), loadAnalytics(), loadHealthAndStatus()]);
    } catch (err) {
      showErrorBanner("Outcome Tracker Error", err.message);
      showToast(err.message, true);
    }
  });

  document.getElementById("btn-open-ai-modal").addEventListener("click", async () => {
    document.getElementById("ai-modal").classList.remove("hidden");
    await loadAIModalData(true);
  });
  document.getElementById("btn-close-ai-modal").addEventListener("click", () => {
    document.getElementById("ai-modal").classList.add("hidden");
  });
  document.querySelectorAll("[data-modal-tab]").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("[data-modal-tab]").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      document.querySelectorAll(".modal-tab-pane").forEach((p) => p.classList.add("hidden"));
      document.getElementById(btn.dataset.modalTab).classList.remove("hidden");
    });
  });
  document.getElementById("btn-save-scanner-settings").addEventListener("click", saveScannerSettings);
  document.querySelectorAll('input[name="scan_mode"]').forEach((radio) => {
    radio.addEventListener("change", syncScanIntervalState);
  });
  document.getElementById("btn-modal-run-scan").addEventListener("click", () => {
    document.getElementById("ai-modal").classList.add("hidden");
    document.getElementById("btn-run-scan").click();
  });
  document.getElementById("btn-toggle-add-strategy").addEventListener("click", () => {
    const card = document.getElementById("strategy-form-card");
    if (card.classList.contains("hidden")) {
      openStrategyForm(null);
    } else {
      card.classList.add("hidden");
    }
  });
  document.getElementById("btn-cancel-strategy-form").addEventListener("click", () => {
    document.getElementById("strategy-form-card").classList.add("hidden");
  });
  document.getElementById("btn-cancel-strategy-form-2").addEventListener("click", () => {
    document.getElementById("strategy-form-card").classList.add("hidden");
  });
  document.getElementById("btn-save-strategy").addEventListener("click", saveStrategyForm);
  document.getElementById("strat-json-file").addEventListener("change", handleStrategyJsonUpload);
  document.getElementById("btn-save-ai-settings").addEventListener("click", saveAISettings);
  document.getElementById("btn-test-ai-conn").addEventListener("click", testAIConnection);
  document.getElementById("btn-toggle-add-model").addEventListener("click", () => {
    document.getElementById("add-model-card").classList.toggle("hidden");
  });
  document.getElementById("btn-cancel-add-model").addEventListener("click", () => {
    document.getElementById("add-model-card").classList.add("hidden");
  });
  document.getElementById("btn-add-model").addEventListener("click", addAIModel);

  document.getElementById("ai-filter-provider").addEventListener("change", renderAIModelsTable);
  document.getElementById("ai-filter-free").addEventListener("change", renderAIModelsTable);
  document.getElementById("ai-filter-search").addEventListener("input", renderAIModelsTable);
  document.querySelectorAll('input[name="active_provider"]').forEach((radio) => {
    radio.addEventListener("change", () => {
      if (radio.checked) {
        highlightSelectedProviderCard(radio.value);
        document.getElementById("ai-filter-provider").value = radio.value;
        document.getElementById("new-model-provider").value = radio.value;
        renderAIModelsTable();
      }
    });
  });

  document.getElementById("live-chart-interval").addEventListener("change", (e) => {
    localStorage.setItem("mexc_live_chart_ms", e.target.value);
    restartLiveChartTimer();
  });

  document.getElementById("btn-close-setting-info").addEventListener("click", () => {
    document.getElementById("setting-info-box").classList.add("hidden");
  });
  document.querySelectorAll(".info-btn").forEach((btn) => {
    btn.title = btn.dataset.info || "";
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      const box = document.getElementById("setting-info-box");
      document.getElementById("setting-info-title").textContent = btn.dataset.infoTitle || "Info";
      document.getElementById("setting-info-desc").textContent = btn.dataset.info || "";
      box.classList.remove("hidden");
      box.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
  });
}

function restartLiveChartTimer() {
  if (state.liveChartTimer) {
    clearInterval(state.liveChartTimer);
    state.liveChartTimer = null;
  }
  const intervalMs = Number(document.getElementById("live-chart-interval").value || 0);
  if (intervalMs > 0) {
    state.liveChartTimer = setInterval(() => {
      if (state.selectedSetup && !document.hidden) {
        renderSetupChart(state.selectedSetup, true);
      }
    }, intervalMs);
  }
}

async function bootstrap() {
  const savedLiveMs = localStorage.getItem("mexc_live_chart_ms");
  if (savedLiveMs !== null) {
    const sel = document.getElementById("live-chart-interval");
    if (Array.from(sel.options).some((o) => o.value === savedLiveMs)) {
      sel.value = savedLiveMs;
    }
  }
  wireEvents();
  await Promise.all([loadStrategies(), loadHealthAndStatus(), loadAnalytics(), loadSetups()]);
  setInterval(() => {
    loadHealthAndStatus();
    loadAnalytics();
    loadSetups();
  }, 30000);
  restartLiveChartTimer();
}

bootstrap().catch((err) => {
  showErrorBanner("Gagal Memuat Dashboard", err.message);
  showToast(err.message, true);
});
