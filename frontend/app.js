/**
 * FILE    : frontend/app.js
 * FUNGSI  : Fetch data dari Backend API → render ke dashboard
 * CATATAN : Ganti API_BASE jika backend berjalan di port / host lain
 */

const API_BASE = "http://localhost:8000";
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
  const now = new Date();
  const p = (n) => String(n).padStart(2, "0");
  document.getElementById("navClock").textContent =
    `${p(now.getHours())}:${p(now.getMinutes())}:${p(now.getSeconds())}`;
}
setInterval(updateClock, 1000);
updateClock();

// ── STATUS INDICATOR ──────────────────────────────────────
function setConnected(ok) {
  const pill = document.getElementById("livePill");
  const label = document.getElementById("liveLabel");
  if (ok) {
    pill.className = "live-pill";
    label.textContent = "Live";
  } else {
    pill.className = "live-pill error";
    label.textContent = "Offline";
  }
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
  const r = 30;
  const len = Math.PI * r;
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

// ── RENDER GAUGES ─────────────────────────────────────────
// Terima data dari /mesin/status — semua mesin aktif selalu muncul
function renderGauges(mesinData) {
  const grid = document.getElementById("gaugeGrid");

  if (!mesinData || mesinData.length === 0) {
    grid.innerHTML = `<div class="empty-state">Belum ada mesin terdaftar — tambahkan via halaman Kelola Perangkat</div>`;
    return;
  }

  grid.innerHTML = mesinData
    .map((m) => {
      const hasData =
        m.nilai_arus_terkini !== null && m.nilai_arus_terkini !== undefined;
      const arus = hasData ? parseFloat(m.nilai_arus_terkini) : 0;
      const status = hasData ? m.status_terkini || "NORMAL" : null;
      const maxVal = parseFloat(m.batas_arus_max) || 25;
      const c = status ? statusClass(status) : "";

      // Badge: kalau belum ada data, tampilkan "BELUM ADA DATA"
      const statusBadge = hasData
        ? badge(status)
        : `<span class="badge" style="background:var(--surface2);color:var(--txt4);border:1px solid var(--border)">NO DATA</span>`;

      // Nilai arus: tampilkan "—" kalau belum ada data
      const arusDisplay = hasData ? arus.toFixed(1) : "—";
      const arusClass = hasData ? `txt-${c}` : "txt-muted";

      return `
      <div class="gauge-item">
        <div class="gauge-name">${m.nama_mesin.replace(/_/g, " ")}</div>
        ${buildGaugeSVG(arus, maxVal, status || "NORMAL")}
        <div class="gauge-val ${arusClass}">${arusDisplay}</div>
        <div class="gauge-unit">Ampere</div>
        ${statusBadge}
        <div class="gauge-loc">${m.lokasi || "—"}</div>
      </div>`;
    })
    .join("");
}

// ── RENDER STATISTIK ──────────────────────────────────────
// Terima data dari /mesin/status — mesin tanpa data tampil dengan "—"
function renderStatistik(mesinData) {
  const tbody = document.getElementById("statBody");

  if (!mesinData || mesinData.length === 0) {
    tbody.innerHTML = `<tr><td colspan="5" class="empty-cell">Belum ada mesin terdaftar</td></tr>`;
    return;
  }

  tbody.innerHTML = mesinData
    .map((m) => {
      const hasData =
        m.total_pembacaan !== null && m.total_pembacaan !== undefined;
      const rata = hasData
        ? parseFloat(m.rata_rata_arus).toFixed(1) + " A"
        : "—";
      const puncak = hasData
        ? parseFloat(m.puncak_arus).toFixed(1) + " A"
        : "—";
      const warn = hasData ? m.total_warning : "—";
      const crit = hasData ? m.total_critical : "—";

      const warnClass =
        hasData && m.total_warning > 0 ? "txt-warn" : "txt-muted";
      const critClass =
        hasData && m.total_critical > 0 ? "txt-crit" : "txt-muted";

      return `
      <tr>
        <td style="font-weight:500">${m.nama_mesin.replace(/_/g, " ")}</td>
        <td class="txt-muted">${rata}</td>
        <td class="txt-warn">${puncak}</td>
        <td class="${warnClass}">${warn}</td>
        <td class="${critClass}">${crit}</td>
      </tr>`;
    })
    .join("");
}

// ── RENDER KPI ────────────────────────────────────────────
function renderKPI(mesinData) {
  const totalLog = mesinData.reduce(
    (s, m) => s + (parseInt(m.total_pembacaan) || 0),
    0,
  );
  const totalWarn = mesinData.reduce(
    (s, m) => s + (parseInt(m.total_warning) || 0),
    0,
  );
  const totalCrit = mesinData.reduce(
    (s, m) => s + (parseInt(m.total_critical) || 0),
    0,
  );

  // Rata-rata hanya dari mesin yang ada datanya
  const mesinDenganData = mesinData.filter((m) => m.rata_rata_arus !== null);
  const avgArus = mesinDenganData.length
    ? (
        mesinDenganData.reduce((s, m) => s + parseFloat(m.rata_rata_arus), 0) /
        mesinDenganData.length
      ).toFixed(1)
    : null;

  document.getElementById("kTotal").textContent = totalLog;
  document.getElementById("kAktif").textContent = mesinData.length;
  document.getElementById("kWarn").textContent = totalWarn;
  document.getElementById("kCrit").textContent = totalCrit;
  document.getElementById("kAvg").textContent =
    avgArus !== null ? `${avgArus} A` : "—";

  // Alert banner
  const banner = document.getElementById("alertBanner");
  if (totalCrit > 0) {
    const critMachines = mesinData
      .filter((m) => m.total_critical > 0)
      .map((m) => m.nama_mesin.replace(/_/g, " "))
      .join(", ");
    document.getElementById("alertText").textContent =
      `${totalCrit} CRITICAL terdeteksi pada: ${critMachines}`;
    banner.style.display = "flex";
  } else {
    banner.style.display = "none";
  }
}

// ── FETCH LOGS ────────────────────────────────────────────
async function fetchLogs() {
  const mesin = document.getElementById("filterMesin").value;
  const status = document.getElementById("filterStatus").value;
  let url = `${API_BASE}/logs?limit=${LOG_LIMIT}`;
  if (mesin) url += `&nama_mesin=${encodeURIComponent(mesin)}`;
  if (status) url += `&status=${encodeURIComponent(status)}`;

  try {
    const res = await fetch(url);
    const json = await res.json();
    const rows = json.data || [];
    const tbody = document.getElementById("logBody");

    if (!rows.length) {
      tbody.innerHTML = `<tr><td colspan="5" class="empty-cell">Belum ada log</td></tr>`;
      return [];
    }

    tbody.innerHTML = rows
      .map((r) => {
        const c = statusClass(r.status_mesin);
        const pct = Math.min(parseFloat(r.nilai_arus) / 25, 1);
        return `<tr>
        <td class="txt-muted">${fmtDateTime(r.waktu_simpan)}</td>
        <td style="font-weight:500">${r.nama_mesin.replace(/_/g, " ")}</td>
        <td class="txt-${c}">${parseFloat(r.nilai_arus).toFixed(2)} A</td>
        <td>${badge(r.status_mesin)}</td>
        <td><div class="bar-wrap"><div class="bar-fill bar-${c}" style="width:${(pct * 100).toFixed(0)}%"></div></div></td>
      </tr>`;
      })
      .join("");

    return rows;
  } catch {
    document.getElementById("logBody").innerHTML =
      `<tr><td colspan="5" class="empty-cell">Gagal memuat log</td></tr>`;
    return [];
  }
}

// ── FETCH MESIN LIST (untuk dropdown filter) ──────────────
async function fetchMesinList() {
  try {
    const res = await fetch(`${API_BASE}/mesin`);
    const json = await res.json();
    const sel = document.getElementById("filterMesin");
    (json.data || []).forEach((m) => {
      if (!sel.querySelector(`option[value="${m.nama_mesin}"]`)) {
        const opt = document.createElement("option");
        opt.value = m.nama_mesin;
        opt.textContent = m.nama_mesin.replace(/_/g, " ");
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
    // Satu endpoint /mesin/status menggantikan /statistik untuk gauge + stat tabel
    const [mesinRes, _] = await Promise.all([
      fetch(`${API_BASE}/mesin/status`),
      fetchLogs(),
    ]);

    const mesinJson = await mesinRes.json();
    const mesinData = mesinJson.data || [];

    renderKPI(mesinData);
    renderGauges(mesinData);
    renderStatistik(mesinData);

    const now = new Date();
    document.getElementById("lastUpdate").textContent =
      `Update: ${fmtTime(now)}`;
    document.getElementById("footerUpdate").textContent =
      `Terakhir update: ${now.toLocaleTimeString("id-ID")}`;

    setConnected(true);
  } catch (e) {
    setConnected(false);
  }
}

// ── INIT ─────────────────────────────────────────────────
(async function init() {
  applyTheme();
  document.getElementById("footerApi").textContent = API_BASE;
  await fetchMesinList();
  await fetchAll();
  setInterval(fetchAll, REFRESH_INTERVAL);
})();
