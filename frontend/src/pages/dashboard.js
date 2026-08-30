// Dashboard page — scaffold only.
// Charts render against placeholder data so the layout is in place; wiring
// these to the backend aggregation endpoints is a later step.
import {
  Chart,
  BarController,
  BarElement,
  LineController,
  LineElement,
  PointElement,
  DoughnutController,
  ArcElement,
  CategoryScale,
  LinearScale,
  Tooltip,
  Legend,
} from 'chart.js';

Chart.register(
  BarController,
  BarElement,
  LineController,
  LineElement,
  PointElement,
  DoughnutController,
  ArcElement,
  CategoryScale,
  LinearScale,
  Tooltip,
  Legend
);

Chart.defaults.color = '#9aa2ad';
Chart.defaults.borderColor = '#2a2f3a';
Chart.defaults.font.family = 'system-ui, sans-serif';

const ACCENT = '#6d8bff';
const PALETTE = ['#6d8bff', '#3fb668', '#e0a83d', '#e05d5d', '#9b7fe0', '#43b7c2'];

// --- Placeholder data (replace with backend aggregation results) ---
const PLACEHOLDER = {
  meetingsByMonth: {
    labels: ['Sep', 'Oct', 'Nov', 'Dec', 'Jan', 'Feb'],
    data: [820, 910, 1180, 1040, 1330, 1210],
  },
  conversionBySeller: {
    labels: ['Toro', 'Vega', 'Rojas', 'Díaz', 'Muñoz'],
    data: [0.42, 0.31, 0.38, 0.27, 0.35],
  },
  useCases: {
    labels: ['Soporte / FAQ', 'Ventas', 'Agendamiento', 'Cobranzas', 'Onboarding'],
    data: [38, 24, 18, 12, 8],
  },
  industries: {
    labels: ['Retail', 'Salud', 'Educación', 'Fintech', 'Logística', 'Otros'],
    data: [26, 19, 15, 14, 12, 14],
  },
};

const CHARTS = [
  {
    title: 'Meetings per month',
    type: 'line',
    build: (d) => ({
      labels: d.meetingsByMonth.labels,
      datasets: [
        {
          label: 'Meetings',
          data: d.meetingsByMonth.data,
          borderColor: ACCENT,
          backgroundColor: 'rgba(109,139,255,0.15)',
          fill: true,
          tension: 0.3,
        },
      ],
    }),
  },
  {
    title: 'Conversion rate by seller',
    type: 'bar',
    options: { scales: { y: { ticks: { callback: (v) => `${Math.round(v * 100)}%` }, suggestedMax: 0.5 } } },
    build: (d) => ({
      labels: d.conversionBySeller.labels,
      datasets: [{ label: 'Closed rate', data: d.conversionBySeller.data, backgroundColor: ACCENT }],
    }),
  },
  {
    title: 'Requested use cases',
    type: 'doughnut',
    options: { plugins: { legend: { position: 'right' } } },
    build: (d) => ({
      labels: d.useCases.labels,
      datasets: [{ data: d.useCases.data, backgroundColor: PALETTE }],
    }),
  },
  {
    title: 'Client industry mix',
    type: 'doughnut',
    options: { plugins: { legend: { position: 'right' } } },
    build: (d) => ({
      labels: d.industries.labels,
      datasets: [{ data: d.industries.data, backgroundColor: PALETTE }],
    }),
  },
];

export function renderDashboardPage(mount) {
  const page = document.createElement('div');
  page.className = 'page';
  page.innerHTML = `
    <h1 class="page__title">Dashboard</h1>
    <p class="page__subtitle">Insights from LLM-enhanced transcripts.</p>
    <div class="empty-note" style="margin-bottom:20px;">
      Scaffold — charts show placeholder data. Connect to the backend aggregation
      endpoints to populate with real transcript insights.
    </div>
    <div class="chart-grid" id="chart-grid"></div>
  `;
  mount.appendChild(page);

  const grid = page.querySelector('#chart-grid');
  const instances = [];

  CHARTS.forEach((spec) => {
    const card = document.createElement('div');
    card.className = 'chart-card';
    card.innerHTML = `<h3>${spec.title}</h3><div class="chart-card__canvas-wrap"><canvas></canvas></div>`;
    grid.appendChild(card);

    const ctx = card.querySelector('canvas').getContext('2d');
    instances.push(
      new Chart(ctx, {
        type: spec.type,
        data: spec.build(PLACEHOLDER),
        options: {
          responsive: true,
          maintainAspectRatio: false,
          ...(spec.options || {}),
        },
      })
    );
  });

  return () => instances.forEach((c) => c.destroy());
}
