// State
let priceChart = null;
let currentDays = 7;
let currentPage = 0;
const pageSize = 20;
let routeColors = {
    "HYD-PNQ": { border: "#38bdf8", bg: "rgba(56, 189, 248, 0.1)" },
    "PNQ-HYD": { border: "#a855f7", bg: "rgba(168, 85, 247, 0.1)" },
    "BOM-HYD": { border: "#f59e0b", bg: "rgba(245, 158, 11, 0.1)" },
    "HYD-BOM": { border: "#10b981", bg: "rgba(16, 185, 129, 0.1)" },
};

let rawChartData = null;
let allLogsData = [];

// Initialize on DOM load
document.addEventListener("DOMContentLoaded", () => {
    initChart();
    loadDashboard();
    
    // Auto-refresh every 20 seconds
    setInterval(loadStatus, 20000);
});

// Format Indian Rupee currency
function formatINR(val) {
    if (val === null || val === undefined) return "N/A";
    return "₹" + Number(val).toLocaleString("en-IN");
}

// Format duration minutes to "1h 25m"
function formatDuration(mins) {
    if (!mins) return "-";
    const h = Math.floor(mins / 60);
    const m = mins % 60;
    return h > 0 ? `${h}h ${m > 0 ? m + 'm' : ''}` : `${m}m`;
}

// Format Airline Badge Class
function getAirlineBadgeClass(airline) {
    const name = (airline || "").toLowerCase();
    if (name.includes("indigo")) return "airline-badge-indigo";
    if (name.includes("air india")) return "airline-badge-airindia";
    if (name.includes("alliance")) return "airline-badge-alliance";
    if (name.includes("akasa")) return "airline-badge-akasa";
    if (name.includes("spicejet")) return "airline-badge-spicejet";
    return "airline-badge-default";
}

// Load full dashboard data
async function loadDashboard() {
    await Promise.all([
        loadStatus(),
        loadRoutes(),
        loadChartData(),
        loadStats(),
        loadLogs(0)
    ]);
}

// Load System & BrightData Status
async function loadStatus() {
    try {
        const res = await fetch("/api/status");
        const data = await res.json();

        // Update BrightData indicator
        const bdPill = document.getElementById("brightDataPill");
        const bdDot = document.getElementById("bdDot");
        const bdText = document.getElementById("bdText");

        if (data.brightdata && data.brightdata.active) {
            bdPill.className = "flex items-center gap-2 px-3 py-1 rounded-full text-xs font-medium border bg-emerald-500/10 border-emerald-500/30 text-emerald-300";
            bdDot.className = "h-2 w-2 rounded-full bg-emerald-400";
            bdText.textContent = `BrightData Protected (${data.brightdata.zone || data.brightdata.mode})`;
        } else {
            bdPill.className = "flex items-center gap-2 px-3 py-1 rounded-full text-xs font-medium border bg-amber-500/10 border-amber-500/30 text-amber-300";
            bdDot.className = "h-2 w-2 rounded-full bg-amber-400";
            bdText.textContent = "Direct Mode (No BrightData Key)";
        }

        // Update Trigger Button State
        const btn = document.getElementById("triggerBtn");
        const icon = document.getElementById("triggerIcon");
        const label = document.getElementById("triggerLabel");

        if (data.is_scraping) {
            btn.disabled = true;
            icon.classList.add("animate-spin");
            label.textContent = "Scraping...";
        } else {
            btn.disabled = false;
            icon.classList.remove("animate-spin");
            label.textContent = "Check Now";
        }

        // Update Next Run Timer
        if (data.next_run_at) {
            const nextTime = new Date(data.next_run_at);
            const now = new Date();
            const diffMins = Math.max(0, Math.round((nextTime - now) / 60000));
            document.getElementById("nextCheckTimer").textContent = `in ~${diffMins} min${diffMins === 1 ? '' : 's'}`;
        } else {
            document.getElementById("nextCheckTimer").textContent = "Idle";
        }

    } catch (err) {
        console.error("Failed to load status:", err);
    }
}

// Load Route Cards
async function loadRoutes() {
    try {
        const res = await fetch("/api/routes");
        const routes = await res.json();
        const grid = document.getElementById("routesGrid");
        grid.innerHTML = "";

        routes.forEach(r => {
            const latest = r.latest;
            const hasData = !!latest;
            const diff = r.price_diff_vs_previous;
            let trendHtml = "";

            if (diff !== null && diff !== undefined) {
                if (diff < 0) {
                    trendHtml = `<span class="text-xs text-emerald-400 flex items-center font-medium">↓ ${formatINR(Math.abs(diff))} drop</span>`;
                } else if (diff > 0) {
                    trendHtml = `<span class="text-xs text-rose-400 flex items-center font-medium">↑ +${formatINR(diff)} rise</span>`;
                } else {
                    trendHtml = `<span class="text-xs text-slate-400">No change</span>`;
                }
            }

            const card = document.createElement("div");
            card.className = "rounded-xl border border-darkBorder bg-darkCard/70 p-5 shadow-lg hover:border-slate-600 transition-all flex flex-col justify-between";

            card.innerHTML = `
                <div>
                    <div class="flex items-center justify-between mb-2">
                        <span class="text-xs font-mono font-semibold px-2 py-0.5 rounded bg-slate-800 text-sky-400 border border-darkBorder">${r.code}</span>
                        ${trendHtml}
                    </div>
                    <div class="flex items-center gap-1.5 font-semibold text-white text-sm mb-3">
                        <span>${r.origin}</span>
                        <i data-lucide="arrow-right" class="w-3.5 h-3.5 text-slate-400"></i>
                        <span>${r.destination}</span>
                    </div>

                    ${hasData ? `
                        <div class="space-y-2">
                            <div class="flex items-baseline justify-between">
                                <span class="text-2xl font-bold tracking-tight text-white">${formatINR(latest.price)}</span>
                                <span class="text-[11px] px-2 py-0.5 rounded font-medium ${getAirlineBadgeClass(latest.airline)}">
                                    ${latest.airline}
                                </span>
                            </div>

                            <div class="text-xs text-slate-400 flex items-center justify-between pt-1 border-t border-darkBorder/40">
                                <span class="flex items-center gap-1">
                                    <i data-lucide="clock" class="w-3 h-3 text-slate-500"></i>
                                    ${latest.departure_time} → ${latest.arrival_time}
                                </span>
                                <span>${formatDuration(latest.duration_minutes)}</span>
                            </div>
                        </div>
                    ` : `
                        <div class="py-4 text-center text-xs text-slate-500">
                            No price logged yet.<br>Click "Check Now" to fetch.
                        </div>
                    `}
                </div>

                <div class="mt-4 pt-3 border-t border-darkBorder/60 flex items-center justify-between text-[11px] text-slate-400">
                    <span>Low: <strong class="text-emerald-400 font-semibold">${formatINR(r.lowest_ever_price)}</strong></span>
                    <span>${hasData ? new Date(latest.scrape_timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '-'}</span>
                </div>
            `;

            grid.appendChild(card);
        });

        lucide.createIcons();
    } catch (err) {
        console.error("Failed to load routes:", err);
    }
}

// Initialize Chart.js
function initChart() {
    const ctx = document.getElementById("priceHistoryChart").getContext("2d");

    priceChart = new Chart(ctx, {
        type: "line",
        data: {
            datasets: []
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: "nearest",
                intersect: false,
            },
            scales: {
                x: {
                    type: "time",
                    time: {
                        unit: "hour",
                        tooltipFormat: "MMM d, HH:mm",
                        displayFormats: {
                            hour: "MMM d, HH:mm",
                            day: "MMM d"
                        }
                    },
                    grid: {
                        color: "rgba(255, 255, 255, 0.05)"
                    },
                    ticks: {
                        color: "#94a3b8",
                        font: { size: 11 }
                    }
                },
                y: {
                    grid: {
                        color: "rgba(255, 255, 255, 0.05)"
                    },
                    ticks: {
                        color: "#94a3b8",
                        font: { size: 11 },
                        callback: function(value) {
                            return "₹" + value.toLocaleString("en-IN");
                        }
                    }
                }
            },
            plugins: {
                legend: {
                    position: "top",
                    labels: {
                        color: "#e2e8f0",
                        font: { size: 12, weight: 500 },
                        usePointStyle: true,
                        pointStyle: "circle"
                    }
                },
                tooltip: {
                    backgroundColor: "#111827",
                    borderColor: "#334155",
                    borderWidth: 1,
                    titleColor: "#f8fafc",
                    bodyColor: "#cbd5e1",
                    padding: 10,
                    callbacks: {
                        label: function(context) {
                            const raw = context.raw;
                            return ` ₹${raw.y.toLocaleString('en-IN')} (${raw.airline} ${raw.departure_time || ''})`;
                        }
                    }
                }
            }
        }
    });
}

// Load and Render Price Chart
async function loadChartData() {
    try {
        const res = await fetch(`/api/history?days=${currentDays}`);
        rawChartData = await res.json();
        renderPriceChart();
    } catch (err) {
        console.error("Failed to load chart data:", err);
    }
}

function renderPriceChart() {
    if (!rawChartData || !priceChart) return;

    const selectedFilter = document.getElementById("graphRouteFilter").value;
    const datasets = [];

    for (const [routeCode, items] of Object.entries(rawChartData.routes)) {
        if (selectedFilter !== "all" && selectedFilter !== routeCode) {
            continue;
        }

        const color = routeColors[routeCode] || { border: "#38bdf8", bg: "rgba(56, 189, 248, 0.1)" };

        const points = items.map(pt => ({
            x: new Date(pt.timestamp),
            y: pt.price,
            airline: pt.airline,
            departure_time: pt.departure_time,
            flight_date: pt.flight_date,
            flight_number: pt.flight_number
        }));

        datasets.push({
            label: routeCode,
            data: points,
            borderColor: color.border,
            backgroundColor: color.bg,
            borderWidth: 2.5,
            tension: 0.3,
            fill: false,
            pointRadius: 4,
            pointHoverRadius: 6,
            pointBackgroundColor: color.border
        });
    }

    priceChart.data.datasets = datasets;
    priceChart.update();
}

function setTimeRange(days) {
    currentDays = days;
    [1, 3, 7, 30].forEach(d => {
        const btn = document.getElementById(`btnRange${d}`);
        if (btn) {
            if (d === days) {
                btn.className = "px-2.5 py-1 rounded-md bg-sky-600 text-white font-medium shadow-sm transition";
            } else {
                btn.className = "px-2.5 py-1 rounded-md text-slate-400 hover:text-white transition";
            }
        }
    });
    loadChartData();
}

// Load Stats Section
async function loadStats() {
    try {
        const res = await fetch("/api/stats");
        const stats = await res.json();
        const grid = document.getElementById("statsGrid");
        grid.innerHTML = "";

        stats.forEach(s => {
            const card = document.createElement("div");
            card.className = "rounded-xl border border-darkBorder bg-darkCard/60 p-4";
            card.innerHTML = `
                <div class="flex items-center justify-between text-xs text-slate-400 mb-1">
                    <span>${s.route_code}</span>
                    <span class="text-[10px] px-1.5 py-0.5 rounded bg-slate-800">${s.total_checks} logs</span>
                </div>
                <div class="text-xl font-bold text-white mb-2">
                    ${formatINR(s.min_price)} <span class="text-xs font-normal text-slate-400">low</span>
                </div>
                <div class="flex justify-between text-[11px] text-slate-400 border-t border-darkBorder/40 pt-2">
                    <span>Avg: <strong class="text-slate-200">${formatINR(s.avg_price)}</strong></span>
                    <span>Top: <strong class="text-sky-400">${s.most_common_airline}</strong></span>
                </div>
            `;
            grid.appendChild(card);
        });
    } catch (err) {
        console.error("Failed to load stats:", err);
    }
}

// Load Detailed Flight Logs Table
async function loadLogs(page = 0) {
    currentPage = page;
    const routeFilter = document.getElementById("tableRouteFilter").value;
    const offset = page * pageSize;

    try {
        const url = `/api/logs?limit=${pageSize}&offset=${offset}${routeFilter ? '&route_code=' + routeFilter : ''}`;
        const res = await fetch(url);
        const data = await res.json();
        allLogsData = data.items;

        const tbody = document.getElementById("logsTableBody");
        tbody.innerHTML = "";

        if (data.items.length === 0) {
            tbody.innerHTML = `<tr><td colspan="7" class="px-6 py-8 text-center text-slate-500">No logs found matching criteria.</td></tr>`;
            document.getElementById("paginationInfo").textContent = "Showing 0 of 0 logs";
            document.getElementById("prevPageBtn").disabled = true;
            document.getElementById("nextPageBtn").disabled = true;
            return;
        }

        data.items.forEach(log => {
            const row = document.createElement("tr");
            row.className = "hover:bg-slate-800/40 transition";

            const scrapeDate = new Date(log.scrape_timestamp).toLocaleString([], {
                month: "short", day: "numeric", hour: "2-digit", minute: "2-digit"
            });

            row.innerHTML = `
                <td class="px-6 py-4 whitespace-nowrap text-xs text-slate-400">${scrapeDate}</td>
                <td class="px-6 py-4 whitespace-nowrap">
                    <span class="font-mono text-xs font-semibold px-2 py-0.5 rounded bg-slate-800 text-sky-400 border border-darkBorder">${log.route_code}</span>
                </td>
                <td class="px-6 py-4 whitespace-nowrap text-xs">
                    <div class="text-slate-200 font-medium">${log.flight_date}</div>
                    <div class="text-slate-400 text-[11px]">${log.day_of_week}</div>
                </td>
                <td class="px-6 py-4 whitespace-nowrap text-xs">
                    <span class="px-2 py-0.5 rounded font-medium ${getAirlineBadgeClass(log.airline)}">${log.airline}</span>
                    ${log.flight_number ? `<span class="ml-1 text-[11px] text-slate-400">${log.flight_number}</span>` : ''}
                </td>
                <td class="px-6 py-4 whitespace-nowrap text-xs text-slate-300">
                    <div>${log.departure_time} → ${log.arrival_time}</div>
                    <div class="text-[11px] text-slate-400">${formatDuration(log.duration_minutes)} • ${log.stops === 0 ? 'Non-stop' : log.stops + ' stop(s)'}</div>
                </td>
                <td class="px-6 py-4 whitespace-nowrap">
                    <span class="text-sm font-bold text-white">${formatINR(log.price)}</span>
                </td>
                <td class="px-6 py-4 whitespace-nowrap text-xs">
                    <button onclick="viewOptions(${log.id})" class="px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-sky-400 text-xs font-medium border border-darkBorder transition flex items-center gap-1">
                        <span>${log.total_options_found} flights</span>
                        <i data-lucide="chevron-right" class="w-3 h-3"></i>
                    </button>
                </td>
            `;

            tbody.appendChild(row);
        });

        // Update pagination
        const total = data.total;
        const start = offset + 1;
        const end = Math.min(offset + pageSize, total);
        document.getElementById("paginationInfo").textContent = `Showing ${start}–${end} of ${total} logs`;
        document.getElementById("prevPageBtn").disabled = page <= 0;
        document.getElementById("nextPageBtn").disabled = end >= total;

        lucide.createIcons();
    } catch (err) {
        console.error("Failed to load logs:", err);
    }
}

function changePage(delta) {
    loadLogs(currentPage + delta);
}

// Trigger Scrape Manually
async function triggerScrape() {
    const btn = document.getElementById("triggerBtn");
    const icon = document.getElementById("triggerIcon");
    const label = document.getElementById("triggerLabel");

    btn.disabled = true;
    icon.classList.add("animate-spin");
    label.textContent = "Starting...";

    try {
        const res = await fetch("/api/scrape/trigger", { method: "POST" });
        const data = await res.json();
        
        // Poll status every 2 seconds until scraping is done
        const checkInterval = setInterval(async () => {
            const statusRes = await fetch("/api/status");
            const statusData = await statusRes.json();
            if (!statusData.is_scraping) {
                clearInterval(checkInterval);
                await loadDashboard();
            }
        }, 2000);
    } catch (err) {
        console.error("Error triggering scrape:", err);
        btn.disabled = false;
        icon.classList.remove("animate-spin");
        label.textContent = "Check Now";
    }
}

// Modal: View all flight options for a log entry
function viewOptions(logId) {
    const log = allLogsData.find(l => l.id === logId);
    if (!log) return;

    document.getElementById("modalTitle").textContent = `${log.route_code} — Options on ${log.flight_date} (${log.day_of_week})`;
    const list = document.getElementById("modalFlightList");
    list.innerHTML = "";

    const allFlights = log.all_flights || [];

    if (allFlights.length === 0) {
        list.innerHTML = `<div class="text-center text-slate-500 py-6 text-xs">No additional flight breakdown available for this log.</div>`;
    } else {
        // Sort lowest price first
        allFlights.sort((a, b) => a.price - b.price);

        allFlights.forEach((fl, idx) => {
            const isLowest = idx === 0;
            const item = document.createElement("div");
            item.className = `p-3 rounded-xl border ${isLowest ? 'border-sky-500/50 bg-sky-500/5' : 'border-darkBorder bg-slate-900/40'} flex items-center justify-between text-xs`;

            item.innerHTML = `
                <div class="flex items-center gap-3">
                    <span class="px-2 py-0.5 rounded font-medium ${getAirlineBadgeClass(fl.airline)}">${fl.airline}</span>
                    <div>
                        <div class="text-slate-200 font-medium">${fl.departure_time} → ${fl.arrival_time}</div>
                        <div class="text-[11px] text-slate-400">${formatDuration(fl.duration_minutes)} • ${fl.stops === 0 ? 'Non-stop' : fl.stops + ' stop(s)'} ${fl.plane_type ? '• ' + fl.plane_type : ''}</div>
                    </div>
                </div>
                <div class="text-right">
                    <div class="text-sm font-bold ${isLowest ? 'text-emerald-400' : 'text-white'}">${formatINR(fl.price)}</div>
                    ${isLowest ? '<span class="text-[10px] text-emerald-400 font-medium">Cheapest</span>' : ''}
                </div>
            `;
            list.appendChild(item);
        });
    }

    document.getElementById("detailsModal").classList.remove("hidden");
    lucide.createIcons();
}

function closeModal() {
    document.getElementById("detailsModal").classList.add("hidden");
}
