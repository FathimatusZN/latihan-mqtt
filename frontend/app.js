/**
 * FILE    : frontend/app.js
 * VERSI   : 2.0 — Topic-based Architecture
 * FUNGSI  : Fetch dari API v2 → render dashboard
 *
 * Perubahan dari v1:
 *   - /mesin/status  → /devices/status
 *   - /mesin         → /devices
 *   - /logs filter nama_mesin → device_id
 *   - Gauge sekarang aware multi-tag per device
 */

const API_BASE = window.APP_CONFIG?.API_BASE ?? "http://localhost:8000";
const REFRESH_INTERVAL = 5000;
const LOG_LIMIT = 100;

// ── TEMA ──────────────────────────────────────────────────
let isDark = localStorage.getItem("theme") === "dark";

function applyTheme() {
  document.documentElement.setAttribute(
    "data-theme",
    isDark ? "dark" : "light",
  );
  document.getElementById("iconSun").style.display = isDark ? "none" : "block";
  document.getElementById("iconMoon").style.display = isDark ? "block" : "none";
  localStorage.setItem("theme", isDark ? "dark" : "light");
}
function toggleTheme() {
  isDark = !isDark;
  applyTheme();
}

// ── CLOCK ─────────────────────────────────────────────────
function updateClock() {
  const now = new Date(),
    p = (n) => String(n).padStart(2, "0");
  document.getElementById("navClock").textContent =
    `${p(now.getHours())}:${p(now.getMinutes())}:${p(now.getSeconds())}`;
}
setInterval(updateClock, 1000);
updateClock();

// ── STATUS INDICATOR ──────────────────────────────────────
function setConnected(ok) {
  const pill = document.getElementById("livePill");
  const label = document.getElementById("liveLabel");
  pill.className = ok ? "live-pill" : "live-pill error";
  label.textContent = ok ? "Live" : "Offline";
}

// ── UTILS ─────────────────────────────────────────────────
const fmtTime = (iso) => {
  if (!iso) return "—";
  const d = new Date(iso),
    p = (n) => String(n).padStart(2, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
};
const fmtDateTime = (iso) => {
  if (!iso) return "—";
  const d = new Date(iso),
    p = (n) => String(n).padStart(2, "0");
  return `${p(d.getDate())}/${p(d.getMonth() + 1)} ${p(d.getHours())}:${p(d.getMinutes())}`;
};
const statusClass = (s) =>
  ({ NORMAL: "ok", WARNING: "warn", CRITICAL: "crit" })[s] || "";
const badge = (s) => {
  const c = statusClass(s);
  return `<span class="badge badge-${c}">${s}</span>`;
};

// ── GAUGE SVG ─────────────────────────────────────────────
function buildGaugeSVG(nilai, maxVal, status) {
  const pct = Math.min(nilai / maxVal, 1);
  const r = 30,
    len = Math.PI * r;
  const fill = pct * len;
  const gap = len - fill + 1;
  const colMap = { NORMAL: "#15803d", WARNING: "#b45309", CRITICAL: "#b91c1c" };
  const trackCol = isDark ? "#1a2030" : "#f3f4f6";
  const col = colMap[status] || "#6b7280";
  return `
    <svg width="80" height="44" viewBox="0 0 80 44">
      <path d="M 10,38 A 30,30 0 0,1 70,38"
        fill="none" stroke="${trackCol}" stroke-width="6" stroke-linecap="round"/>
      <path d="M 10,38 A 30,30 0 0,1 70,38"
        fill="none" stroke="${col}" stroke-width="6" stroke-linecap="round"
        stroke-dasharray="${fill.toFixed(1)} ${gap.toFixed(1)}"/>
    </svg>`;
}

// ── KELOMPOKKAN DATA PER DEVICE ────────────────────────────
/**
 * API /devices/status mengembalikan flat list (satu baris per tag).
 * Fungsi ini mengelompokkan menjadi { device_id: { info, tags: [...] } }
 */
function groupByDevice(flatData) {
  const map = {};
  for (const row of flatData) {
    if (!map[row.device_id]) {
      map[row.device_id] = {
        device_id: row.device_id,
        nama_display: row.nama_display,
        lokasi: row.lokasi,
        factory_id: row.factory_id,
        tags: [],
      };
    }
    map[row.device_id].tags.push(row);
  }
  return Object.values(map);
}

// ── RENDER GAUGES ─────────────────────────────────────────
/**
 * v2: satu kartu gauge per TAG (bukan per device),
 * karena satu device bisa punya current, voltage, pressure, dll.
 * Tag "current" ditampilkan lebih besar sebagai primary metric.
 */
function renderGauges(flatData) {
  const grid = document.getElementById("gaugeGrid");
  if (!flatData || flatData.length === 0) {
    grid.innerHTML = `<div class="empty-state">Belum ada device & tag terdaftar</div>`;
    return;
  }

  grid.innerHTML = flatData
    .map((row) => {
      const hasData =
        row.nilai_terkini !== null && row.nilai_terkini !== undefined;
      const arus = hasData ? parseFloat(row.nilai_terkini) : 0;
      const status = hasData ? row.status_terkini || "NORMAL" : null;
      const maxVal =
        parseFloat(row.batas_critical) ||
        parseFloat(row.batas_warning) * 1.3 ||
        25;
      const c = status ? statusClass(status) : "";
      const satuan = row.satuan || "";
      const tagLabel = (row.tag_name || "").toUpperCase();

      const statusBadge = hasData
        ? badge(status)
        : `<span class="badge" style="background:var(--surface2);color:var(--txt4);border:1px solid var(--border)">NO DATA</span>`;

      const arusDisplay = hasData ? arus.toFixed(2) : "—";
      const arusClass = hasData ? `txt-${c}` : "txt-muted";

      return `
    <div class="gauge-item">
      <div class="gauge-name">${(row.nama_display || row.device_id).replace(/_/g, " ")}</div>
      <div style="font-size:9px;color:var(--txt4);margin-top:-4px;margin-bottom:2px">${tagLabel}</div>
      ${buildGaugeSVG(arus, maxVal, status || "NORMAL")}
      <div class="gauge-val ${arusClass}">${arusDisplay}</div>
      <div class="gauge-unit">${satuan}</div>
      ${statusBadge}
      <div class="gauge-loc">${row.lokasi || "—"}</div>
    </div>`;
    })
    .join("");
}

// ── RENDER STATISTIK ──────────────────────────────────────
function renderStatistik(flatData) {
  const tbody = document.getElementById("statBody");
  if (!flatData || flatData.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" class="empty-cell">Belum ada data</td></tr>`;
    return;
  }

  tbody.innerHTML = flatData
    .map((row) => {
      const hasData =
        row.total_pembacaan !== null && row.total_pembacaan !== undefined;
      const rata = hasData
        ? parseFloat(row.rata_rata).toFixed(2) + ` ${row.satuan || ""}`
        : "—";
      const maks = hasData
        ? parseFloat(row.nilai_max).toFixed(2) + ` ${row.satuan || ""}`
        : "—";
      const warn = hasData ? row.total_warning : "—";
      const crit = hasData ? row.total_critical : "—";
      const warnCls =
        hasData && row.total_warning > 0 ? "txt-warn" : "txt-muted";
      const critCls =
        hasData && row.total_critical > 0 ? "txt-crit" : "txt-muted";

      return `
    <tr>
      <td style="font-weight:500">${(row.nama_display || row.device_id).replace(/_/g, " ")}</td>
      <td style="font-size:10px;color:var(--txt4)">${row.tag_name}</td>
      <td class="txt-muted">${rata}</td>
      <td class="txt-warn">${maks}</td>
      <td class="${warnCls}">${warn}</td>
      <td class="${critCls}">${crit}</td>
    </tr>`;
    })
    .join("");
}

// ── RENDER KPI ────────────────────────────────────────────
function renderKPI(flatData) {
  const totalLog = flatData.reduce(
    (s, r) => s + (parseInt(r.total_pembacaan) || 0),
    0,
  );
  const totalWarn = flatData.reduce(
    (s, r) => s + (parseInt(r.total_warning) || 0),
    0,
  );
  const totalCrit = flatData.reduce(
    (s, r) => s + (parseInt(r.total_critical) || 0),
    0,
  );

  // Jumlah device unik yang aktif
  const devSet = new Set(flatData.map((r) => r.device_id));

  // Rata-rata hanya dari tag yang punya data
  const withData = flatData.filter(
    (r) => r.rata_rata !== null && r.rata_rata !== undefined,
  );
  const avgVal = withData.length
    ? (
        withData.reduce((s, r) => s + parseFloat(r.rata_rata), 0) /
        withData.length
      ).toFixed(2)
    : null;

  document.getElementById("kTotal").textContent = totalLog;
  document.getElementById("kAktif").textContent = devSet.size;
  document.getElementById("kWarn").textContent = totalWarn;
  document.getElementById("kCrit").textContent = totalCrit;
  document.getElementById("kAvg").textContent = avgVal !== null ? avgVal : "—";

  // Alert banner
  const banner = document.getElementById("alertBanner");
  if (totalCrit > 0) {
    const critTags = flatData
      .filter((r) => r.total_critical > 0)
      .map(
        (r) =>
          `${(r.nama_display || r.device_id).replace(/_/g, " ")}/${r.tag_name}`,
      )
      .join(", ");
    document.getElementById("alertText").textContent =
      `${totalCrit} CRITICAL terdeteksi pada: ${critTags}`;
    banner.style.display = "flex";
  } else {
    banner.style.display = "none";
  }
}

// ── FETCH LOGS ────────────────────────────────────────────
async function fetchLogs() {
  const deviceId = document.getElementById("filterMesin").value;
  const status = document.getElementById("filterStatus").value;
  let url = `${API_BASE}/logs?limit=${LOG_LIMIT}`;
  if (deviceId) url += `&device_id=${encodeURIComponent(deviceId)}`;
  if (status) url += `&status=${encodeURIComponent(status)}`;

  try {
    const res = await fetch(url);
    const json = await res.json();
    const rows = json.data || [];
    const tbody = document.getElementById("logBody");

    if (!rows.length) {
      tbody.innerHTML = `<tr><td colspan="6" class="empty-cell">Belum ada log</td></tr>`;
      return [];
    }

    tbody.innerHTML = rows
      .map((r) => {
        const c = statusClass(r.status);
        const val = parseFloat(r.value).toFixed(3);
        return `<tr>
        <td class="txt-muted">${fmtDateTime(r.ts_simpan)}</td>
        <td style="font-weight:500">${r.device_id}</td>
        <td style="font-size:10px;color:var(--txt4)">${r.tag_name}</td>
        <td class="txt-${c}">${val}</td>
        <td>${badge(r.status)}</td>
        <td>
          <div class="bar-wrap">
            <div class="bar-fill bar-${c}" style="width:${Math.min((parseFloat(r.value) / 25) * 100, 100).toFixed(0)}%"></div>
          </div>
        </td>
      </tr>`;
      })
      .join("");

    return rows;
  } catch {
    document.getElementById("logBody").innerHTML =
      `<tr><td colspan="6" class="empty-cell">Gagal memuat log</td></tr>`;
    return [];
  }
}

// ── FETCH DEVICE LIST (untuk dropdown) ────────────────────
async function fetchDeviceList() {
  try {
    const res = await fetch(`${API_BASE}/devices`);
    const json = await res.json();
    const sel = document.getElementById("filterMesin");
    (json.data || []).forEach((d) => {
      if (!sel.querySelector(`option[value="${d.device_id}"]`)) {
        const opt = document.createElement("option");
        opt.value = d.device_id;
        opt.textContent = (d.nama_display || d.device_id).replace(/_/g, " ");
        sel.appendChild(opt);
      }
    });
  } catch {
    /* silent */
  }
}

// ── FETCH ALL ─────────────────────────────────────────────
async function fetchAll() {
  try {
    const [statusRes] = await Promise.all([
      fetch(`${API_BASE}/devices/status`),
      fetchLogs(),
    ]);
    const statusJson = await statusRes.json();
    const flatData = statusJson.data || [];

    renderKPI(flatData);
    renderGauges(flatData);
    renderStatistik(flatData);

    const now = new Date();
    document.getElementById("lastUpdate").textContent =
      `Update: ${fmtTime(now)}`;
    document.getElementById("footerUpdate").textContent =
      `Terakhir update: ${now.toLocaleTimeString("id-ID")}`;

    setConnected(true);
  } catch {
    setConnected(false);
  }
}

// ── INIT ─────────────────────────────────────────────────
(async function init() {
  applyTheme();
  document.getElementById("footerApi").textContent = API_BASE;
  await fetchDeviceList();
  await fetchAll();
  setInterval(fetchAll, REFRESH_INTERVAL);
})();
