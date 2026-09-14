// ══════════════════════════════════════════════════════════════
//  AeroTrack — Frontend Application Logic
// ══════════════════════════════════════════════════════════════

/* ── State ── */
let chart = null;
let currentDays = 7;
let currentPage = 0;
const PAGE_SIZE = 20;
let allLogsCache = [];
let rawHistory = null;

const ROUTE_COLORS = {
  'HYD-PNQ': { line: '#38bdf8', fill: 'rgba(56,189,248,0.08)', label: 'HYD→PNQ' },
  'PNQ-HYD': { line: '#a78bfa', fill: 'rgba(167,139,250,0.08)', label: 'PNQ→HYD' },
  'BOM-HYD': { line: '#fbbf24', fill: 'rgba(251,191,36,0.08)',  label: 'BOM→HYD' },
  'HYD-BOM': { line: '#34d399', fill: 'rgba(52,211,153,0.08)',  label: 'HYD→BOM' },
};

/* ══════════════════════════════════════════════════════════════
   INIT
══════════════════════════════════════════════════════════════ */
document.addEventListener('DOMContentLoaded', () => {
  initChart();
  loadAll();
  setInterval(loadStatus, 15000);
});

async function loadAll() {
  await Promise.all([
    loadStatus(),
    loadRoutes(),
    loadHistory(),
    loadStats(),
    loadLogs(0),
  ]);
}

/* ══════════════════════════════════════════════════════════════
   TABS
══════════════════════════════════════════════════════════════ */
function showTab(name) {
  ['dashboard','logs','stats'].forEach(t => {
    document.getElementById(`tab-content-${t}`).classList.toggle('hidden', t !== name);
    document.getElementById(`tab-${t}`).classList.toggle('active', t === name);
  });
}

/* ══════════════════════════════════════════════════════════════
   FORMATTERS
══════════════════════════════════════════════════════════════ */
function inr(v)   { return v != null ? '₹' + Number(v).toLocaleString('en-IN') : '—'; }
function dur(m)   { if (!m) return '—'; const h = Math.floor(m/60), r = m%60; return h ? `${h}h ${r ? r+'m':''}`.trim() : `${r}m`; }
function fmtTime(ts) {
  return new Date(ts).toLocaleString('en-IN', { month:'short', day:'numeric', hour:'2-digit', minute:'2-digit', hour12:true });
}

function airlineBadge(name) {
  const n = (name||'').toLowerCase();
  if (n.includes('indigo'))    return `<span class="badge badge-indigo">✈ ${name}</span>`;
  if (n.includes('air india')) return `<span class="badge badge-air">✈ ${name}</span>`;
  if (n.includes('akasa'))     return `<span class="badge badge-akasa">✈ ${name}</span>`;
  if (n.includes('spicejet'))  return `<span class="badge badge-spice">✈ ${name}</span>`;
  if (n.includes('vistara'))   return `<span class="badge badge-vistara">✈ ${name}</span>`;
  return `<span class="badge badge-default">✈ ${name||'Unknown'}</span>`;
}

function diffChip(d) {
  if (d == null) return '';
  if (d < 0) return `<span class="chip-drop">↓ ${inr(Math.abs(d))}</span>`;
  if (d > 0) return `<span class="chip-rise">↑ +${inr(d)}</span>`;
  return `<span class="chip-flat">→ No change</span>`;
}

/* ══════════════════════════════════════════════════════════════
   STATUS
══════════════════════════════════════════════════════════════ */
async function loadStatus() {
  try {
    const d = await fetch('/api/status').then(r => r.json());

    /* BrightData badge */
    const bd = document.getElementById('bdBadge');
    const dot = document.getElementById('bdDot');
    const lbl = document.getElementById('bdLabel');
    bd.classList.remove('hidden');
    if (d.brightdata?.active) {
      dot.className = 'w-1.5 h-1.5 rounded-full bg-emerald-400';
      lbl.textContent = `BrightData · ${d.brightdata.zone || d.brightdata.mode}`;
      bd.className = 'hidden sm:flex items-center gap-1.5 text-[11px] font-medium px-3 py-1 rounded-full border bg-emerald-500/10 border-emerald-500/25 text-emerald-300';
    } else {
      dot.className = 'w-1.5 h-1.5 rounded-full bg-yellow-400 animate-pulse-slow';
      lbl.textContent = 'Direct Mode';
      bd.className = 'hidden sm:flex items-center gap-1.5 text-[11px] font-medium px-3 py-1 rounded-full border bg-yellow-500/10 border-yellow-500/25 text-yellow-300';
    }

    /* Trigger button */
    const btn = document.getElementById('triggerBtn');
    const icon = document.getElementById('triggerIcon');
    const lbtn = document.getElementById('triggerLabel');
    if (d.is_scraping) {
      btn.disabled = true;
      icon.classList.add('spin');
      lbtn.textContent = 'Scraping…';
    } else {
      btn.disabled = false;
      icon.classList.remove('spin');
      lbtn.textContent = 'Refresh';
    }

    /* Next check countdown */
    if (d.next_run_at) {
      const diff = Math.max(0, Math.round((new Date(d.next_run_at) - Date.now()) / 60000));
      document.getElementById('nextCheck').textContent = `~${diff}m`;
    }
  } catch {}
}

/* ══════════════════════════════════════════════════════════════
   HERO STRIP (stat cards at top)
══════════════════════════════════════════════════════════════ */
async function buildHeroStrip(routes) {
  const strip = document.getElementById('heroStrip');
  const totalChecks = routes.reduce((a, r) => {
    // We'll fetch stats separately, just show route count for now
    return a;
  }, 0);

  // Pull latest scrape summary from /api/status
  let statusData = {};
  try { statusData = await fetch('/api/status').then(r => r.json()); } catch {}

  const lowestAll = routes
    .filter(r => r.lowest_ever_price)
    .sort((a, b) => a.lowest_ever_price - b.lowest_ever_price)[0];

  const cards = [
    {
      label: 'Routes Monitored',
      value: routes.length,
      sub: 'active tracking',
      icon: '🛣️',
      accent: '#38bdf8',
    },
    {
      label: 'Total Records',
      value: statusData.total_records?.toLocaleString() || '—',
      sub: 'price data points',
      icon: '📊',
      accent: '#a78bfa',
    },
    {
      label: 'Cheapest Ever',
      value: lowestAll ? inr(lowestAll.lowest_ever_price) : '—',
      sub: lowestAll ? lowestAll.code : '—',
      icon: '💸',
      accent: '#34d399',
    },
    {
      label: 'Scrape Interval',
      value: `${statusData.check_interval_minutes || 60} min`,
      sub: statusData.is_scraping ? '🔄 scanning now…' : 'auto-scheduled',
      icon: '⏱️',
      accent: '#fbbf24',
    },
  ];

  strip.innerHTML = cards.map(c => `
    <div class="stat-card flex items-center gap-4">
      <div class="text-2xl select-none">${c.icon}</div>
      <div class="min-w-0">
        <div class="text-[11px] text-slate-500 truncate">${c.label}</div>
        <div class="text-lg font-bold text-white leading-tight">${c.value}</div>
        <div class="text-[11px] text-slate-500 truncate">${c.sub}</div>
      </div>
    </div>
  `).join('');
}

/* ══════════════════════════════════════════════════════════════
   ROUTE CARDS
══════════════════════════════════════════════════════════════ */
async function loadRoutes() {
  try {
    const routes = await fetch('/api/routes').then(r => r.json());
    await buildHeroStrip(routes);
    renderRouteCards(routes);
  } catch (e) {
    document.getElementById('routesGrid').innerHTML =
      `<div class="col-span-full text-center py-10 text-slate-500 text-sm">Failed to load routes: ${e.message}</div>`;
  }
}

function renderRouteCards(routes) {
  const grid = document.getElementById('routesGrid');
  const colors = {
    'HYD-PNQ': '#38bdf8',
    'PNQ-HYD': '#a78bfa',
    'BOM-HYD': '#fbbf24',
    'HYD-BOM': '#34d399',
  };

  grid.innerHTML = routes.map(r => {
    const L = r.latest;
    const c = colors[r.code] || '#3b82f6';

    return `
      <div class="route-card" style="--card-accent:${c}">
        <!-- Header row -->
        <div class="flex items-start justify-between mb-4">
          <div>
            <div class="text-[11px] text-slate-500 font-mono mb-1">${r.code}</div>
            <div class="flex items-center gap-1.5 text-sm font-semibold text-white">
              <span>${r.origin}</span>
              <svg class="w-3.5 h-3.5 text-slate-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
                <path d="M14 5l7 7-7 7M3 12h18" stroke-linecap="round" stroke-linejoin="round"/>
              </svg>
              <span>${r.destination}</span>
            </div>
          </div>
          ${L ? diffChip(r.price_diff_vs_previous) : ''}
        </div>

        <!-- Price block -->
        ${L ? `
          <div class="mb-4">
            <div class="text-2xl font-extrabold text-white tracking-tight">${inr(L.price)}</div>
            <div class="mt-1">${airlineBadge(L.airline)}</div>
          </div>

          <div class="space-y-1.5 text-[12px] text-slate-400">
            <div class="flex items-center justify-between">
              <span class="flex items-center gap-1">
                <svg class="w-3 h-3 text-slate-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                  <circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2" stroke-linecap="round"/>
                </svg>
                ${L.departure_time} → ${L.arrival_time}
              </span>
              <span class="text-slate-500">${dur(L.duration_minutes)}</span>
            </div>
            <div class="flex items-center justify-between">
              <span class="text-slate-500">${L.stops === 0 ? 'Non-stop' : `${L.stops} stop(s)`}</span>
              <span class="text-slate-600 text-[10px]">${fmtTime(L.scrape_timestamp)}</span>
            </div>
          </div>

          <div class="mt-4 pt-3 border-t border-border/60 flex items-center justify-between">
            <div class="text-[11px] text-slate-500">
              All-time low: <span class="text-emerald-400 font-semibold">${inr(r.lowest_ever_price)}</span>
            </div>
            <div class="w-2 h-2 rounded-full" style="background:${c}; box-shadow: 0 0 6px ${c};"></div>
          </div>
        ` : `
          <div class="py-8 text-center text-slate-600 text-xs">
            No data yet — click Refresh to fetch
          </div>
        `}
      </div>
    `;
  }).join('');
}

/* ══════════════════════════════════════════════════════════════
   CHART
══════════════════════════════════════════════════════════════ */
function initChart() {
  const ctx = document.getElementById('priceChart').getContext('2d');
  chart = new Chart(ctx, {
    type: 'line',
    data: { datasets: [] },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'nearest', intersect: false, axis: 'x' },
      scales: {
        x: {
          type: 'time',
          time: {
            unit: 'hour',
            tooltipFormat: 'MMM d, HH:mm',
            displayFormats: { hour: 'MMM d, HH:mm', day: 'MMM d' }
          },
          grid: { color: 'rgba(33,40,58,0.5)', drawBorder: false },
          ticks: { color: '#475569', font: { size: 11 }, maxTicksLimit: 8 }
        },
        y: {
          grid: { color: 'rgba(33,40,58,0.5)', drawBorder: false },
          ticks: {
            color: '#475569', font: { size: 11 },
            callback: v => '₹' + Number(v).toLocaleString('en-IN')
          }
        }
      },
      plugins: {
        legend: {
          position: 'top',
          labels: {
            color: '#94a3b8', font: { size: 12, weight: '500' },
            usePointStyle: true, pointStyle: 'circle', padding: 20
          }
        },
        tooltip: {
          backgroundColor: '#0d1117',
          borderColor: '#21283a',
          borderWidth: 1,
          titleColor: '#f1f5f9',
          bodyColor: '#94a3b8',
          padding: 12,
          callbacks: {
            label: ctx => {
              const r = ctx.raw;
              return ` ${inr(r.y)} · ${r.airline || ''} ${r.departure_time || ''}`;
            }
          }
        }
      }
    }
  });
}

async function loadHistory() {
  try {
    rawHistory = await fetch(`/api/history?days=${currentDays}`).then(r => r.json());
    renderChart();
  } catch {}
}

function renderChart() {
  if (!rawHistory || !chart) return;
  const filter = document.getElementById('graphRouteFilter').value;

  const datasets = Object.entries(rawHistory.routes)
    .filter(([code]) => filter === 'all' || filter === code)
    .map(([code, pts]) => {
      const c = ROUTE_COLORS[code] || { line: '#3b82f6', fill: 'rgba(59,130,246,0.08)', label: code };
      return {
        label: c.label,
        data: pts.map(p => ({
          x: new Date(p.timestamp),
          y: p.price,
          airline: p.airline,
          departure_time: p.departure_time,
        })),
        borderColor: c.line,
        backgroundColor: c.fill,
        borderWidth: 2,
        tension: 0.4,
        fill: true,
        pointRadius: 3,
        pointHoverRadius: 6,
        pointBackgroundColor: c.line,
        pointBorderColor: '#0d1117',
        pointBorderWidth: 2,
      };
    });

  chart.data.datasets = datasets;
  chart.update();
}

function setRange(d) {
  currentDays = d;
  [1,3,7,30].forEach(n => {
    const b = document.getElementById(`r${n}`);
    if (b) b.classList.toggle('active', n === d);
  });
  loadHistory();
}

/* ══════════════════════════════════════════════════════════════
   STATS
══════════════════════════════════════════════════════════════ */
async function loadStats() {
  try {
    const stats = await fetch('/api/stats').then(r => r.json());
    const colors = ['#38bdf8','#a78bfa','#fbbf24','#34d399'];
    document.getElementById('statsGrid').innerHTML = stats.map((s, i) => `
      <div class="glass-card rounded-2xl p-5 space-y-4">
        <div class="flex items-center justify-between">
          <div class="text-[11px] font-mono font-bold text-slate-500">${s.route_code}</div>
          <div class="text-[11px] px-2 py-0.5 rounded-full bg-surface-3 text-slate-500 border border-border">${s.total_checks} logs</div>
        </div>

        <div>
          <div class="text-2xl font-extrabold text-white">${inr(s.min_price)}</div>
          <div class="text-[11px] text-slate-500 mt-0.5">all-time lowest</div>
        </div>

        <div class="space-y-2 text-[12px]">
          <div class="flex justify-between items-center">
            <span class="text-slate-500">Average</span>
            <span class="font-semibold text-slate-200">${inr(s.avg_price)}</span>
          </div>
          <div class="flex justify-between items-center">
            <span class="text-slate-500">Highest seen</span>
            <span class="font-semibold text-rose-400">${inr(s.max_price)}</span>
          </div>
          <div class="flex justify-between items-center">
            <span class="text-slate-500">Top carrier</span>
            <span>${airlineBadge(s.most_common_airline)}</span>
          </div>
        </div>

        <!-- Mini progress bar: min vs max spread -->
        <div>
          <div class="flex justify-between text-[10px] text-slate-600 mb-1">
            <span>Price range</span>
            <span>${inr(s.min_price)} – ${inr(s.max_price)}</span>
          </div>
          <div class="h-1 rounded-full bg-surface-3 overflow-hidden">
            <div class="h-full rounded-full" style="width:${s.max_price ? Math.round((s.avg_price/s.max_price)*100) : 50}%; background:${colors[i]};"></div>
          </div>
        </div>
      </div>
    `).join('');
  } catch {}
}

/* ══════════════════════════════════════════════════════════════
   LOGS TABLE
══════════════════════════════════════════════════════════════ */
async function loadLogs(page = 0) {
  currentPage = page;
  const filter = document.getElementById('tableRouteFilter')?.value || '';
  const offset = page * PAGE_SIZE;

  document.getElementById('logsBody').innerHTML =
    `<tr><td colspan="7" class="px-5 py-10 text-center text-slate-600">Loading…</td></tr>`;

  try {
    const url = `/api/logs?limit=${PAGE_SIZE}&offset=${offset}${filter ? '&route_code=' + filter : ''}`;
    const d = await fetch(url).then(r => r.json());
    allLogsCache = d.items;

    const tbody = document.getElementById('logsBody');
    if (!d.items.length) {
      tbody.innerHTML = `<tr><td colspan="7" class="px-5 py-10 text-center text-slate-600 text-sm">No logs found.</td></tr>`;
      return;
    }

    tbody.innerHTML = d.items.map(log => `
      <tr class="transition-colors text-[13px]">
        <td class="px-5 py-3.5 text-slate-500 whitespace-nowrap">${fmtTime(log.scrape_timestamp)}</td>
        <td class="px-5 py-3.5">
          <span class="font-mono text-[11px] font-semibold text-sky-400 bg-sky-500/10 border border-sky-500/20 px-2 py-0.5 rounded">${log.route_code}</span>
        </td>
        <td class="px-5 py-3.5 whitespace-nowrap">
          <div class="text-slate-200 font-medium">${log.flight_date}</div>
          <div class="text-slate-600 text-[11px]">${log.day_of_week}</div>
        </td>
        <td class="px-5 py-3.5">${airlineBadge(log.airline)}</td>
        <td class="px-5 py-3.5 whitespace-nowrap text-[12px]">
          <div class="text-slate-200">${log.departure_time} → ${log.arrival_time}</div>
          <div class="text-slate-500">${dur(log.duration_minutes)} · ${log.stops === 0 ? 'Non-stop' : `${log.stops} stop`}</div>
        </td>
        <td class="px-5 py-3.5 text-right">
          <span class="text-base font-bold text-white">${inr(log.price)}</span>
        </td>
        <td class="px-5 py-3.5">
          <button onclick="viewOptions(${log.id})"
            class="flex items-center gap-1 text-[11px] px-2.5 py-1 rounded-lg border border-border bg-surface-2 hover:border-border-bright text-slate-400 hover:text-slate-200 transition">
            ${log.total_options_found} opts
            <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path d="M9 5l7 7-7 7" stroke-linecap="round"/></svg>
          </button>
        </td>
      </tr>
    `).join('');

    /* Pagination */
    const total = d.total;
    const end = Math.min(offset + PAGE_SIZE, total);
    document.getElementById('pageInfo').textContent = `${offset+1}–${end} of ${total}`;
    document.getElementById('prevBtn').disabled = page <= 0;
    document.getElementById('nextBtn').disabled = end >= total;
  } catch (e) {
    document.getElementById('logsBody').innerHTML =
      `<tr><td colspan="7" class="px-5 py-10 text-center text-rose-400 text-sm">Error: ${e.message}</td></tr>`;
  }
}

function changePage(d) { loadLogs(currentPage + d); }

/* ══════════════════════════════════════════════════════════════
   MODAL — All options for a log
══════════════════════════════════════════════════════════════ */
function viewOptions(id) {
  const log = allLogsCache.find(l => l.id === id);
  if (!log) return;

  document.getElementById('modalTitle').textContent = `${log.route_code} — All Flights`;
  document.getElementById('modalSub').textContent = `${log.flight_date} · ${log.day_of_week} · Scraped at ${fmtTime(log.scrape_timestamp)}`;

  const list = document.getElementById('modalList');
  const flights = (log.all_flights || []).sort((a, b) => a.price - b.price);

  if (!flights.length) {
    list.innerHTML = `<div class="text-center text-slate-600 py-8 text-xs">No flight breakdown available.</div>`;
  } else {
    list.innerHTML = flights.map((f, i) => `
      <div class="flight-option ${i === 0 ? 'cheapest' : ''}">
        <div class="flex items-center gap-3 min-w-0">
          ${airlineBadge(f.airline)}
          <div class="text-[12px] min-w-0">
            <div class="text-slate-200 font-medium">${f.departure_time} → ${f.arrival_time} <span class="text-slate-500 font-normal ml-1">${dur(f.duration_minutes)}</span></div>
            <div class="text-slate-500">${f.stops === 0 ? 'Non-stop' : `${f.stops} stop(s)`}${f.plane_type ? ' · '+f.plane_type : ''}</div>
          </div>
        </div>
        <div class="text-right flex-shrink-0">
          <div class="font-bold text-sm ${i === 0 ? 'text-emerald-400' : 'text-white'}">${inr(f.price)}</div>
          ${i === 0 ? '<div class="text-[10px] text-emerald-500 font-semibold">CHEAPEST</div>' : ''}
        </div>
      </div>
    `).join('');
  }

  document.getElementById('modal').style.display = 'flex';
}

function closeModal() { document.getElementById('modal').style.display = 'none'; }
document.getElementById('modal')?.addEventListener('click', e => {
  if (e.target === document.getElementById('modal')) closeModal();
});

/* ══════════════════════════════════════════════════════════════
   SCRAPE TRIGGER
══════════════════════════════════════════════════════════════ */
async function triggerScrape() {
  const btn = document.getElementById('triggerBtn');
  btn.disabled = true;
  document.getElementById('triggerIcon').classList.add('spin');
  document.getElementById('triggerLabel').textContent = 'Starting…';
  showToast('⚡', 'Scrape started — updating in background…', 'info');

  try {
    await fetch('/api/scrape/trigger', { method: 'POST' });
    const poll = setInterval(async () => {
      const s = await fetch('/api/status').then(r => r.json());
      if (!s.is_scraping) {
        clearInterval(poll);
        await loadAll();
        showToast('✅', 'Data refreshed successfully!', 'success');
      }
    }, 2500);
  } catch (e) {
    showToast('❌', 'Failed to trigger scrape.', 'error');
    btn.disabled = false;
    document.getElementById('triggerIcon').classList.remove('spin');
    document.getElementById('triggerLabel').textContent = 'Refresh';
  }
}

/* ══════════════════════════════════════════════════════════════
   TOAST
══════════════════════════════════════════════════════════════ */
let _toastTimeout;
function showToast(icon, msg, type = 'info') {
  const el = document.getElementById('toast');
  const inner = document.getElementById('toastInner');
  document.getElementById('toastIcon').textContent = icon;
  document.getElementById('toastMsg').textContent = msg;

  const colors = { success: 'border-emerald-500/30 bg-emerald-900/30', error: 'border-rose-500/30 bg-rose-900/30', info: 'border-blue-500/30 bg-blue-900/20' };
  inner.className = `flex items-center gap-3 px-4 py-3 rounded-xl border shadow-2xl text-sm font-medium backdrop-blur-md text-white ${colors[type] || colors.info}`;

  el.classList.remove('hidden');
  el.classList.add('toast-show');
  clearTimeout(_toastTimeout);
  _toastTimeout = setTimeout(() => {
    el.classList.add('toast-hide');
    setTimeout(() => { el.classList.add('hidden'); el.classList.remove('toast-show','toast-hide'); }, 300);
  }, 3500);
}
