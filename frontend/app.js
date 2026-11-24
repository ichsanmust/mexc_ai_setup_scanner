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

function formatJakartaShortTime(val) {
  const d = parseBackendUtcDate(val);
  if (!d) return "-";
  return `${d.toLocaleTimeString("en-GB", {
    timeZone: JAKARTA_TZ,
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  })} WIB`;
}

function formatRelativeTimeId(val) {
  const d = parseBackendUtcDate(val);
  if (!d) return "";
  const diffSec = Math.max(0, Math.floor((Date.now() - d.getTime()) / 1000));
  if (diffSec < 15) return "Baru saja";
  if (diffSec < 60) return `${diffSec} dtk lalu`;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin} mnt lalu`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr} jam lalu`;
  const diffDay = Math.floor(diffHr / 24);
  return `${diffDay} hr lalu`;
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
  setupsSort: "updated",
  knownSetupStatuses: {},
  justChangedSetups: {},
  hasLoadedSetupsOnce: false,
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
  setupStrategyFilter: [],
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

function inferDecimalPrecision(val) {
  const n = Math.abs(Number(val));
  if (!Number.isFinite(n) || n === 0) return 4;
  if (n >= 1000) return 2;
  if (n >= 10) return 3;
  if (n >= 1) return 4;
  // Hitung digit signifikan yang wajar tanpa notasi ilmiah (maks 10 desimal)
  const str = n.toFixed(10).replace(/0+$/, "");
  const dotIdx = str.indexOf(".");
  const rawDec = dotIdx >= 0 ? str.length - dotIdx - 1 : 2;
  const magFloor = n >= 0.01 ? 5 : n >= 0.0001 ? 6 : n >= 0.00001 ? 7 : n >= 0.000001 ? 8 : n >= 0.0000001 ? 9 : 10;
  return Math.min(10, Math.max(magFloor, rawDec));
}

function fmtPrice(val) {
  if (val === null || val === undefined) return "-";
  const num = Number(val);
  if (!Number.isFinite(num)) return "-";
  if (Math.abs(num) >= 1000) return num.toLocaleString("en-US", { maximumFractionDigits: 2 });
  if (Math.abs(num) >= 1) return num.toLocaleString("en-US", { maximumFractionDigits: 4 });
  if (Math.abs(num) >= 0.001) return num.toLocaleString("en-US", { maximumFractionDigits: 8 });
  return num.toLocaleString("en-US", { maximumFractionDigits: 10 });
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
    EXTENDED: { cls: "badge-extended", tip: "Expiry diperpanjang mengikuti strategi & tetap dipantau otomatis oleh Tracker" },
    HIT_TP: { cls: "badge-hit-tp", tip: "Harga menyentuh Take Profit terlebih dahulu (Win)" },
    HIT_SL: { cls: "badge-hit-sl", tip: "Harga menyentuh Stop Loss terlebih dahulu (Loss)" },
    BEP: { cls: "badge-bep", tip: "Otomatis dari Tracker: harga menyentuh SL-BEP (Break-Even Point)" },
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
  if (s.manual_action_at && (st === "HIT_TP" || st === "HIT_SL" || st === "BEP" || st === "EXPIRED" || st === "CLOSED_MANUAL_TP" || st === "CLOSED_MANUAL_CL")) {
    tags.push(`<span class="badge badge-manual" title="Setup ini sempat ditandai Taken manual">TAKEN</span>`);
  }
  if (s.sl_bep_price && st !== "BEP") {
    const bepAtStr = s.sl_bep_at ? formatJakartaDateTime(s.sl_bep_at) : "-";
    tags.push(`<span class="badge badge-bep" title="SL dipindah ke BEP (${fmtPrice(s.sl_bep_price)}) pada ${escapeHtml(bepAtStr)}">SL-BEP</span>`);
  }
  return `<div style="display:flex; flex-wrap:wrap; gap:4px;">${tags.join("")}</div>`;
}

function syncScanButtonsState(isRunning) {
  const running = Boolean(isRunning);
  const scanBtn = document.getElementById("btn-run-scan");
  if (scanBtn) {
    scanBtn.disabled = running;
    scanBtn.textContent = running ? "Scanning..." : "Run Scan Now";
    scanBtn.title = running
      ? "Scan sedang berjalan (hanya 1 proses scan aktif dalam satu waktu)"
      : "";
  }
  const modalInfo = document.getElementById("modal-scan-running-info");
  if (modalInfo) {
    modalInfo.classList.toggle("hidden", !running);
  }
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
  pill.title = `Provider & Model Aktif: ${label.textContent}`;
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
  updateTopbarOverflow();
  syncScanButtonsState(scannerStatus.is_running);
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
  const params = new URLSearchParams();
  const { startDate, endDate } = runsRangePicker.getRange();
  if (startDate) params.set("start_date", startDate);
  if (endDate) params.set("end_date", endDate);
  if (startDate || endDate) params.set("tz_offset", "-420");

  const runIdVal = document.getElementById("filter-run-id")?.value.trim();
  if (runIdVal) params.set("run_id", runIdVal);
  const runStVal = document.getElementById("filter-run-status")?.value;
  if (runStVal && runStVal !== "ALL") params.set("status", runStVal);

  params.set("limit", String(state.runsPageSize));
  params.set("offset", String((state.runsPage - 1) * state.runsPageSize));

  let data = await apiRequest(`/api/scanner/runs?${params.toString()}`);
  state.runsTotal = data.total || 0;
  const maxPage = Math.max(1, Math.ceil(state.runsTotal / state.runsPageSize));
  if (state.runsPage > maxPage) {
    state.runsPage = maxPage;
    params.set("offset", String((state.runsPage - 1) * state.runsPageSize));
    data = await apiRequest(`/api/scanner/runs?${params.toString()}`);
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
      const btcSnap = cfg && cfg.btc_market_mover ? cfg.btc_market_mover : null;
      const btcLine = btcSnap
        ? `<div class="subtitle-sm">BTC Mover: <b>${escapeHtml(btcSnap.overall_regime || "-")}</b> (${escapeHtml(btcSnap.overall_bias || "-")}) &bull; Saran: <code>${escapeHtml((btcSnap.suggested_strategies || []).join(", ") || "-")}</code></div>`
        : "";
      return `
        <div class="scan-run-chip ${cls}">
          <div class="run-top">
            <strong><button type="button" class="run-id-chip" data-eval-run="${r.id}" title="Lihat detail &amp; settingan Scan Run #${r.id}">#${r.id}</button> &bull; ${timeStr}</strong>
            <span class="badge ${stBadge}">${r.status}</span>
          </div>
          <div class="subtitle-sm">Pair: ${r.top_pairs_count} | Pre: ${r.prefiltered_count} | AI: ${r.ai_analyzed_count} | Setup: <b>${r.setups_created_count}</b></div>
          ${cfgLine}
          ${btcLine}
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
  const btcSnap = cfg.btc_market_mover || null;
  const btcHtml = btcSnap
    ? `<div><strong>BTC_USDT Market Mover:</strong> Regime <b>${escapeHtml(btcSnap.overall_regime || "-")}</b> (${escapeHtml(btcSnap.overall_bias || "-")}) &bull; Alignment: <b>${escapeHtml(btcSnap.alignment || "-")}</b> &bull; Saran Strategi: <code>${escapeHtml((btcSnap.suggested_strategies || []).join(", ") || "-")}</code> (${escapeHtml(btcSnap.suggested_risk_profile || "-")})</div>`
    : "";
  return `
    <div class="eval-settings-box">
      <div><strong>Settingan Scan Dipakai:</strong> Mode <b>${escapeHtml(cfg.scan_mode || "-")}</b> &bull; Top N: <b>${cfg.top_n_pairs ?? "-"}</b> &bull; Interval Scan: <b>${cfg.scan_interval_minutes ?? "-"}m</b> &bull; Tracker: <b>${cfg.tracker_interval_seconds ?? "-"}s</b> &bull; Strategi: <code>${escapeHtml(stratLabel)}</code></div>
      <div><strong>Profil Per-Strategi:</strong> <code>${escapeHtml(formatStrategyProfilesSummary(cfg, fallbackStrategy))}</code></div>
      <div><strong>Filter &amp; Risk:</strong> Profil <b>${escapeHtml(cfg.risk_profile || "CONSERVATIVE")}</b> &bull; Vol 24h: <b>$${Number(cfg.min_24h_quote_volume || 0).toLocaleString("en-US")}</b> – <b>${maxVolStr}</b> &bull; ATR: <b>${cfg.min_atr_pct ?? "-"}%–${cfg.max_atr_pct ?? "-"}%</b> &bull; Min Conf: <b>${cfg.min_confidence ?? "-"}%</b> &bull; MEXC: <code>${escapeHtml(cfg.mexc_base_url || "-")}</code> &bull; LLM: Timeout ${cfg.llm_timeout_seconds ?? "-"}s / Concurrency ${cfg.llm_max_concurrency ?? "-"} / MaxTok ${cfg.llm_max_tokens ?? "-"}</div>
      ${btcHtml}
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

function getTodayJakartaYmd() {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: JAKARTA_TZ,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

function shiftYmd(ymd, deltaDays) {
  const [y, m, d] = ymd.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d + deltaDays));
  return dt.toISOString().slice(0, 10);
}

function formatYmdDisplay(ymd) {
  if (!ymd) return "-";
  const [y, m, d] = ymd.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  return dt.toLocaleDateString("en-US", { timeZone: "UTC", month: "short", day: "numeric", year: "numeric" });
}

function computeRangePreset(preset) {
  const today = getTodayJakartaYmd();
  const [y, m] = today.split("-").map(Number);
  if (preset === "today") {
    return { startDate: today, endDate: today };
  }
  if (preset === "last_7d") {
    return { startDate: shiftYmd(today, -6), endDate: today };
  }
  if (preset === "this_month") {
    return { startDate: `${y}-${String(m).padStart(2, "0")}-01`, endDate: today };
  }
  if (preset === "last_month") {
    const prevLast = new Date(Date.UTC(y, m - 1, 0));
    const py = prevLast.getUTCFullYear();
    const pm = prevLast.getUTCMonth() + 1;
    const pd = prevLast.getUTCDate();
    return {
      startDate: `${py}-${String(pm).padStart(2, "0")}-01`,
      endDate: `${py}-${String(pm).padStart(2, "0")}-${String(pd).padStart(2, "0")}`,
    };
  }
  if (preset === "last_3m") {
    const startDt = new Date(Date.UTC(y, m - 3, 1));
    return {
      startDate: startDt.toISOString().slice(0, 10),
      endDate: today,
    };
  }
  return { startDate: null, endDate: null };
}

function createDateRangePicker(cfg) {
  const rs = {
    preset: cfg.defaultPreset || "this_month",
    startDate: null,
    endDate: null,
    leftMonth: null,
    pendingStart: null,
    hoverDate: null,
  };

  const syncLeftMonth = () => {
    const ref = rs.endDate || rs.startDate || getTodayJakartaYmd();
    const [y, m] = ref.split("-").map(Number);
    const leftDt = new Date(Date.UTC(y, m - 2, 1));
    rs.leftMonth = { year: leftDt.getUTCFullYear(), month: leftDt.getUTCMonth() };
  };

  const renderUI = () => {
    const labelEl = document.getElementById(cfg.labelId);
    const popTextEl = document.getElementById(cfg.popTextId);
    const hintEl = document.getElementById(cfg.hintId);
    let txt = "Semua Waktu";
    if (rs.pendingStart) {
      txt = `${formatYmdDisplay(rs.pendingStart)}  \u2192  Pilih tgl akhir...`;
    } else if (rs.startDate && rs.endDate) {
      txt = `${formatYmdDisplay(rs.startDate)}  \u2192  ${formatYmdDisplay(rs.endDate)}`;
    }
    if (labelEl && !rs.pendingStart) labelEl.textContent = txt;
    if (popTextEl) popTextEl.textContent = txt;
    if (hintEl) {
      hintEl.textContent = rs.pendingStart
        ? "Klik tanggal kedua untuk menerapkan rentang."
        : "Klik tanggal mulai lalu klik tanggal akhir.";
    }
    document.querySelectorAll(`[${cfg.presetAttr}]`).forEach((btn) => {
      btn.classList.toggle("active", btn.getAttribute(cfg.presetAttr) === rs.preset);
    });
  };

  const closePopover = () => {
    const pop = document.getElementById(cfg.popoverId);
    const trigger = document.getElementById(cfg.triggerId);
    rs.pendingStart = null;
    rs.hoverDate = null;
    if (pop) pop.classList.add("hidden");
    if (trigger) trigger.setAttribute("aria-expanded", "false");
    renderUI();
  };

  const renderCalendars = () => {
    const grid = document.getElementById(cfg.gridId);
    if (!grid) return;
    if (!rs.leftMonth) syncLeftMonth();

    const today = getTodayJakartaYmd();
    const effStart = rs.pendingStart || rs.startDate;
    const effEnd = rs.pendingStart ? rs.hoverDate || rs.pendingStart : rs.endDate;
    const rangeMin = effStart && effEnd ? (effStart <= effEnd ? effStart : effEnd) : null;
    const rangeMax = effStart && effEnd ? (effStart <= effEnd ? effEnd : effStart) : null;

    const renderMonth = (year, monthIdx, navKind) => {
      const monthTitle = new Date(Date.UTC(year, monthIdx, 1)).toLocaleDateString("en-US", {
        timeZone: "UTC",
        month: "short",
        year: "numeric",
      });
      const firstDow = new Date(Date.UTC(year, monthIdx, 1)).getUTCDay();
      const cells = [];
      for (let i = 0; i < 42; i++) {
        const dt = new Date(Date.UTC(year, monthIdx, 1 - firstDow + i));
        const ymd = dt.toISOString().slice(0, 10);
        const isOutside = dt.getUTCMonth() !== monthIdx;
        const isStart = rangeMin && ymd === rangeMin;
        const isEnd = rangeMax && ymd === rangeMax;
        const inRange = rangeMin && rangeMax && ymd > rangeMin && ymd < rangeMax;
        const isToday = ymd === today;
        const cls = [
          "cal-day",
          isOutside ? "is-outside" : "",
          inRange ? "in-range" : "",
          isStart ? "is-start" : "",
          isEnd ? "is-end" : "",
          isToday ? "is-today" : "",
        ]
          .filter(Boolean)
          .join(" ");
        cells.push(`<button type="button" class="${cls}" data-cal-ymd="${ymd}">${dt.getUTCDate()}</button>`);
      }

      const leftBtn =
        navKind === "prev"
          ? `<button type="button" class="cal-nav-btn" data-cal-nav="prev" title="Bulan sebelumnya">&lsaquo;</button>`
          : `<span></span>`;
      const rightBtn =
        navKind === "next"
          ? `<button type="button" class="cal-nav-btn" data-cal-nav="next" title="Bulan berikutnya">&rsaquo;</button>`
          : `<span></span>`;

      return `
        <div class="cal-month">
          <div class="cal-month-head">
            ${leftBtn}
            <span>${monthTitle}</span>
            ${rightBtn}
          </div>
          <div class="cal-weekdays">
            <span>Su</span><span>Mo</span><span>Tu</span><span>We</span><span>Th</span><span>Fr</span><span>Sa</span>
          </div>
          <div class="cal-days">${cells.join("")}</div>
        </div>`;
    };

    const ly = rs.leftMonth.year;
    const lm = rs.leftMonth.month;
    const rightDt = new Date(Date.UTC(ly, lm + 1, 1));
    grid.innerHTML =
      renderMonth(ly, lm, "prev") +
      renderMonth(rightDt.getUTCFullYear(), rightDt.getUTCMonth(), "next");

    grid.querySelector('[data-cal-nav="prev"]')?.addEventListener("click", (e) => {
      e.stopPropagation();
      const d = new Date(Date.UTC(ly, lm - 1, 1));
      rs.leftMonth = { year: d.getUTCFullYear(), month: d.getUTCMonth() };
      renderCalendars();
    });
    grid.querySelector('[data-cal-nav="next"]')?.addEventListener("click", (e) => {
      e.stopPropagation();
      const d = new Date(Date.UTC(ly, lm + 1, 1));
      rs.leftMonth = { year: d.getUTCFullYear(), month: d.getUTCMonth() };
      renderCalendars();
    });

    grid.querySelectorAll("button[data-cal-ymd]").forEach((btn) => {
      btn.addEventListener("mouseenter", () => {
        if (rs.pendingStart) {
          rs.hoverDate = btn.dataset.calYmd;
          grid.querySelectorAll("button[data-cal-ymd]").forEach((dBtn) => {
            const ymd = dBtn.dataset.calYmd;
            const lo = rs.pendingStart <= rs.hoverDate ? rs.pendingStart : rs.hoverDate;
            const hi = rs.pendingStart <= rs.hoverDate ? rs.hoverDate : rs.pendingStart;
            dBtn.classList.toggle("is-start", ymd === lo);
            dBtn.classList.toggle("is-end", ymd === hi);
            dBtn.classList.toggle("in-range", ymd > lo && ymd < hi);
          });
        }
      });
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const clicked = btn.dataset.calYmd;
        if (!rs.pendingStart) {
          rs.pendingStart = clicked;
          rs.hoverDate = clicked;
          renderUI();
          renderCalendars();
        } else {
          const s = rs.pendingStart <= clicked ? rs.pendingStart : clicked;
          const en = rs.pendingStart <= clicked ? clicked : rs.pendingStart;
          rs.pendingStart = null;
          rs.hoverDate = null;
          rs.preset = "custom";
          rs.startDate = s;
          rs.endDate = en;
          renderUI();
          renderCalendars();
          closePopover();
          if (cfg.onChange) cfg.onChange();
        }
      });
    });
  };

  const applyPreset = (preset, shouldFetch = true) => {
    const { startDate, endDate } = computeRangePreset(preset);
    rs.preset = preset;
    rs.startDate = startDate;
    rs.endDate = endDate;
    rs.pendingStart = null;
    rs.hoverDate = null;
    syncLeftMonth();
    renderUI();
    renderCalendars();
    if (shouldFetch && cfg.onChange) cfg.onChange();
  };

  const wire = () => {
    const wrap = document.getElementById(cfg.wrapId);
    const trigger = document.getElementById(cfg.triggerId);
    const pop = document.getElementById(cfg.popoverId);
    if (!wrap || !trigger || !pop) return;

    trigger.addEventListener("click", (e) => {
      e.stopPropagation();
      const willOpen = pop.classList.contains("hidden");
      if (willOpen) {
        syncLeftMonth();
        renderUI();
        renderCalendars();
        pop.classList.remove("hidden");
        trigger.setAttribute("aria-expanded", "true");
      } else {
        closePopover();
      }
    });

    document.getElementById(cfg.closeBtnId)?.addEventListener("click", (e) => {
      e.stopPropagation();
      closePopover();
    });

    document.getElementById(cfg.clearBtnId)?.addEventListener("click", (e) => {
      e.stopPropagation();
      applyPreset("all", true);
      closePopover();
    });

    document.querySelectorAll(`[${cfg.presetAttr}]`).forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        applyPreset(btn.getAttribute(cfg.presetAttr) || cfg.defaultPreset, true);
        closePopover();
      });
    });

    document.addEventListener("click", (e) => {
      if (!wrap.contains(e.target) && !pop.classList.contains("hidden")) {
        closePopover();
      }
    });
  };

  return {
    getRange: () => ({ startDate: rs.startDate, endDate: rs.endDate, preset: rs.preset }),
    applyPreset,
    wire,
  };
}

const dashRangePicker = createDateRangePicker({
  defaultPreset: "this_month",
  wrapId: "dash-range-wrap",
  triggerId: "btn-dash-range",
  popoverId: "dash-range-popover",
  labelId: "dash-range-label",
  popTextId: "dash-popover-selected-text",
  hintId: "dash-cal-hint",
  gridId: "dash-cal-grid",
  closeBtnId: "btn-cal-close",
  clearBtnId: "btn-cal-clear",
  presetAttr: "data-range-preset",
  onChange: () => loadAnalytics(),
});

const setupsRangePicker = createDateRangePicker({
  defaultPreset: "last_7d",
  wrapId: "setups-range-wrap",
  triggerId: "btn-setups-range",
  popoverId: "setups-range-popover",
  labelId: "setups-range-label",
  popTextId: "setups-popover-selected-text",
  hintId: "setups-cal-hint",
  gridId: "setups-cal-grid",
  closeBtnId: "btn-setups-cal-close",
  clearBtnId: "btn-setups-cal-clear",
  presetAttr: "data-setups-preset",
  onChange: () => {
    state.setupsPage = 1;
    loadSetups();
  },
});

const runsRangePicker = createDateRangePicker({
  defaultPreset: "this_month",
  wrapId: "runs-range-wrap",
  triggerId: "btn-runs-range",
  popoverId: "runs-range-popover",
  labelId: "runs-range-label",
  popTextId: "runs-popover-selected-text",
  hintId: "runs-cal-hint",
  gridId: "runs-cal-grid",
  closeBtnId: "btn-runs-cal-close",
  clearBtnId: "btn-runs-cal-clear",
  presetAttr: "data-runs-preset",
  onChange: () => {
    state.runsPage = 1;
    loadScanRuns();
  },
});

async function loadAnalytics() {
  const { startDate, endDate } = dashRangePicker.getRange();
  const params = new URLSearchParams();
  if (startDate) params.set("start_date", startDate);
  if (endDate) params.set("end_date", endDate);
  if (startDate || endDate) params.set("tz_offset", "-420");
  const qs = params.toString();
  const data = await apiRequest(`/api/analytics/strategies${qs ? `?${qs}` : ""}`);
  const openWait = data.total_open_waiting_count ?? 0;
  const entryHit = data.total_entry_hit_active_count ?? 0;
  const extendedAct = data.total_extended_active_count ?? 0;
  const manualTaken = data.total_manual_taken_count ?? 0;

  document.getElementById("kpi-total").textContent = data.total_setups;
  const totalSub = document.getElementById("kpi-total-sub");
  if (totalSub) {
    totalSub.innerHTML = `Avg R:R: <b>${data.overall_avg_rr.toFixed(2)}x</b> &bull; BEP: <b>${data.total_bep_count ?? 0}</b> &bull; Expired: <b>${data.total_expired_count ?? 0}</b> &bull; Skip: <b>${data.total_skipped_count ?? 0}</b>`;
  }

  document.getElementById("kpi-open").textContent = data.open_count;
  const openSub = document.getElementById("kpi-open-sub");
  if (openSub) {
    openSub.innerHTML = `Menunggu: <b>${openWait}</b> &bull; Entry Hit: <b>${entryHit}</b> &bull; Extended: <b>${extendedAct}</b> &bull; Taken: <b>${manualTaken}</b>`;
  }

  document.getElementById("kpi-winrate").textContent = `${data.overall_win_rate_pct}%`;
  const wrSub = document.getElementById("kpi-winrate-sub");
  if (wrSub) {
    const tpAuto = data.total_hit_tp_auto_count ?? 0;
    const tpClosed = data.total_closed_manual_tp_count ?? 0;
    const slAuto = data.total_hit_sl_auto_count ?? 0;
    const slClosed = data.total_closed_manual_cl_count ?? 0;
    wrSub.innerHTML =
      `Win: <b>${data.total_tp_count ?? 0}</b> <span class="subtitle-sm">(TP:${tpAuto} / ClTP:${tpClosed})</span> &bull; ` +
      `Loss: <b>${data.total_sl_count ?? 0}</b> <span class="subtitle-sm">(SL:${slAuto} / ClCL:${slClosed})</span>`;
  }

  const noEntryEl = document.getElementById("kpi-no-entry");
  if (noEntryEl) {
    noEntryEl.textContent = `${data.total_sl_no_entry_count ?? 0} / ${data.total_tp_no_entry_count ?? 0}`;
  }
  const noEntrySub = document.getElementById("kpi-no-entry-sub");
  if (noEntrySub) {
    noEntrySub.innerHTML = `<span class="text-red">SL No Entry: <b>${data.total_sl_no_entry_count ?? 0}</b></span> &bull; <span class="text-green">TP No Entry: <b>${data.total_tp_no_entry_count ?? 0}</b></span>`;
  }

  const breakdownEl = document.getElementById("dash-active-breakdown");
  if (breakdownEl) {
    const activeTotal = Math.max(1, data.open_count || 0);
    const items = [
      {
        badgeCls: "badge-open",
        code: "OPEN",
        label: "Menunggu Entry",
        desc: "Harga belum menyentuh Entry",
        count: openWait,
        color: "#1877f2",
      },
      {
        badgeCls: "badge-entry-hit",
        code: "ENTRY_HIT",
        label: "Sudah Entry (Sistem)",
        desc: "Berjalan menuju TP atau SL",
        count: entryHit,
        color: "#0284c7",
      },
      {
        badgeCls: "badge-extended",
        code: "EXTENDED",
        label: "Expiry Diperpanjang",
        desc: "Tambahan waktu pantau strategi",
        count: extendedAct,
        color: "#0f766e",
      },
      {
        badgeCls: "badge-manual",
        code: "TAKEN",
        label: "Diambil Manual",
        desc: "Dieksekusi manual & dipantau Tracker",
        count: manualTaken,
        color: "#7c3aed",
      },
    ];
    breakdownEl.innerHTML = items
      .map((it) => {
        const pct = data.open_count > 0 ? Math.round((it.count / activeTotal) * 100) : 0;
        return `
          <div class="active-breakdown-row">
            <div class="active-breakdown-head">
              <div><span class="badge ${it.badgeCls}">${it.code}</span> <strong>${it.label}</strong></div>
              <strong>${it.count}</strong>
            </div>
            <div class="active-breakdown-track">
              <div class="active-breakdown-fill" style="width:${pct}%; background:${it.color};"></div>
            </div>
            <div class="active-breakdown-meta">${it.desc}</div>
          </div>`;
      })
      .join("");
  }

  const detailTbody = document.getElementById("dashboard-strategy-tbody");
  if (detailTbody) {
    detailTbody.innerHTML = data.strategies
      .map(
        (s) => `
        <tr>
          <td>
            <strong>${escapeHtml(s.strategy_used)}</strong>
            <div class="subtitle-sm">Total: <b>${s.total_setups}</b> setup</div>
          </td>
          <td>
            <b>${s.open_count}</b>
            <div class="subtitle-sm">
              <span title="O = OPEN (Menunggu harga menyentuh Entry)" style="cursor:help;">O:${s.open_waiting_count ?? 0}</span>
              <span title="H = ENTRY_HIT (Sudah menyentuh Entry otomatis, sedang menuju TP/SL)" style="cursor:help;">H:${s.entry_hit_active_count ?? 0}</span>
              <span title="E = EXTENDED (Batas expiry diperpanjang sesuai strategi)" style="cursor:help;">E:${s.extended_active_count ?? 0}</span>
              <span title="T = MANUAL_TAKEN (Diambil manual &amp; tetap dipantau Tracker)" style="cursor:help;">T:${s.manual_taken_count ?? 0}</span>
            </div>
          </td>
          <td class="text-green">
            <b>${s.hit_tp_count}</b>
            <div class="subtitle-sm">
              <span title="HIT = HIT_TP (Kena Take Profit otomatis oleh Tracker)" style="cursor:help;">HIT:${s.hit_tp_auto_count ?? 0}</span>
              <span title="Cl = CLOSED_MANUAL_TP (Ditutup manual dengan Take Profit)" style="cursor:help;">Cl:${s.closed_manual_tp_count ?? 0}</span>
            </div>
          </td>
          <td class="text-red">
            <b>${s.hit_sl_count}</b>
            <div class="subtitle-sm">
              <span title="HIT = HIT_SL (Kena Stop Loss otomatis oleh Tracker)" style="cursor:help;">HIT:${s.hit_sl_auto_count ?? 0}</span>
              <span title="Cl = CLOSED_MANUAL_CL (Ditutup manual dengan Cut Loss)" style="cursor:help;">Cl:${s.closed_manual_cl_count ?? 0}</span>
            </div>
          </td>
          <td>
            <span class="badge badge-expired" title="SL No Entry = Harga langsung jebol Stop Loss sebelum menyentuh Limit Entry">SL: ${s.sl_no_entry_count ?? 0}</span>
            <span class="badge badge-missed-tp" title="TP No Entry = Harga sudah tembus Take Profit duluan tanpa menyentuh Limit Entry">TP: ${s.tp_no_entry_count ?? 0}</span>
          </td>
          <td>
            <span class="badge badge-bep" title="BEP = Break-Even Point (Kena SL-BEP, 0 Loss, tidak masuk hitungan Win Rate)" style="cursor:help;">BEP: ${s.bep_count ?? 0}</span>
            <div class="subtitle-sm">
              <span title="Exp = EXPIRED (Melewati batas waktu Expiry tanpa menyentuh TP/SL)" style="cursor:help;">Exp: ${s.expired_count}</span> &bull;
              <span title="Skip = MANUAL_SKIPPED (Ditandai manual untuk dilewati)" style="cursor:help;">Skip: ${s.manual_skipped_count}</span>
            </div>
          </td>
          <td>
            <b>${s.win_rate_pct}%</b> <small class="subtitle-sm" title="Jumlah Win (${s.hit_tp_count}) dari total trade selesai yang Sudah Entry (${s.decided_count} = Win + Loss)" style="cursor:help;">(${s.hit_tp_count}/${s.decided_count})</small>
            <div class="subtitle-sm" title="Rata-rata Risk-to-Reward Ratio dari seluruh setup strategi ini" style="cursor:help;">R:R <b>${Number(s.avg_rr).toFixed(2)}x</b></div>
          </td>
        </tr>`
      )
      .join("");
  }

  const ctx = document.getElementById("strategyChart").getContext("2d");
  if (state.strategyChart) state.strategyChart.destroy();
  state.strategyChart = new Chart(ctx, {
    type: "bar",
    data: {
      labels: data.strategies.map((s) => s.strategy_used),
      datasets: [
        { label: "Win (TP + Closed TP)", data: data.strategies.map((s) => s.hit_tp_count), backgroundColor: "#16a34a" },
        { label: "Loss (SL + Closed CL)", data: data.strategies.map((s) => s.hit_sl_count), backgroundColor: "#e41e3f" },
        { label: "BEP (Break-Even)", data: data.strategies.map((s) => s.bep_count ?? 0), backgroundColor: "#0ea5e9" },
        { label: "Aktif", data: data.strategies.map((s) => s.open_count), backgroundColor: "#1877f2" },
        { label: "No Entry (SL/TP)", data: data.strategies.map((s) => (s.sl_no_entry_count ?? 0) + (s.tp_no_entry_count ?? 0)), backgroundColor: "#f97316" },
        { label: "Expired", data: data.strategies.map((s) => s.expired_count), backgroundColor: "#eab308" },
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

const ACTIVE_STATUS_SET = new Set(["OPEN", "ENTRY_HIT", "EXTENDED", "MANUAL_TAKEN"]);

function switchStatusTab(targetStatus) {
  const clean = targetStatus || "ALL";
  state.statusFilter = clean;
  document.querySelectorAll("#status-tabs .tab").forEach((b) => {
    b.classList.toggle("active", b.dataset.status === clean);
  });
}

function updateStatusTabCounts(counts = {}) {
  document.querySelectorAll("#status-tabs .tab-count[data-count-for]").forEach((badgeEl) => {
    const key = badgeEl.dataset.countFor;
    const val = Object.prototype.hasOwnProperty.call(counts, key) ? counts[key] : 0;
    badgeEl.textContent = String(val ?? 0);
  });
}

function getLatestTransition(setup) {
  const hist = Array.isArray(setup.status_history) ? setup.status_history : [];
  let lastIdx = -1;
  for (let i = 0; i < hist.length; i++) {
    if (hist[i] && hist[i].event && hist[i].event !== "CREATED") {
      lastIdx = i;
    }
  }
  if (lastIdx >= 0) {
    const ev = hist[lastIdx];
    const prev = lastIdx > 0 && hist[lastIdx - 1] ? hist[lastIdx - 1] : null;
    return {
      fromStatus: (prev && prev.status) || "OPEN",
      toStatus: ev.status || setup.status,
      event: ev.event,
      note: ev.note || "",
      price: ev.price ?? null,
      at: ev.at || setup.updated_at,
    };
  }
  if (setup.status !== "OPEN" || setup.entry_hit_at || setup.missed_tp_at) {
    return {
      fromStatus: setup.entry_hit_at && ["HIT_TP", "HIT_SL", "BEP", "EXPIRED"].includes(setup.status) ? "ENTRY_HIT" : "OPEN",
      toStatus: setup.status,
      event: setup.missed_tp_at && setup.status === "OPEN" ? "TP_BEFORE_ENTRY" : setup.status,
      note: "",
      price: setup.resolved_price ?? setup.missed_tp_price ?? null,
      at: setup.resolved_at || setup.manual_action_at || setup.entry_hit_at || setup.missed_tp_at || setup.updated_at,
    };
  }
  return null;
}

function isRecentlyChangedSetup(setup) {
  const nowMs = Date.now();
  const live = state.justChangedSetups[setup.id];
  if (live && nowMs - live.atMs < 180000) return true;
  const tr = getLatestTransition(setup);
  if (!tr || !tr.at) return false;
  const evDate = parseBackendUtcDate(tr.at);
  return evDate ? nowMs - evDate.getTime() < 120000 : false;
}

async function focusSetupFromTransition(changeItem) {
  if (!changeItem || !changeItem.setup_id) return;
  const newStatus = changeItem.to_status || "ALL";
  const hiddenByTab =
    state.statusFilter !== "ALL" &&
    state.statusFilter !== newStatus &&
    !(state.statusFilter === "ACTIVE" && ACTIVE_STATUS_SET.has(newStatus));
  if (hiddenByTab) {
    switchStatusTab(ACTIVE_STATUS_SET.has(newStatus) ? "ACTIVE" : "ALL");
    state.setupsPage = 1;
  }
  await loadSetups();
  let target = state.setups.find((x) => x.id === changeItem.setup_id);
  if (!target) {
    try {
      target = await apiRequest(`/api/setups/${changeItem.setup_id}`);
    } catch (_err) {
      return;
    }
  }
  if (target) {
    await selectSetup(target);
    const rowEl = document.querySelector(`#setups-tbody tr[data-id="${target.id}"]`);
    if (rowEl) {
      rowEl.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }
}

function renderRecentChangesStrip(changes = []) {
  const bar = document.getElementById("recent-changes-strip");
  const wrap = document.getElementById("recent-changes-chips");
  if (!bar || !wrap) return;
  if (!changes.length) {
    bar.classList.add("hidden");
    wrap.innerHTML = "";
    return;
  }

  const nowMs = Date.now();
  wrap.innerHTML = changes
    .slice(0, 6)
    .map((c, idx) => {
      const evDt = parseBackendUtcDate(c.at);
      const isLive = Boolean(state.justChangedSetups[c.setup_id] && nowMs - state.justChangedSetups[c.setup_id].atMs < 180000);
      const isVeryRecent = isLive || (evDt ? nowMs - evDt.getTime() < 300000 : false);
      const fromTxt = c.from_status && c.from_status !== c.to_status ? `${escapeHtml(c.from_status)} ` : "";
      const arrowTxt = fromTxt ? `<span class="change-arrow">&rarr;</span> ` : "";
      const toLabel = c.event === "TP_BEFORE_ENTRY" && c.to_status === "OPEN" ? "TP NO ENTRY" : c.to_status;
      const rel = formatRelativeTimeId(c.at);
      return `
        <button type="button" class="change-chip ${isVeryRecent ? "is-fresh" : ""}" data-change-idx="${idx}" title="${escapeHtml(c.note || "Klik untuk fokus ke setup ini")}">
          ${isVeryRecent ? '<span class="badge badge-fresh">BARU</span>' : ""}
          <strong>${escapeHtml(c.symbol)}</strong>
          <span>${fromTxt}${arrowTxt}<b>${escapeHtml(toLabel)}</b></span>
          <span class="change-time">${escapeHtml(rel || formatJakartaShortTime(c.at))}</span>
        </button>`;
    })
    .join("");

  bar.classList.remove("hidden");
  wrap.querySelectorAll("button[data-change-idx]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const item = changes[Number(btn.dataset.changeIdx)];
      if (item) focusSetupFromTransition(item);
    });
  });
}

async function loadSetups() {
  const params = new URLSearchParams();
  if (state.statusFilter !== "ALL") params.set("status", state.statusFilter);
  const stratFilters = Array.isArray(state.setupStrategyFilter) ? state.setupStrategyFilter : [];
  if (stratFilters.length) params.set("strategy", stratFilters.join(","));
  const sym = document.getElementById("filter-symbol").value.trim();
  if (sym) params.set("symbol", sym);
  const { startDate: setupsStart, endDate: setupsEnd } = setupsRangePicker.getRange();
  if (setupsStart) params.set("start_date", setupsStart);
  if (setupsEnd) params.set("end_date", setupsEnd);
  if (setupsStart || setupsEnd) params.set("tz_offset", "-420");
  const sortEl = document.getElementById("sort-setups");
  state.setupsSort = sortEl ? sortEl.value || "updated" : state.setupsSort;
  params.set("sort", state.setupsSort);

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

  // Detect live status transitions across refreshes or manual tracker runs
  const liveTransitions = [];
  const nextKnown = { ...state.knownSetupStatuses };
  for (const s of data.items || []) {
    const prevSt = state.knownSetupStatuses[s.id];
    if (state.hasLoadedSetupsOnce && prevSt && prevSt !== s.status) {
      state.justChangedSetups[s.id] = { fromStatus: prevSt, toStatus: s.status, atMs: Date.now() };
      liveTransitions.push(`${s.symbol} (${prevSt} \u2192 ${s.status})`);
    }
    nextKnown[s.id] = s.status;
  }
  for (const ch of data.recent_changes || []) {
    const prevSt = state.knownSetupStatuses[ch.setup_id];
    if (state.hasLoadedSetupsOnce && prevSt && prevSt !== ch.to_status) {
      if (!state.justChangedSetups[ch.setup_id] || state.justChangedSetups[ch.setup_id].toStatus !== ch.to_status) {
        state.justChangedSetups[ch.setup_id] = { fromStatus: prevSt, toStatus: ch.to_status, atMs: Date.now() };
        const txt = `${ch.symbol} (${prevSt} \u2192 ${ch.to_status})`;
        if (!liveTransitions.includes(txt)) liveTransitions.push(txt);
      }
    }
    nextKnown[ch.setup_id] = ch.to_status;
  }
  state.knownSetupStatuses = nextKnown;
  state.hasLoadedSetupsOnce = true;

  if (liveTransitions.length) {
    const preview = liveTransitions.slice(0, 2).join(", ");
    const extra = liveTransitions.length > 2 ? ` (+${liveTransitions.length - 2} lagi)` : "";
    showToast(`Perubahan status: ${preview}${extra}`);
  }

  updateStatusTabCounts(data.status_counts || {});
  renderRecentChangesStrip(data.recent_changes || []);

  state.setups = data.items;
  updatePaginationUI("setups", state.setupsPage, state.setupsPageSize, state.setupsTotal);

  const tbody = document.getElementById("setups-tbody");
  if (!data.items.length) {
    tbody.innerHTML = `<tr><td colspan="6" class="empty-cell">Belum ada setup untuk filter ini.</td></tr>`;
    return;
  }

  tbody.innerHTML = data.items
    .map((s) => {
      const selectedCls = state.selectedSetup && state.selectedSetup.id === s.id ? "selected" : "";
      const fresh = isRecentlyChangedSetup(s);
      const changedCls = fresh ? "just-changed" : "";
      const dirBadge = s.decision === "LONG" ? "badge-long" : "badge-short";
      const meLine = s.manual_entry_price ? `<div class="text-accent">ME: ${fmtPrice(s.manual_entry_price)}</div>` : "";
      const bepLine = s.sl_bep_price ? `<div class="text-bep">SL-BEP: ${fmtPrice(s.sl_bep_price)}</div>` : "";
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

      const tr = getLatestTransition(s);
      const updatedRef = (tr && tr.at) || s.updated_at || s.created_at;
      const relUpdated = formatRelativeTimeId(updatedRef);
      const hasStatusChanged = Boolean(tr);
      const updatedTimeLine = hasStatusChanged
        ? `<span class="setup-time-updated">Update: ${escapeHtml(relUpdated)} (${escapeHtml(formatJakartaShortTime(updatedRef))})</span>`
        : `<span>Dibuat: ${escapeHtml(formatRelativeTimeId(s.created_at))} (${escapeHtml(formatJakartaShortTime(s.created_at))})</span>`;
      const scanTimeLine = hasStatusChanged
        ? `<span>Scan: ${escapeHtml(formatJakartaDateTime(s.created_at))}</span>`
        : `<span>Tgl: ${escapeHtml(formatJakartaDateTime(s.created_at))}</span>`;
      const expTimeLine =
        ACTIVE_STATUS_SET.has(s.status) && s.expires_at
          ? `<span>Exp: ${escapeHtml(formatJakartaDateTime(s.expires_at))}</span>`
          : "";

      let transitionHtml = `<div class="setup-last-transition setup-last-transition-sub">Menunggu sentuh Entry (${escapeHtml(s.entry_type || "LIMIT")})</div>`;
      if (tr) {
        const fromPart = tr.fromStatus && tr.fromStatus !== tr.toStatus ? `${escapeHtml(tr.fromStatus)} &rarr; ` : "";
        const toLabel = tr.event === "TP_BEFORE_ENTRY" && tr.toStatus === "OPEN" ? "TP NO ENTRY" : tr.toStatus;
        const noteShort = tr.note ? `<div class="setup-last-transition-sub">${escapeHtml(tr.note)}</div>` : "";
        transitionHtml = `
          <div class="setup-last-transition">
            <strong>${fromPart}${escapeHtml(toLabel)}</strong> &bull; <span class="setup-last-transition-sub">${escapeHtml(relUpdated)}</span>
            ${noteShort}
          </div>`;
      }

      const freshTag = fresh ? `<span class="badge badge-fresh">BARU</span>` : "";

      return `
        <tr class="${selectedCls} ${changedCls}" data-id="${s.id}">
          <td>
            <div class="setup-pair-head">
              <strong>${escapeHtml(s.symbol)}</strong>
              <span class="badge ${dirBadge}">${s.decision}</span>
              ${freshTag}
            </div>
            <div class="setup-time-stack">
              ${updatedTimeLine}
              ${scanTimeLine}
              ${expTimeLine}
            </div>
          </td>
          <td>
            <strong>${escapeHtml(s.strategy_used)}</strong>
            ${holdHtml}
            ${tfLine}
          </td>
          <td>
            <div>E: ${fmtPrice(s.entry_price)}</div>
            ${meLine}
            <div class="text-red">SL: ${fmtPrice(s.stop_loss)}</div>
            ${bepLine}
            <div class="text-green">TP: ${fmtPrice(s.take_profit)}</div>
            ${closeLine}
          </td>
          <td>
            <strong>${Number(s.risk_reward_ratio).toFixed(2)}x</strong>
            <div class="subtitle-sm">Conf: <b>${s.confidence}%</b></div>
          </td>
          <td>
            ${statusBadge(s)}
            ${transitionHtml}
          </td>
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
    rightPriceScale: { borderColor: "#dadde1", minimumWidth: 96, autoScale: true },
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
    rightPriceScale: { borderColor: "#dadde1", autoScale: true, minimumWidth: 96 },
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
  if (Math.abs(n) >= 1000) return n.toFixed(2);
  if (Math.abs(n) >= 1) return n.toFixed(4);
  const prec = inferDecimalPrecision(n);
  return n.toFixed(prec).replace(/(\.\d*?[1-9])0+$/, "$1").replace(/\.0+$/, "");
}

function roundPositionPrice(val) {
  const n = Number(val);
  if (!Number.isFinite(n)) return n;
  const prec = Math.abs(n) >= 1000 ? 2 : Math.abs(n) >= 1 ? 4 : Math.max(8, inferDecimalPrecision(n));
  return Number(n.toFixed(Math.min(10, prec)));
}

function computeChartPriceFormat(candles, setup) {
  const samples = [];
  if (setup) {
    [setup.entry_price, setup.manual_entry_price, setup.stop_loss, setup.sl_bep_price, setup.take_profit].forEach((v) => {
      if (Number.isFinite(Number(v)) && Number(v) > 0) samples.push(Number(v));
    });
  }
  const tail = Array.isArray(candles) ? candles.slice(-20) : [];
  for (const c of tail) {
    if (c && Number.isFinite(Number(c.close)) && Number(c.close) > 0) samples.push(Number(c.close));
    if (c && Number.isFinite(Number(c.low)) && Number(c.low) > 0) samples.push(Number(c.low));
  }
  const precision = samples.length
    ? Math.max(...samples.map((s) => inferDecimalPrecision(s)))
    : 4;
  const clamped = Math.min(10, Math.max(2, precision));
  const minMove = Number((10 ** -clamped).toFixed(clamped));
  return { type: "price", precision: clamped, minMove };
}

const SETUP_BOX_ID = 0;

function getAutoPositionSide() {
  if (state.selectedSetup && String(state.selectedSetup.decision).toUpperCase() === "SHORT") {
    return "SHORT";
  }
  return "LONG";
}

function parseUtcEpochSec(isoStr) {
  if (!isoStr) return NaN;
  const raw = String(isoStr).trim();
  const hasTz = /(?:Z|[+-]\d{2}:\d{2})$/i.test(raw);
  const ms = new Date(hasTz ? raw : `${raw}Z`).getTime();
  return Number.isFinite(ms) ? Math.floor(ms / 1000) : NaN;
}

function findCandleIdxAtOrBefore(candles, targetSec) {
  if (!candles || !candles.length || !Number.isFinite(targetSec)) return -1;
  if (Number(candles[0].time) > targetSec) return 0;
  let matchIdx = 0;
  for (let i = 0; i < candles.length; i += 1) {
    if (Number(candles[i].time) <= targetSec) {
      matchIdx = i;
    } else {
      break;
    }
  }
  return matchIdx;
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

  const activeStatuses = new Set(["OPEN", "ENTRY_HIT", "EXTENDED", "MANUAL_TAKEN"]);
  const isFinished = !activeStatuses.has(String(setup.status || "").toUpperCase());

  let startIdx = Math.max(0, state.chartBarsCount - 1);
  if (setup.created_at && state.chartCandles.length) {
    const createdSec = parseUtcEpochSec(setup.created_at);
    const idx = findCandleIdxAtOrBefore(state.chartCandles, createdSec);
    if (idx >= 0) {
      startIdx = idx;
    }
  }

  let endIdx = Math.max(startIdx + 12, state.chartBarsCount + 6);
  if (isFinished && state.chartCandles.length) {
    const hist = Array.isArray(setup.status_history) ? setup.status_history : [];
    const lastHistAt = hist.length ? hist[hist.length - 1]?.at : null;
    const finalIso = setup.resolved_at || lastHistAt || setup.manual_action_at || setup.updated_at || setup.expires_at;
    const endedSec = parseUtcEpochSec(finalIso);
    if (Number.isFinite(endedSec)) {
      const eIdx = findCandleIdxAtOrBefore(state.chartCandles, endedSec);
      const resolvedBarIdx = eIdx >= 0 ? eIdx : state.chartCandles.length - 1;
      endIdx = Math.max(startIdx + 1, resolvedBarIdx);
    }
  }
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
  const plotW = Math.max(0, (typeof ts.width === "function" ? ts.width() : 0) || ((chartEl ? chartEl.clientWidth : 800) - 96));
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
        price: Number(setup.entry_price),
        color: "#6b7280",
        lineWidth: 2,
        lineStyle: LightweightCharts.LineStyle.Dashed,
        axisLabelVisible: true,
        title: "AI ENTRY",
      }),
      state.candleSeries.createPriceLine({
        price: Number(setup.manual_entry_price),
        color: "#6b21a8",
        lineWidth: 2,
        lineStyle: LightweightCharts.LineStyle.Dashed,
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
  if (
    setup.sl_bep_price !== null &&
    setup.sl_bep_price !== undefined &&
    Number(setup.sl_bep_price) > 0
  ) {
    nextLines.push(
      state.candleSeries.createPriceLine({
        price: Number(setup.sl_bep_price),
        color: "#f59e0b",
        lineWidth: 2,
        lineStyle: LightweightCharts.LineStyle.LargeDashed,
        axisLabelVisible: true,
        title: "SL-BEP",
      })
    );
  }
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
  const dirCls = setup.decision === "LONG" ? "badge-long" : "badge-short";
  document.getElementById("chart-title").innerHTML =
    `${escapeHtml(setup.symbol)} <span class="badge ${dirCls}">${escapeHtml(setup.decision)}</span> &mdash; ${escapeHtml(setup.strategy_used)}`;

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
    if (isNewContext || !isLiveRefresh) {
      const priceFormat = computeChartPriceFormat(candles, setup);
      state.candleSeries.applyOptions({ priceFormat });
      state.ema21Series.applyOptions({ priceFormat });
      state.ema50Series.applyOptions({ priceFormat });
      state.ema200Series.applyOptions({ priceFormat });
      state.chart.applyOptions({
        localization: {
          locale: "id-ID",
          timeFormatter: formatChartJakartaTime,
          priceFormatter: (p) => (Number.isFinite(p) ? Number(p).toFixed(priceFormat.precision) : ""),
        },
      });
    }
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
  const pairMexc = String(setup.symbol || "").replace(/_/g, "");
  document.getElementById("setup-detail-body").classList.remove("hidden");
  const dPairMexc = document.getElementById("d-pair-mexc");
  if (dPairMexc) dPairMexc.textContent = pairMexc || "-";
  document.getElementById("d-entry-type").textContent = setup.manual_entry_price ? "MANUAL" : setup.entry_type;
  document.getElementById("d-entry").textContent = fmtPrice(effEntry);
  document.getElementById("d-sl").textContent = setup.sl_bep_price
    ? `${fmtPrice(setup.stop_loss)} (BEP: ${fmtPrice(setup.sl_bep_price)})`
    : fmtPrice(setup.stop_loss);
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

  const reasonBox = document.getElementById("d-ai-reasoning");
  if (reasonBox) {
    const aiPay = setup.ai_payload || {};
    const htfTxt = (aiPay.htf_analysis || "").trim();
    const ltfTxt = (aiPay.ltf_trigger_analysis || "").trim();
    const chk = aiPay.checklist && typeof aiPay.checklist === "object" ? aiPay.checklist : null;
    if (htfTxt || ltfTxt || chk) {
      const chkLabels = [
        ["htf_trend_ok", "HTF Trend"],
        ["pullback_or_level_ok", "Level/Pullback"],
        ["trigger_candle_ok", "Trigger Candle"],
        ["volume_ok", "Volume"],
        ["momentum_ok", "Momentum"],
        ["rr_ok", "R:R"],
      ];
      const chkHtml = chk
        ? `<div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:6px;">${chkLabels
            .map(([k, lbl]) => {
              const ok = Boolean(chk[k]);
              const cls = ok ? "badge-hit-tp" : "badge-hit-sl";
              return `<span class="badge ${cls}">${ok ? "✓" : "✗"} ${lbl}</span>`;
            })
            .join("")}</div>`
        : "";
      reasonBox.innerHTML = `${htfTxt ? `<h4>HTF Analysis</h4><p>${escapeHtml(htfTxt)}</p>` : ""}${
        ltfTxt ? `<h4>LTF Trigger Analysis</h4><p>${escapeHtml(ltfTxt)}</p>` : ""
      }${chkHtml ? `<h4>Checklist Konfluensi</h4>${chkHtml}` : ""}`;
      reasonBox.classList.remove("hidden");
    } else {
      reasonBox.innerHTML = "";
      reasonBox.classList.add("hidden");
    }
  }
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
        h.stop_loss != null && h.take_profit != null && (h.event === "MANUAL_TAKEN" || h.event === "RESET_OPEN" || h.event === "EXTENDED")
          ? ` (SL: ${fmtPrice(h.stop_loss)}, TP: ${fmtPrice(h.take_profit)})`
          : "";
      const expTxt = h.new_expires_at
        ? ` &bull; <span class="text-accent">Expiry baru: ${escapeHtml(formatJakartaDateTime(h.new_expires_at))}</span>`
        : "";
      rows.push(
        `<div class="history-item"><div><span class="badge badge-neutral">${escapeHtml(h.event || h.status)}</span> <strong>${escapeHtml(h.note || h.status || "")}</strong>${pxTxt}${slTpTxt}${expTxt}</div><span class="subtitle-sm">${escapeHtml(timeTxt)}</span></div>`
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
    if (overrides && overrides.sl_bep_price !== null && overrides.sl_bep_price !== undefined) {
      bodyObj.sl_bep_price = overrides.sl_bep_price;
    }
    if (overrides && overrides.live_price !== null && overrides.live_price !== undefined) {
      bodyObj.live_price = overrides.live_price;
    }
    if (overrides && overrides.extend_hours !== null && overrides.extend_hours !== undefined) {
      bodyObj.extend_hours = overrides.extend_hours;
    }

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
  const extendWrap = document.getElementById("edit-extend-hours-wrap");
  const bepWrap = document.getElementById("edit-sl-bep-wrap");
  const closeWrap = document.getElementById("edit-close-price-wrap");
  const closeLabel = document.getElementById("edit-close-price-label");
  const closeInput = document.getElementById("edit-close-price");

  const showEntry =
    statusVal === "MANUAL_TAKEN" ||
    statusVal === "ENTRY_HIT" ||
    statusVal === "CLOSED_MANUAL_TP" ||
    statusVal === "CLOSED_MANUAL_CL";
  const showRiskLevels =
    statusVal === "MANUAL_TAKEN" ||
    statusVal === "ENTRY_HIT" ||
    statusVal === "EXTENDED" ||
    statusVal === "OPEN";
  const showExtend = statusVal === "EXTENDED";
  const showBep = statusVal === "MOVE_SL_BEP";
  const showClose = statusVal === "CLOSED_MANUAL_TP" || statusVal === "CLOSED_MANUAL_CL";

  entryWrap.classList.toggle("hidden", !showEntry);
  if (riskWrap) riskWrap.classList.toggle("hidden", !showRiskLevels);
  if (extendWrap) extendWrap.classList.toggle("hidden", !showExtend);
  if (bepWrap) bepWrap.classList.toggle("hidden", !showBep);
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
  const allowed = new Set(["OPEN", "ENTRY_HIT", "EXTENDED", "MANUAL_TAKEN", "MANUAL_SKIPPED", "CLOSED_MANUAL_TP", "CLOSED_MANUAL_CL", "EXPIRED"]);
  sel.value = allowed.has(setup.status) ? setup.status : "MANUAL_TAKEN";

  const meta = resolveSetupStrategyMeta(setup);
  const extInput = document.getElementById("edit-extend-hours");
  if (extInput) extInput.value = meta.expiryHours || 12;

  document.getElementById("edit-manual-entry").value = setup.manual_entry_price ?? setup.entry_price ?? "";
  const bepInput = document.getElementById("edit-sl-bep-price");
  if (bepInput) bepInput.value = setup.sl_bep_price ?? setup.manual_entry_price ?? setup.entry_price ?? "";
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

function readSetupStrategyFilterFromDom() {
  const checked = Array.from(
    document.querySelectorAll('#filter-strategy-options input[name="setup_strategy_filter"]:checked')
  ).map((cb) => cb.value);
  state.setupStrategyFilter = checked;
  return checked;
}

function updateSetupStrategyFilterLabel() {
  const labelEl = document.getElementById("filter-strategy-label");
  if (!labelEl) return;
  const selected = Array.isArray(state.setupStrategyFilter) ? state.setupStrategyFilter : [];
  const total = state.strategies.length;
  if (!selected.length) {
    labelEl.textContent = "Semua Strategi";
    return;
  }
  if (total && selected.length >= total) {
    labelEl.textContent = `Semua Strategi (${selected.length})`;
    return;
  }
  if (selected.length === 1) {
    labelEl.textContent = selected[0];
    return;
  }
  const preview = selected.slice(0, 2).join(", ");
  labelEl.textContent = selected.length <= 2 ? preview : `${preview} +${selected.length - 2}`;
}

function closeStrategyFilterMenu() {
  const menu = document.getElementById("filter-strategy-menu");
  const btn = document.getElementById("btn-filter-strategy");
  if (menu) menu.classList.add("hidden");
  if (btn) btn.setAttribute("aria-expanded", "false");
}

function renderStrategyFilterDropdown() {
  const wrap = document.getElementById("filter-strategy-options");
  if (!wrap) return;
  const prevSelected = new Set(Array.isArray(state.setupStrategyFilter) ? state.setupStrategyFilter : []);
  const names = state.strategies.map((s) => s.name);
  // Keep selection only for strategies that still exist.
  state.setupStrategyFilter = names.filter((n) => prevSelected.has(n));

  if (!names.length) {
    wrap.innerHTML = `<div class="multi-select-empty subtitle-sm">Belum ada strategi.</div>`;
    updateSetupStrategyFilterLabel();
    return;
  }

  wrap.innerHTML = names
    .map(
      (n) => `
      <label class="multi-select-option" title="${escapeHtml(n)}">
        <input type="checkbox" name="setup_strategy_filter" value="${escapeHtml(n)}" ${state.setupStrategyFilter.includes(n) ? "checked" : ""} />
        <span>${escapeHtml(n)}</span>
      </label>`
    )
    .join("");

  wrap.querySelectorAll('input[name="setup_strategy_filter"]').forEach((cb) => {
    cb.addEventListener("change", () => {
      readSetupStrategyFilterFromDom();
      updateSetupStrategyFilterLabel();
      state.setupsPage = 1;
      loadSetups();
    });
  });

  updateSetupStrategyFilterLabel();
}

function setSetupStrategyFilterSelection(names, reload = true) {
  const valid = new Set(state.strategies.map((s) => s.name));
  state.setupStrategyFilter = (names || []).filter((n) => valid.has(n));
  const wrap = document.getElementById("filter-strategy-options");
  if (wrap) {
    wrap.querySelectorAll('input[name="setup_strategy_filter"]').forEach((cb) => {
      cb.checked = state.setupStrategyFilter.includes(cb.value);
    });
  }
  updateSetupStrategyFilterLabel();
  if (reload) {
    state.setupsPage = 1;
    loadSetups();
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
          openConfirmDeleteModal({
            title: "Hapus Strategi",
            message: `Yakin ingin menghapus strategi ${target.name}? Tindakan ini tidak dapat dibatalkan.`,
            detailHtml: `
              <div class="confirm-scan-row"><span class="subtitle-sm">Kode / Nama</span><strong>${escapeHtml(target.name)} &bull; ${escapeHtml(target.display_name || "-")}</strong></div>
              <div class="confirm-scan-row"><span class="subtitle-sm">Gaya / Timeframe</span><span>${escapeHtml(target.trade_style || "-")} (${escapeHtml(target.suggested_htf || "-")}/${escapeHtml(target.suggested_ltf || "-")})</span></div>
            `,
            onConfirm: async () => {
              await apiRequest(`/api/strategies/${id}`, { method: "DELETE" });
              showToast(`Strategi ${target.name} dihapus.`);
              await Promise.all([loadAIModalData(false), loadAnalytics()]);
            },
          });
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
  const riskSel = document.getElementById("cfg-risk-profile");
  if (riskSel) {
    riskSel.value = scannerCfg.risk_profile || "CONSERVATIVE";
    if (!riskSel.dataset.boundRiskSync) {
      riskSel.dataset.boundRiskSync = "1";
      riskSel.addEventListener("change", () => {
        const defaults = { CONSERVATIVE: 70, MODERATE: 60, AGGRESSIVE: 55 };
        const confInput = document.getElementById("cfg-min-confidence");
        if (confInput && defaults[riskSel.value] !== undefined) {
          confInput.value = defaults[riskSel.value];
        }
      });
    }
  }
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
      const modelObj = (state.aiModels || []).find((m) => m.id === id);
      try {
        if (act === "activate") {
          const res = await apiRequest(`/api/ai/models/${id}/activate`, { method: "POST" });
          showToast(res.message);
          await Promise.all([loadAIModalData(false), loadHealthAndStatus()]);
        } else if (act === "delete") {
          openConfirmDeleteModal({
            title: "Hapus Model AI",
            message: `Yakin ingin menghapus model AI ${modelObj ? modelObj.name : `#${id}`}?`,
            detailHtml: modelObj
              ? `
                <div class="confirm-scan-row"><span class="subtitle-sm">Nama Model</span><strong>${escapeHtml(modelObj.name)}</strong></div>
                <div class="confirm-scan-row"><span class="subtitle-sm">Provider / Model ID</span><code>${escapeHtml(modelObj.provider)} &bull; ${escapeHtml(modelObj.model_id)}</code></div>
              `
              : "",
            onConfirm: async () => {
              await apiRequest(`/api/ai/models/${id}`, { method: "DELETE" });
              showToast("Model AI dihapus.");
              await Promise.all([loadAIModalData(false), loadHealthAndStatus()]);
            },
          });
        }
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
    risk_profile: document.getElementById("cfg-risk-profile")?.value || "CONSERVATIVE",
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
    showToast("Pengaturan provider AI berhasil disimpan.");
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
  document.querySelectorAll("button[data-view-tab]").forEach((btn) => {
    btn.addEventListener("click", () => {
      switchMainView(btn.dataset.viewTab || "scanner");
    });
  });

  const dashActiveBtn = document.getElementById("btn-dash-view-active");
  if (dashActiveBtn) {
    dashActiveBtn.addEventListener("click", () => {
      switchStatusTab("ACTIVE");
      state.setupsPage = 1;
      switchMainView("scanner");
      loadSetups();
    });
  }

  document.querySelectorAll("#status-tabs .tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      switchStatusTab(btn.dataset.status);
      state.setupsPage = 1;
      loadSetups();
    });
  });

  const sortSel = document.getElementById("sort-setups");
  if (sortSel) {
    sortSel.addEventListener("change", () => {
      state.setupsSort = sortSel.value || "updated";
      state.setupsPage = 1;
      loadSetups();
    });
  }

  document.getElementById("btn-toggle-status-legend").addEventListener("click", () => {
    document.getElementById("status-legend-box").classList.toggle("hidden");
  });
  document.getElementById("btn-close-status-legend").addEventListener("click", () => {
    document.getElementById("status-legend-box").classList.add("hidden");
  });

  const strategyFilterWrap = document.getElementById("filter-strategy-wrap");
  const strategyFilterBtn = document.getElementById("btn-filter-strategy");
  const strategyFilterMenu = document.getElementById("filter-strategy-menu");
  if (strategyFilterBtn && strategyFilterMenu) {
    strategyFilterBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      const willOpen = strategyFilterMenu.classList.contains("hidden");
      strategyFilterMenu.classList.toggle("hidden", !willOpen);
      strategyFilterBtn.setAttribute("aria-expanded", willOpen ? "true" : "false");
    });
    document.getElementById("btn-filter-strategy-all")?.addEventListener("click", () => {
      setSetupStrategyFilterSelection(state.strategies.map((s) => s.name));
    });
    document.getElementById("btn-filter-strategy-clear")?.addEventListener("click", () => {
      setSetupStrategyFilterSelection([]);
    });
    document.addEventListener("click", (e) => {
      if (strategyFilterWrap && !strategyFilterWrap.contains(e.target)) {
        closeStrategyFilterMenu();
      }
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") closeStrategyFilterMenu();
    });
  }
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

  document.getElementById("filter-run-id")?.addEventListener("input", () => {
    clearTimeout(window.__runIdDebounce);
    window.__runIdDebounce = setTimeout(() => {
      state.runsPage = 1;
      loadScanRuns();
    }, 250);
  });
  document.getElementById("filter-run-status")?.addEventListener("change", () => {
    state.runsPage = 1;
    loadScanRuns();
  });
  document.getElementById("btn-reset-run-filters")?.addEventListener("click", () => {
    const idEl = document.getElementById("filter-run-id");
    const stEl = document.getElementById("filter-run-status");
    if (idEl) idEl.value = "";
    if (stEl) stEl.value = "ALL";
    state.runsPage = 1;
    runsRangePicker.applyPreset("this_month", true);
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

  async function copyTextWithFeedback(text, btn = null) {
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
      if (btn) {
        const prev = btn.textContent;
        btn.textContent = "Copied!";
        btn.classList.add("copied");
        setTimeout(() => {
          btn.textContent = prev;
          btn.classList.remove("copied");
        }, 1200);
      }
      showToast(`Disalin: ${text}`);
    } catch (err) {
      showToast(`Gagal copy: ${err.message}`, true);
    }
  }

  document.querySelectorAll(".copy-btn[data-copy-field]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!state.selectedSetup) return;
      const field = btn.dataset.copyField;
      let rawVal;
      if (field === "symbol_mexc") {
        rawVal = String(state.selectedSetup.symbol || "").replace(/_/g, "");
      } else if (field === "entry_price") {
        rawVal = state.selectedSetup.manual_entry_price ?? state.selectedSetup.entry_price;
      } else {
        rawVal = state.selectedSetup[field];
      }
      if (rawVal === null || rawVal === undefined || rawVal === "") return;
      await copyTextWithFeedback(String(rawVal), btn);
    });
  });

  function closeQuickCopyModal() {
    document.getElementById("quick-copy-modal")?.classList.add("hidden");
  }

  function openQuickCopyModal() {
    const s = state.selectedSetup;
    if (!s) return;
    const modal = document.getElementById("quick-copy-modal");
    if (!modal) return;
    const pairMexc = String(s.symbol || "").replace(/_/g, "");
    const effEntry = s.manual_entry_price ?? s.entry_price;
    const dirEl = document.getElementById("qc-dir");
    document.getElementById("qc-pair").textContent = pairMexc;
    if (dirEl) {
      dirEl.textContent = s.decision;
      dirEl.className = `badge ${s.decision === "LONG" ? "badge-long" : "badge-short"}`;
    }
    document.getElementById("qc-entry-type").textContent = s.manual_entry_price ? "MANUAL" : s.entry_type;
    document.getElementById("qc-entry").textContent = fmtPrice(effEntry);
    document.getElementById("qc-tp").textContent = fmtPrice(s.take_profit);
    document.getElementById("qc-sl").textContent = fmtPrice(s.stop_loss);
    const bepRow = document.getElementById("qc-bep-row");
    const bepVal = document.getElementById("qc-bep");
    if (bepRow && bepVal) {
      if (s.sl_bep_price) {
        bepVal.textContent = fmtPrice(s.sl_bep_price);
        bepRow.classList.remove("hidden");
      } else {
        bepRow.classList.add("hidden");
      }
    }
    modal.classList.remove("hidden");
  }

  document.getElementById("btn-open-quick-copy")?.addEventListener("click", openQuickCopyModal);
  document.getElementById("btn-close-quick-copy")?.addEventListener("click", closeQuickCopyModal);
  document.getElementById("btn-cancel-quick-copy")?.addEventListener("click", closeQuickCopyModal);
  document.getElementById("quick-copy-modal")?.addEventListener("click", (e) => {
    if (e.target && e.target.id === "quick-copy-modal") closeQuickCopyModal();
  });
  document.getElementById("btn-copy-all-setup")?.addEventListener("click", async (e) => {
    const s = state.selectedSetup;
    if (!s) return;
    const pairMexc = String(s.symbol || "").replace(/_/g, "");
    const effEntry = s.manual_entry_price ?? s.entry_price;
    const lines = [
      `Pair: ${pairMexc} (${s.decision})`,
      `Entry: ${effEntry}`,
      `TP: ${s.take_profit}`,
      `SL: ${s.stop_loss}`,
    ];
    if (s.sl_bep_price) lines.push(`SL-BEP: ${s.sl_bep_price}`);
    await copyTextWithFeedback(lines.join("\n"), e.currentTarget);
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
    const anyModalOpen = ["edit-status-modal", "scan-eval-modal"].some((id) => {
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
        const minGap = Math.max(orig.entry * 0.0005, 1e-12);

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

    const extRaw = document.getElementById("edit-extend-hours")?.value;
    const extParsed = extRaw ? Number(extRaw) : null;
    if (statusVal === "EXTENDED" && (!Number.isInteger(extParsed) || extParsed < 1 || extParsed > 720)) {
      showToast("Durasi perpanjang expiry harus berupa angka bulat 1–720 jam.", true);
      return;
    }

    const bepParsed = parseOptionalFloatText(document.getElementById("edit-sl-bep-price")?.value);
    if (statusVal === "MOVE_SL_BEP") {
      if (Number.isNaN(bepParsed)) {
        showToast("Harga SL-BEP harus berupa angka positif.", true);
        return;
      }
      const stSetup = state.editingSetup;
      if (stSetup) {
        const effEntry = Number(stSetup.manual_entry_price ?? stSetup.entry_price);
        const effBep = bepParsed ?? effEntry;
        const livePx = Number(stSetup.live_price);
        if (stSetup.decision === "LONG" && effBep < effEntry) {
          showToast(`SL-BEP LONG (${fmtPrice(effBep)}) tidak boleh di bawah Entry (${fmtPrice(effEntry)}).`, true);
          return;
        }
        if (stSetup.decision === "SHORT" && effBep > effEntry) {
          showToast(`SL-BEP SHORT (${fmtPrice(effBep)}) tidak boleh di atas Entry (${fmtPrice(effEntry)}).`, true);
          return;
        }
        if (Number.isFinite(livePx) && livePx > 0) {
          if (stSetup.decision === "LONG" && (livePx <= effEntry || livePx <= effBep)) {
            showToast(`Posisi LONG belum profit / harga (${fmtPrice(livePx)}) harus di atas Entry & SL-BEP.`, true);
            return;
          }
          if (stSetup.decision === "SHORT" && (livePx >= effEntry || livePx >= effBep)) {
            showToast(`Posisi SHORT belum profit / harga (${fmtPrice(livePx)}) harus di bawah Entry & SL-BEP.`, true);
            return;
          }
        }
      }
    }

    const canSendRisk = statusVal === "MANUAL_TAKEN" || statusVal === "ENTRY_HIT" || statusVal === "EXTENDED" || statusVal === "OPEN";
    const ok = await updateManualStatus(statusVal, {
      manual_entry_price:
        statusVal === "MANUAL_TAKEN" ||
        statusVal === "ENTRY_HIT" ||
        statusVal === "CLOSED_MANUAL_TP" ||
        statusVal === "CLOSED_MANUAL_CL"
          ? entryParsed
          : null,
      sl_bep_price: statusVal === "MOVE_SL_BEP" ? bepParsed : null,
      live_price: statusVal === "MOVE_SL_BEP" && state.editingSetup?.live_price ? Number(state.editingSetup.live_price) : null,
      stop_loss: canSendRisk ? slParsed : null,
      take_profit: canSendRisk ? tpParsed : null,
      resolved_price:
        statusVal === "CLOSED_MANUAL_TP" || statusVal === "CLOSED_MANUAL_CL" ? closeParsed : null,
      extend_hours: statusVal === "EXTENDED" ? extParsed : null,
      manual_notes: document.getElementById("edit-manual-notes").value,
    });
    if (ok) {
      document.getElementById("edit-status-modal").classList.add("hidden");
    }
  });

  document.getElementById("btn-dismiss-error").addEventListener("click", hideErrorBanner);

  const btnScanBtc = document.getElementById("btn-scan-btc-mover");
  if (btnScanBtc) btnScanBtc.addEventListener("click", triggerBtcMarketMoverScan);
  const btnApplyBtc = document.getElementById("btn-apply-btc-suggestion");
  if (btnApplyBtc) btnApplyBtc.addEventListener("click", applyBtcMarketMoverSuggestion);
  const btnToggleBtc = document.getElementById("btn-toggle-btc-mover");
  if (btnToggleBtc) {
    btnToggleBtc.addEventListener("click", () => {
      const body = document.getElementById("btc-mover-body");
      if (!body) return;
      const nextCollapsed = !body.classList.contains("hidden");
      setBtcMoverCollapsed(nextCollapsed, true);
    });
  }

  async function executeRunScan() {
    try {
      hideErrorBanner();
      syncScanButtonsState(true);
      const res = await apiRequest("/api/scanner/run", { method: "POST" });
      showToast(res.message);

      if (!res.started) {
        const stNow = await loadHealthAndStatus();
        syncScanButtonsState(stNow?.is_running);
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
            syncScanButtonsState(false);
            await Promise.all([loadSetups(), loadAnalytics()]);
            if (latest && latest.status === "FAILED") {
              showToast(`Scan #${latest.id} gagal: ${latest.error_message || "Cek banner error"}`, true);
            } else if (latest && latest.status === "COMPLETED") {
              showToast(`Scan #${latest.id} selesai: ${latest.setups_created_count} setup baru.`);
            }
          }
        } catch (pollErr) {
          clearInterval(timer);
          syncScanButtonsState(false);
          showErrorBanner("Gagal Memantau Status Scan", pollErr.message);
        }
      }, 2000);
    } catch (err) {
      syncScanButtonsState(false);
      showErrorBanner("Gagal Menjalankan Scan", err.message);
      showToast(err.message, true);
    }
  }

  function closeConfirmRunScanModal() {
    document.getElementById("confirm-scan-modal")?.classList.add("hidden");
  }

  function openConfirmRunScanModal() {
    const modal = document.getElementById("confirm-scan-modal");
    if (!modal) {
      executeRunScan();
      return;
    }
    const llmLabel = document.getElementById("active-llm-label")?.textContent || "-";
    const activeStrats = (state.strategies || []).filter((s) => s.is_active);
    const llmEl = document.getElementById("confirm-scan-llm");
    const stratsEl = document.getElementById("confirm-scan-strategies");
    const btcRow = document.getElementById("confirm-scan-btc-row");
    const btcEl = document.getElementById("confirm-scan-btc");

    if (llmEl) llmEl.textContent = llmLabel;
    if (stratsEl) {
      stratsEl.innerHTML = activeStrats.length
        ? activeStrats
            .map((s) => `<span class="badge badge-open">${escapeHtml(s.name)}</span>`)
            .join("")
        : `<span class="badge badge-hit-sl">Tidak ada strategi aktif</span>`;
    }
    if (btcRow && btcEl) {
      if (latestBtcMoverReport && latestBtcMoverReport.btc) {
        const b = latestBtcMoverReport.btc;
        const adv = latestBtcMoverReport.advisor || {};
        const alignBadge = adv.alignment === "SELARAS" ? "badge-hit-tp" : "badge-open";
        const alignTxt = adv.alignment === "SELARAS" ? "Selaras" : (adv.alignment || "-");
        btcEl.innerHTML = `<span class="badge ${_btcRegimeBadgeClass(b.overall_regime)}">${escapeHtml(b.overall_regime)} &bull; ${escapeHtml(b.overall_bias)}</span> <span class="badge ${alignBadge}">${escapeHtml(alignTxt)}</span>`;
        btcRow.classList.remove("hidden");
      } else {
        btcRow.classList.add("hidden");
      }
    }
    modal.classList.remove("hidden");
  }

  document.getElementById("btn-run-scan").addEventListener("click", openConfirmRunScanModal);
  document.getElementById("btn-close-confirm-scan")?.addEventListener("click", closeConfirmRunScanModal);
  document.getElementById("btn-cancel-confirm-scan")?.addEventListener("click", closeConfirmRunScanModal);
  document.getElementById("confirm-scan-modal")?.addEventListener("click", (e) => {
    if (e.target && e.target.id === "confirm-scan-modal") closeConfirmRunScanModal();
  });
  document.getElementById("btn-confirm-run-scan")?.addEventListener("click", () => {
    closeConfirmRunScanModal();
    executeRunScan();
  });

  document.getElementById("btn-close-confirm-delete")?.addEventListener("click", closeConfirmDeleteModal);
  document.getElementById("btn-cancel-confirm-delete")?.addEventListener("click", closeConfirmDeleteModal);
  document.getElementById("confirm-delete-modal")?.addEventListener("click", (e) => {
    if (e.target && e.target.id === "confirm-delete-modal") closeConfirmDeleteModal();
  });
  document.getElementById("btn-confirm-delete-ok")?.addEventListener("click", async () => {
    const fn = pendingDeleteAction;
    closeConfirmDeleteModal();
    if (typeof fn === "function") {
      try {
        await fn();
      } catch (err) {
        showToast(err.message, true);
      }
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

const MAIN_VIEWS = ["scanner", "dashboard", "runs", "settings"];

function updateTopbarOverflow() {
  const topbar = document.querySelector(".topbar");
  const nav = document.getElementById("topbar-nav");
  const dropdown = document.getElementById("nav-overflow-dropdown");
  const menu = document.getElementById("nav-overflow-menu");
  const moreBtn = document.getElementById("btn-nav-more");
  const actions = document.querySelector(".topbar-actions");
  if (!topbar || !nav || !dropdown || !menu || !moreBtn || !actions) return;

  // Restore all nav items and reset Menu toggle width before measuring fit
  const allItems = Array.from(document.querySelectorAll("[data-nav-item]"));
  allItems.forEach((el) => nav.insertBefore(el, dropdown));
  dropdown.classList.add("hidden");
  menu.classList.add("hidden");
  moreBtn.setAttribute("aria-expanded", "false");
  moreBtn.classList.remove("has-active");
  moreBtn.innerHTML = "Menu &#9662;";
  moreBtn.title = "Menu lainnya";

  const isOverflowing = () =>
    topbar.scrollWidth > topbar.clientWidth + 2 ||
    actions.scrollWidth > actions.clientWidth + 2 ||
    topbar.getBoundingClientRect().height > 76 ||
    actions.getBoundingClientRect().height > 54;

  // Move trailing items into dropdown (keep first item `Scanner` visible) until topbar fits in 1 row
  const movable = allItems.slice(1);
  while (movable.length > 0 && isOverflowing()) {
    const popped = movable.pop();
    dropdown.classList.remove("hidden");
    menu.insertBefore(popped, menu.firstChild);
  }

  const hasItemsInMenu = menu.children.length > 0;
  dropdown.classList.toggle("hidden", !hasItemsInMenu);

  const activeInsideDropdown = Array.from(menu.querySelectorAll("[data-view-tab]")).find((b) =>
    b.classList.contains("active")
  );
  moreBtn.classList.toggle("has-active", Boolean(activeInsideDropdown));
  moreBtn.title = activeInsideDropdown
    ? `Menu aktif: ${activeInsideDropdown.textContent.trim()}`
    : "Menu lainnya";
}

function wireTopbarDropdown() {
  const dropdown = document.getElementById("nav-overflow-dropdown");
  const menu = document.getElementById("nav-overflow-menu");
  const moreBtn = document.getElementById("btn-nav-more");
  if (!dropdown || !menu || !moreBtn) return;

  moreBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    const willOpen = menu.classList.contains("hidden");
    menu.classList.toggle("hidden", !willOpen);
    moreBtn.setAttribute("aria-expanded", willOpen ? "true" : "false");
  });

  document.addEventListener("click", (e) => {
    if (!dropdown.contains(e.target)) {
      menu.classList.add("hidden");
      moreBtn.setAttribute("aria-expanded", "false");
    }
  });

  const topbar = document.querySelector(".topbar");
  if (topbar && typeof ResizeObserver === "function") {
    new ResizeObserver(() => updateTopbarOverflow()).observe(topbar);
  }
  window.addEventListener("resize", updateTopbarOverflow);
}

function switchMainView(viewName, updateHash = true) {
  const target = MAIN_VIEWS.includes(viewName) ? viewName : "scanner";
  MAIN_VIEWS.forEach((v) => {
    const el = document.getElementById(`view-${v}`);
    if (el) el.classList.toggle("hidden", v !== target);
  });

  document.querySelectorAll("button[data-view-tab]").forEach((btn) => {
    const isAct = btn.dataset.viewTab === target;
    btn.classList.toggle("active", isAct);
    btn.setAttribute("aria-selected", isAct ? "true" : "false");
  });

  // Close overflow dropdown menu after selecting a tab
  const menu = document.getElementById("nav-overflow-menu");
  const moreBtn = document.getElementById("btn-nav-more");
  if (menu) menu.classList.add("hidden");
  if (moreBtn) moreBtn.setAttribute("aria-expanded", "false");
  updateTopbarOverflow();

  if (updateHash && window.history && typeof window.history.replaceState === "function") {
    const nextHash = `#${target}`;
    if (window.location.hash !== nextHash) {
      window.history.replaceState(null, "", nextHash);
    }
  }

  if (target === "settings") {
    loadAIModalData(true);
  } else if (target === "runs") {
    loadScanRuns();
  } else if (target === "scanner") {
    loadStrategies();
  }

  requestAnimationFrame(() => {
    if (target === "dashboard") {
      if (state.strategyChart) state.strategyChart.resize();
      else loadAnalytics();
    } else if (target === "scanner" && state.chart) {
      const container = document.getElementById("candlestick-chart");
      if (container && container.clientWidth > 0) {
        state.chart.applyOptions({ width: container.clientWidth, height: container.clientHeight });
      }
      scheduleOverlayRender();
    }
  });
}

let latestBtcMoverReport = null;
let pendingDeleteAction = null;

function closeConfirmDeleteModal() {
  pendingDeleteAction = null;
  document.getElementById("confirm-delete-modal")?.classList.add("hidden");
}

function openConfirmDeleteModal({ title, message, detailHtml = "", onConfirm }) {
  const modal = document.getElementById("confirm-delete-modal");
  if (!modal) return;
  const titleEl = document.getElementById("confirm-delete-title");
  const msgEl = document.getElementById("confirm-delete-msg");
  const detailEl = document.getElementById("confirm-delete-detail");
  if (titleEl) titleEl.textContent = title || "Konfirmasi Hapus";
  if (msgEl) msgEl.textContent = message || "Apakah Anda yakin ingin menghapus item ini?";
  if (detailEl) {
    if (detailHtml) {
      detailEl.innerHTML = detailHtml;
      detailEl.classList.remove("hidden");
    } else {
      detailEl.innerHTML = "";
      detailEl.classList.add("hidden");
    }
  }
  pendingDeleteAction = onConfirm || null;
  modal.classList.remove("hidden");
}

function _btcRegimeBadgeClass(regime) {
  if (regime === "TRENDING_UP") return "badge-hit-tp";
  if (regime === "TRENDING_DOWN" || regime === "HIGH_VOLATILITY") return "badge-hit-sl";
  if (regime === "RANGING") return "badge-open";
  return "badge-neutral";
}

function renderBtcMarketMover(report) {
  latestBtcMoverReport = report || null;
  const pricePill = document.getElementById("btc-mover-price-pill");
  const regimePill = document.getElementById("btc-mover-regime-pill");
  const alignPill = document.getElementById("btc-mover-align-pill");
  const subtitleEl = document.getElementById("btc-mover-subtitle");
  const bodyEl = document.getElementById("btc-mover-body");
  const applyBtn = document.getElementById("btn-apply-btc-suggestion");
  if (!pricePill || !bodyEl) return;

  if (!report || !report.btc) {
    pricePill.textContent = "Belum discan";
    pricePill.className = "badge badge-neutral";
    regimePill?.classList.add("hidden");
    alignPill?.classList.add("hidden");
    applyBtn?.classList.add("hidden");
    bodyEl.innerHTML = `<div class="subtitle-sm">Klik <strong>Scan BTC_USDT</strong> untuk membaca kondisi BTC saat ini (Scalp, Harian/Intraday, Swing) dan melihat sugesti settingan scan.</div>`;
    return;
  }

  const btc = report.btc;
  const adv = report.advisor || {};
  const curr = adv.current_summary || {};
  const sug = adv.suggested_settings || {};
  const chg = Number(btc.change_24h_pct || 0);
  const chgStr = `${chg >= 0 ? "+" : ""}${chg.toFixed(2)}%`;

  pricePill.textContent = `$${Number(btc.last_price || 0).toLocaleString("en-US")} (${chgStr})`;
  pricePill.className = `badge ${chg >= 0 ? "badge-hit-tp" : "badge-hit-sl"}`;

  if (regimePill) {
    regimePill.textContent = `${btc.overall_regime || "-"} • ${btc.overall_bias || "-"}`;
    regimePill.className = `badge ${_btcRegimeBadgeClass(btc.overall_regime)}`;
  }

  const diffs = Array.isArray(sug.diffs) ? sug.diffs : [];
  if (alignPill) {
    const al = adv.alignment || "SELARAS";
    alignPill.textContent = al === "SELARAS" ? "Settingan Selaras" : `${diffs.length} Sugesti Settingan`;
    alignPill.className = `badge ${al === "SELARAS" ? "badge-hit-tp" : "badge-open"}`;
  }

  if (subtitleEl) {
    const scannedAt = btc.scanned_at ? formatJakartaDateTime(btc.scanned_at) : "-";
    subtitleEl.textContent = `Scan BTC terakhir: ${scannedAt} • Volatilitas: ${btc.volatility_state || "-"} • Funding: ${Number(btc.funding_rate_pct || 0).toFixed(4)}%`;
  }

  if (applyBtn) {
    if (diffs.length > 0 && sug.patch_payload) {
      applyBtn.classList.remove("hidden");
    } else {
      applyBtn.classList.add("hidden");
    }
  }

  const stylesObj = btc.styles || {};
  const styleOrder = ["SCALP", "INTRADAY", "SWING"];
  const stylesHtml = styleOrder
    .map((key) => {
      const st = stylesObj[key];
      if (!st) return "";
      const htf = st.htf || {};
      const ltf = st.ltf || {};
      const tfLabel = htf.interval && ltf.interval ? `${htf.interval}/${ltf.interval}` : "-";
      return `
        <div class="btc-style-box">
          <div class="btc-style-top">
            <strong>${escapeHtml(st.label || key)}</strong>
            <span class="badge ${_btcRegimeBadgeClass(st.regime)}">${escapeHtml(st.regime || "-")}</span>
          </div>
          <div class="btc-style-metrics">
            <span>TF: <b>${escapeHtml(tfLabel)}</b></span>
            <span>Bias: <b>${escapeHtml(st.bias || "-")}</b></span>
            <span>ATR: <b>${ltf.atr_pct ?? "-"}%</b></span>
            <span>RSI: <b>${ltf.rsi14 ?? "-"}</b></span>
          </div>
          <div class="btc-style-summary">${escapeHtml(st.summary || "-")}</div>
        </div>`;
    })
    .join("");

  const stratRecs = Array.isArray(sug.strategy_recommendations) ? sug.strategy_recommendations : [];
  const stratChipsHtml = stratRecs
    .map((r) => {
      const cls = r.recommended_active ? "rec-on" : "rec-off";
      const badgeText = r.recommended_active ? "Rekomendasi AKTIF" : "Pause Sementara";
      return `<span class="btc-strat-chip ${cls}" title="${escapeHtml(r.reason || "")}"><b>${escapeHtml(r.name)}</b> (${escapeHtml(r.trade_style || "-")}) — ${badgeText}</span>`;
    })
    .join("");

  const diffsHtml = diffs.length
    ? `<div class="btc-diff-list">${diffs
        .map(
          (d) => `
          <div class="btc-diff-item">
            <div class="btc-diff-top">
              <strong>${escapeHtml(d.label || d.field)}</strong>
              <span><code>${escapeHtml(String(d.current))}</code> &rarr; <b><code>${escapeHtml(String(d.suggested))}</code></b></span>
            </div>
            <div class="subtitle-sm">${escapeHtml(d.reason || "")}</div>
          </div>`
        )
        .join("")}</div>`
    : `<div class="subtitle-sm">Semua parameter settingan scan saat ini sudah selaras dengan kondisi BTC_USDT.</div>`;

  bodyEl.innerHTML = `
    <div class="btc-mover-styles-grid">${stylesHtml}</div>
    <div class="btc-advisor-grid">
      <div class="btc-advisor-box">
        <h4>Kesimpulan Settingan Scan Saat Ini</h4>
        <p>${escapeHtml(curr.conclusion || "-")}</p>
        <div class="btc-strat-chips">${stratChipsHtml}</div>
      </div>
      <div class="btc-advisor-box">
        <h4>Sugesti Settingan (${escapeHtml((sug.recommended_styles || []).join(" / ") || "ALL")})</h4>
        <p>${escapeHtml(sug.headline || "-")}</p>
        ${diffsHtml}
      </div>
    </div>`;
}

async function loadBtcMarketMover() {
  try {
    const res = await apiRequest("/api/market-mover/btc");
    renderBtcMarketMover(res.has_data ? res.report : null);
  } catch (err) {
    // Keep panel usable even if initial fetch fails silently
  }
}

async function triggerBtcMarketMoverScan() {
  const btn = document.getElementById("btn-scan-btc-mover");
  const prevText = btn ? btn.textContent : "Scan BTC_USDT";
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Scanning BTC...";
  }
  try {
    hideErrorBanner();
    const res = await apiRequest("/api/market-mover/btc/scan", { method: "POST" });
    renderBtcMarketMover(res.report);
    setBtcMoverCollapsed(false, true);
    showToast("Scan BTC_USDT selesai — kesimpulan & sugesti diperbarui.");
  } catch (err) {
    showErrorBanner("Gagal Scan BTC_USDT", err.message);
    showToast(err.message, true);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = prevText;
    }
  }
}

async function applyBtcMarketMoverSuggestion() {
  const payload = latestBtcMoverReport?.advisor?.suggested_settings?.patch_payload;
  if (!payload) return;
  const btn = document.getElementById("btn-apply-btc-suggestion");
  if (btn) btn.disabled = true;
  try {
    await apiRequest("/api/scanner/settings", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    await Promise.all([loadStrategies(), loadBtcMarketMover()]);
    showToast("Sugesti settingan berhasil diterapkan ke konfigurasi scanner.");
  } catch (err) {
    showToast(err.message, true);
  } finally {
    if (btn) btn.disabled = false;
  }
}

const BTC_MOVER_COLLAPSED_KEY = "mexc_btc_mover_collapsed";

function setBtcMoverCollapsed(collapsed, persist = true) {
  const body = document.getElementById("btc-mover-body");
  const toggleBtn = document.getElementById("btn-toggle-btc-mover");
  if (body) {
    body.classList.toggle("hidden", Boolean(collapsed));
  }
  if (toggleBtn) {
    toggleBtn.textContent = collapsed ? "Tampilkan" : "Sembunyikan";
    toggleBtn.setAttribute("aria-expanded", String(!collapsed));
  }
  if (persist) {
    localStorage.setItem(BTC_MOVER_COLLAPSED_KEY, collapsed ? "1" : "0");
  }
}

async function bootstrap() {
  const savedBtcCollapsed = localStorage.getItem(BTC_MOVER_COLLAPSED_KEY) === "1";
  setBtcMoverCollapsed(savedBtcCollapsed, false);
  const savedLiveMs = localStorage.getItem("mexc_live_chart_ms");
  if (savedLiveMs !== null) {
    const sel = document.getElementById("live-chart-interval");
    if (Array.from(sel.options).some((o) => o.value === savedLiveMs)) {
      sel.value = savedLiveMs;
    }
  }
  wireEvents();
  wireTopbarDropdown();
  dashRangePicker.wire();
  setupsRangePicker.wire();
  runsRangePicker.wire();
  dashRangePicker.applyPreset("this_month", false);
  setupsRangePicker.applyPreset("last_7d", false);
  runsRangePicker.applyPreset("this_month", false);
  const hashView = (window.location.hash || "").replace(/^#/, "");
  const initialView = MAIN_VIEWS.includes(hashView) ? hashView : "scanner";
  switchMainView(initialView, false);
  await Promise.all([loadStrategies(), loadHealthAndStatus(), loadAnalytics(), loadSetups(), loadBtcMarketMover()]);
  updateTopbarOverflow();
  if (initialView === "dashboard" && state.strategyChart) {
    state.strategyChart.resize();
  }
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
