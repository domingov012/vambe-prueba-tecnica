// Reusable horizontal bar chart for every "close rate by <dimension>" dataset.
// Contract shape: [{ group, total, closed, close_rate }]. Mirrors the backend's
// single `close_rate_by_dimension` aggregation — used for charts #1 (×3), #5,
// #6, #9.
//
// By default bars sort descending by close_rate. Pass `order` (an array of
// group keys) to force an ordinal category order instead, e.g. low→medium→high
// for urgency or the bucket order for needs complexity.

import { Chart } from 'chart.js';
import { humanize, percent } from '../format.js';

const ACCENT = '#6d8bff';

export function createCloseRateBarChart(canvas, data, { order } = {}) {
  const rows = orderRows(data, order);

  return new Chart(canvas.getContext('2d'), {
    type: 'bar',
    data: {
      labels: rows.map((r) => humanize(labelOf(r))),
      datasets: [
        {
          label: 'Close rate',
          data: rows.map((r) => r.close_rate),
          backgroundColor: ACCENT,
          borderRadius: 4,
          maxBarThickness: 26,
        },
      ],
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: {
          suggestedMax: 1,
          ticks: { callback: (v) => percent(v) },
        },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const r = rows[ctx.dataIndex];
              return `${percent(r.close_rate, 1)} · ${r.closed}/${r.total} closed`;
            },
          },
        },
      },
    },
  });
}

// The datasets that share this component label their category under different
// keys: `group` (most), `needs_bucket` (#6), `rep` (#4a).
function labelOf(row) {
  return row.group ?? row.needs_bucket ?? row.rep;
}

function orderRows(data, order) {
  if (order) {
    const rank = new Map(order.map((key, i) => [key, i]));
    return [...data].sort((a, b) => (rank.get(labelOf(a)) ?? 99) - (rank.get(labelOf(b)) ?? 99));
  }
  return [...data].sort((a, b) => b.close_rate - a.close_rate);
}
