// Dashboard page — one fetch of GET /api/dashboard/insights, ten chart sections
// rendered from the precomputed payload. No per-chart fetching, no client-side
// aggregation: the payload arrives pre-shaped (see aggregations.md).
//
// While the database is empty the endpoint 404s; the page then offers a
// "sample data" mode that renders every chart against a synthetic payload
// (src/pages/dashboard.sample.js) so the visuals can be verified.

import {
  Chart,
  BarController,
  BarElement,
  DoughnutController,
  ArcElement,
  ScatterController,
  PointElement,
  CategoryScale,
  LinearScale,
  Tooltip,
  Legend,
} from 'chart.js';

import { getDashboardInsights } from '../api.js';
import { humanize, percent, relativeTime, isStale } from '../format.js';
import { createCloseRateBarChart } from '../components/closeRateBarChart.js';
import { renderHeatmap } from '../components/heatmap.js';
import { buildSampleInsights } from './dashboard.sample.js';

Chart.register(
  BarController,
  BarElement,
  DoughnutController,
  ArcElement,
  ScatterController,
  PointElement,
  CategoryScale,
  LinearScale,
  Tooltip,
  Legend
);

Chart.defaults.color = '#9aa2ad';
Chart.defaults.borderColor = '#2a2f3a';
Chart.defaults.font.family = 'system-ui, sans-serif';

const ACCENT = '#6d8bff';
const PALETTE = [
  '#6d8bff', '#3fb668', '#e0a83d', '#e05d5d', '#9b7fe0',
  '#43b7c2', '#d67ab0', '#8a94a6', '#c2803a', '#5ec27a',
];

// --- Chart-by-chart rendering guide (aggregations.md §"Chart-by-chart") ---
// Each spec: which payload key it reads, its card title, whether it spans the
// full grid width, and a render(container, data) -> cleanup|null function.
const SPECS = [
  {
    key: 'close_rate_by_sector',
    title: 'Close rate by sector',
    render: (el, d) => createCloseRateBarChart(canvasIn(el, 'tall'), d),
  },
  {
    key: 'close_rate_by_business_model',
    title: 'Close rate by business model',
    render: (el, d) => createCloseRateBarChart(canvasIn(el), d),
  },
  {
    key: 'close_rate_by_business_size',
    title: 'Close rate by business size',
    render: (el, d) => createCloseRateBarChart(canvasIn(el), d),
  },
  {
    key: 'needs_frequency',
    title: 'Most requested client needs',
    wide: true,
    render: renderNeedsFrequency,
  },
  {
    key: 'discovery_channel_frequency',
    title: 'How clients discovered Vambe',
    render: (el, d) => countBar(canvasIn(el), d, 'channel'),
  },
  {
    key: 'current_channel_frequency',
    title: "Clients' current support channels",
    render: (el, d) => countDoughnut(canvasIn(el), d, 'channel'),
  },
  {
    key: 'rep_performance',
    title: 'Sales rep performance',
    render: (el, d) => createCloseRateBarChart(canvasIn(el, 'tall'), d),
  },
  {
    key: 'rep_performance_by_sector',
    title: 'Rep specialization — close rate by sector',
    wide: true,
    render: (el, d) =>
      renderHeatmap(el, d, {
        rowKey: 'rep',
        colKey: 'sector',
        valueKey: 'close_rate',
        format: (v) => (v ? percent(v) : ''),
      }),
  },
  {
    key: 'close_rate_by_urgency',
    title: 'Close rate by pain-point urgency',
    render: (el, d) =>
      createCloseRateBarChart(canvasIn(el), d, { order: ['low', 'medium', 'high', 'unclear'] }),
  },
  {
    key: 'close_rate_by_needs_complexity',
    title: 'Close rate by needs complexity',
    render: (el, d) =>
      createCloseRateBarChart(canvasIn(el), d, { order: ['0', '1-2', '3-4', '5+'] }),
  },
  {
    key: 'close_rate_by_discovery_channel',
    title: 'Discovery channel — volume vs. quality',
    wide: true,
    render: (el, d) => scatterVolumeQuality(canvasIn(el, 'tall'), d),
  },
  {
    key: 'sector_needs_matrix',
    title: 'Sector × client needs',
    wide: true,
    render: (el, d) => renderHeatmap(el, d, { rowKey: 'sector', colKey: 'need' }),
  },
  {
    key: 'close_rate_by_regulatory_flag',
    title: 'Close rate by regulatory sensitivity',
    render: (el, d) => createCloseRateBarChart(canvasIn(el), d),
  },
  {
    key: 'size_needs_matrix',
    title: 'Business size × client needs',
    wide: true,
    render: (el, d) => renderHeatmap(el, d, { rowKey: 'business_size', colKey: 'need' }),
  },
];

export function renderDashboardPage(mount) {
  const page = document.createElement('div');
  page.className = 'page';
  page.innerHTML = `
    <h1 class="page__title">Dashboard</h1>
    <p class="page__subtitle">Insights from LLM-enhanced transcripts.</p>
    <div id="dashboard-status" class="dashboard-status"></div>
    <div class="chart-grid" id="chart-grid"></div>
  `;
  mount.appendChild(page);

  const statusEl = page.querySelector('#dashboard-status');
  const grid = page.querySelector('#chart-grid');

  let cleanups = [];
  let disposed = false;

  function teardownCharts() {
    cleanups.forEach((fn) => {
      try {
        fn();
      } catch {
        /* chart already destroyed */
      }
    });
    cleanups = [];
  }

  function showSkeletons() {
    teardownCharts();
    statusEl.className = 'dashboard-status';
    statusEl.innerHTML = '<span class="skeleton skeleton--text"></span>';
    grid.innerHTML = SPECS.map(
      (s) => `
      <div class="chart-card${s.wide ? ' chart-card--wide' : ''}">
        <h3>${s.title}</h3>
        <div class="skeleton skeleton--block${s.wide ? ' skeleton--block-wide' : ''}"></div>
      </div>`
    ).join('');
  }

  function showMessage(kind, html) {
    teardownCharts();
    grid.innerHTML = '';
    statusEl.className = `dashboard-status dashboard-status--${kind}`;
    statusEl.innerHTML = html;
  }

  function renderCharts(payload, { sample }) {
    teardownCharts();

    if (sample) {
      statusEl.className = 'dashboard-status dashboard-status--sample';
      statusEl.innerHTML = `
        <span>Showing <strong>sample data</strong> — the dashboard is not connected to real transcripts yet.</span>
        <button class="btn btn--ghost btn--sm" data-action="live">Try live data</button>`;
      statusEl.querySelector('[data-action="live"]').addEventListener('click', () => load({ sample: false }));
    } else {
      const stale = isStale(payload.computed_at);
      statusEl.className = `dashboard-status${stale ? ' dashboard-status--warn' : ''}`;
      statusEl.innerHTML = `Data as of ${relativeTime(payload.computed_at)}${
        stale ? ' — this snapshot may be outdated' : ''
      }`;
    }

    grid.innerHTML = '';
    SPECS.forEach((spec) => {
      const card = document.createElement('div');
      card.className = 'chart-card' + (spec.wide ? ' chart-card--wide' : '');
      card.innerHTML = `<h3>${spec.title}</h3>`;
      grid.appendChild(card);

      const body = document.createElement('div');
      card.appendChild(body);

      const data = payload[spec.key];
      if (!Array.isArray(data) || data.length === 0) {
        body.innerHTML = '<div class="empty-note">Not enough data yet.</div>';
        return;
      }

      try {
        const cleanup = spec.render(body, data);
        if (typeof cleanup === 'function') cleanups.push(cleanup);
        else if (cleanup && typeof cleanup.destroy === 'function') cleanups.push(() => cleanup.destroy());
      } catch (err) {
        body.innerHTML = `<div class="empty-note">Could not render this chart: ${err.message}</div>`;
      }
    });
  }

  async function load({ sample }) {
    if (disposed) return;

    if (sample) {
      renderCharts(buildSampleInsights(), { sample: true });
      return;
    }

    showSkeletons();
    try {
      const payload = await getDashboardInsights();
      if (disposed) return;
      renderCharts(payload, { sample: false });
    } catch (err) {
      if (disposed) return;
      const noData = err.status === 404;
      showMessage(
        noData ? 'info' : 'error',
        `
        <span>${
          noData
            ? 'No insights computed yet — upload a CSV and let an enhancement job finish.'
            : `Could not load the dashboard: ${err.message}`
        }</span>
        <span class="dashboard-status__actions">
          ${noData ? '' : '<button class="btn btn--ghost btn--sm" data-action="retry">Retry</button>'}
          <button class="btn btn--sm" data-action="sample">Preview with sample data</button>
        </span>`
      );
      const retry = statusEl.querySelector('[data-action="retry"]');
      if (retry) retry.addEventListener('click', () => load({ sample: false }));
      statusEl
        .querySelector('[data-action="sample"]')
        .addEventListener('click', () => load({ sample: true }));
    }
  }

  // DB is currently empty — start in sample mode so the charts are visible.
  // "Try live data" (shown in sample mode) switches to the real endpoint.
  load({ sample: true });

  return () => {
    disposed = true;
    teardownCharts();
  };
}

// --- Local chart builders (the non-reusable one-offs) ---

// Adds a canvas wrapper to a card body and returns the <canvas>.
function canvasIn(container, size) {
  const wrap = document.createElement('div');
  wrap.className = 'chart-card__canvas-wrap' + (size === 'tall' ? ' chart-card__canvas-wrap--tall' : '');
  const canvas = document.createElement('canvas');
  wrap.appendChild(canvas);
  container.appendChild(wrap);
  return canvas;
}

// Vertical bar of { <labelKey>, count } frequency rows (already sorted desc).
function countBar(canvas, rows, labelKey) {
  return new Chart(canvas.getContext('2d'), {
    type: 'bar',
    data: {
      labels: rows.map((r) => humanize(r[labelKey])),
      datasets: [{ label: 'Mentions', data: rows.map((r) => r.count), backgroundColor: ACCENT, borderRadius: 4 }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: { y: { beginAtZero: true, ticks: { precision: 0 } } },
    },
  });
}

function countDoughnut(canvas, rows, labelKey) {
  return new Chart(canvas.getContext('2d'), {
    type: 'doughnut',
    data: {
      labels: rows.map((r) => humanize(r[labelKey])),
      datasets: [{ data: rows.map((r) => r.count), backgroundColor: PALETTE, borderWidth: 0 }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { position: 'right', labels: { boxWidth: 12 } } },
    },
  });
}

// Chart #7 — the one non-bar chart: total (x, volume) vs. close_rate (y, quality).
function scatterVolumeQuality(canvas, rows) {
  return new Chart(canvas.getContext('2d'), {
    type: 'scatter',
    data: {
      datasets: [
        {
          label: 'Discovery channel',
          data: rows.map((r) => ({ x: r.total, y: r.close_rate, label: humanize(r.group) })),
          backgroundColor: ACCENT,
          pointRadius: 6,
          pointHoverRadius: 8,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => `${ctx.raw.label}: ${percent(ctx.raw.y, 1)} close · ${ctx.raw.x} deals`,
          },
        },
      },
      scales: {
        x: { title: { display: true, text: 'Volume (total deals)' }, beginAtZero: true },
        y: {
          title: { display: true, text: 'Close rate' },
          beginAtZero: true,
          suggestedMax: 1,
          ticks: { callback: (v) => percent(v) },
        },
      },
    },
  });
}

// Chart #2 — long list (15 needs); default to top 8 with a "show all" toggle.
function renderNeedsFrequency(container, data) {
  const TOP = 8;
  let showAll = false;
  let chart = null;

  const canvas = canvasIn(container, 'tall');

  let toggle = null;
  if (data.length > TOP) {
    toggle = document.createElement('button');
    toggle.className = 'btn btn--ghost btn--sm';
    toggle.style.marginTop = '10px';
    container.appendChild(toggle);
    toggle.addEventListener('click', () => {
      showAll = !showAll;
      draw();
    });
  }

  function draw() {
    if (chart) chart.destroy();
    const rows = showAll ? data : data.slice(0, TOP);
    chart = new Chart(canvas.getContext('2d'), {
      type: 'bar',
      data: {
        labels: rows.map((r) => humanize(r.need)),
        datasets: [
          { label: 'Mentions', data: rows.map((r) => r.count), backgroundColor: ACCENT, borderRadius: 4 },
        ],
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: { x: { beginAtZero: true, ticks: { precision: 0 } } },
      },
    });
    if (toggle) toggle.textContent = showAll ? 'Show top 8' : `Show all ${data.length}`;
  }

  draw();
  return () => chart && chart.destroy();
}
