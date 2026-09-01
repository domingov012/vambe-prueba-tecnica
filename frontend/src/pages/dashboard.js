import { getDashboardInsights } from '../api.js';
import { percent, count, humanize, relativeTime, isStale } from '../format.js';
import { createProportionList, createCountList } from '../components/barList.js';
import { createSegmented } from '../components/segmented.js';
import { createDropdown } from '../components/dropdown.js';
import { createTimeSeries } from '../components/timeSeries.js';
import { renderHeatmap } from '../components/heatmap.js';
import { buildSampleInsights } from './dashboard.sample.js';

// Ordinal domains: these read in their own order, never sorted by value.
const URGENCY_ORDER = ['low', 'medium', 'high', 'unclear'];
const SIZE_ORDER = ['solo_micro', 'small', 'medium', 'large', 'unclear'];
const VOLUME_ORDER = ['low', 'medium', 'high', 'very_high', 'unclear'];
const COMPLEXITY_ORDER = ['0', '1-2', '3-4', '5+'];

const VOLUME_RANGES = {
  low: '<100/sem',
  medium: '100–500/sem',
  high: '500–1500/sem',
  very_high: '1500+/sem',
};

const DIMENSIONS = [
  { value: 'sector', label: 'Sector', key: 'close_rate_by_sector' },
  { value: 'business_model', label: 'Model', key: 'close_rate_by_business_model' },
  { value: 'business_size', label: 'Size', key: 'close_rate_by_business_size', order: SIZE_ORDER },
  {
    value: 'inquiry_volume',
    label: 'Volume',
    key: 'close_rate_by_inquiry_volume',
    order: VOLUME_ORDER,
    annotate: VOLUME_RANGES,
  },
  { value: 'urgency', label: 'Urgency', key: 'close_rate_by_urgency', order: URGENCY_ORDER },
  { value: 'discovery_channel', label: 'Discovery', key: 'close_rate_by_discovery_channel' },
  { value: 'regulatory_flag', label: 'Regulated', key: 'close_rate_by_regulatory_flag' },
];

const MATRIX_VIEWS = {
  sector: { key: 'sector_needs_matrix', rowKey: 'sector', label: 'By sector' },
  business_size: { key: 'size_needs_matrix', rowKey: 'business_size', label: 'By size' },
};

const REP_CUTS = {
  sector: { key: 'rep_performance_by_sector', field: 'sector', label: 'Sector', noun: 'sector' },
  business_model: {
    key: 'rep_performance_by_business_model',
    field: 'business_model',
    label: 'Model',
    noun: 'modelo de negocio',
  },
};

export function renderDashboardPage(mount) {
  const page = document.createElement('div');
  page.className = 'dash';
  page.innerHTML = `
    <div class="dash__inner">
      <header class="hero" id="hero"></header>
      <div class="dash-status" id="dash-status"></div>
      <div id="sections"></div>
    </div>`;
  mount.appendChild(page);

  const heroEl = page.querySelector('#hero');
  const statusEl = page.querySelector('#dash-status');
  const sectionsEl = page.querySelector('#sections');

  let disposed = false;
  // Cleanups returned by sections that hold something the GC won't reclaim on
  // its own — currently the timeline's ResizeObserver. Run on re-render and on
  // navigation away.
  let disposeSections = [];

  function showLoading() {
    heroEl.innerHTML = `
      <p class="hero__eyebrow">Leyendo transcripciones enriquecidas</p>
      <h1 class="hero__title">Cargando datos</h1>
      <div class="skeleton skeleton--strip"></div>`;
    statusEl.className = 'dash-status';
    statusEl.textContent = '';
    sectionsEl.innerHTML = ['', '', '']
      .map(
        () => `
        <div class="sect">
          <div class="sect__rail"><span class="skeleton" style="height:14px;width:150px"></span></div>
          <div class="sect__body"><span class="skeleton skeleton--rows"></span></div>
        </div>`
      )
      .join('');
  }

  function showMessage(kind, html) {
    heroEl.innerHTML = `
      <p class="hero__eyebrow">Vambe · Insights de ventas</p>
      <h1 class="hero__title">Sin datos disponibles</h1>`;
    sectionsEl.innerHTML = '';
    statusEl.className = `dash-status dash-status--${kind}`;
    statusEl.innerHTML = html;
  }

  function render(payload, { sample }) {
    renderHero(heroEl, payload);

    if (sample) {
      statusEl.className = 'dash-status dash-status--sample';
      statusEl.innerHTML = `
        <span>Datos de ejemplo — sin conexión a transcripciones reales.</span>
        <span class="dash-status__actions">
          <button class="btn btn--ghost btn--sm" data-action="live">Cargar datos reales</button>
        </span>`;
      statusEl
        .querySelector('[data-action="live"]')
        .addEventListener('click', () => load({ sample: false }));
    } else {
      const stale = isStale(payload.computed_at);
      statusEl.className = `dash-status${stale ? ' dash-status--warn' : ''}`;
      statusEl.textContent = stale
        ? `Datos de ${relativeTime(payload.computed_at)} — pueden estar desactualizados`
        : `Datos de ${relativeTime(payload.computed_at)}`;
    }

    sectionsEl.innerHTML = '';
    // The two rep sections sit adjacent on purpose: "how is each rep doing" and
    // "how has that moved" are one question asked twice, and reading them apart
    // invites judging a rep on a snapshot.
    disposeSections.forEach((dispose) => dispose());
    disposeSections = [
      timelineSection,
      repSection,
      closeRateSection,
      complexitySection,
      demandSection,
      discoveryChannelSection,
      currentChannelSection,
      matrixSection,
    ]
      .map((build) => build(sectionsEl, payload))
      .filter((value) => typeof value === 'function');
  }

  async function load({ sample }) {
    if (disposed) return;

    if (sample) {
      render(buildSampleInsights(), { sample: true });
      return;
    }

    showLoading();
    try {
      const payload = await getDashboardInsights();
      if (disposed) return;
      render(payload, { sample: false });
    } catch (err) {
      if (disposed) return;
      const noData = err.status === 404;
      showMessage(
        noData ? 'info' : 'error',
        `
        <span>${
          noData
            ? 'Aún no hay datos calculados. Sube un CSV y espera a que termine el job de enriquecimiento.'
            : `No se pudo cargar el dashboard: ${err.message}`
        }</span>
        <span class="dash-status__actions">
          ${noData ? '' : '<button class="btn btn--ghost btn--sm" data-action="retry">Reintentar</button>'}
          <button class="btn btn--sm" data-action="sample">Ver datos de ejemplo</button>
        </span>`
      );
      const retry = statusEl.querySelector('[data-action="retry"]');
      if (retry) retry.addEventListener('click', () => load({ sample: false }));
      statusEl
        .querySelector('[data-action="sample"]')
        .addEventListener('click', () => load({ sample: true }));
    }
  }

  // Live by default now that enriched transcripts exist. Sample mode stays
  // reachable from the 404/error states, which is where it's actually useful.
  load({ sample: false });

  return () => {
    disposed = true;
    disposeSections.forEach((dispose) => dispose());
    disposeSections = [];
  };
}

// --- Hero: the whole dataset as one bar -------------------------------------
// Every chart below is a cut of this bar, so the page opens by drawing it.

function renderHero(el, payload) {
  const totals = overallTotals(payload);

  if (!totals) {
    el.innerHTML = `
      <p class="hero__eyebrow">Vambe · Insights de ventas</p>
      <h1 class="hero__title">Sin datos disponibles</h1>`;
    return;
  }

  el.innerHTML = `
    <p class="hero__eyebrow">${count(totals.total)} reuniones analizadas</p>
    <h1 class="hero__title">Tasa de conversión general</h1>
    <div class="hero__strip"><div class="hero__fill"></div></div>
    <div class="hero__legend">
      <span><b>${percent(totals.rate, 1)}</b> cerradas · ${count(totals.closed)} negocios</span>
      <span>${count(totals.total - totals.closed)} no cerradas</span>
    </div>
  `;

  const fill = el.querySelector('.hero__fill');
  requestAnimationFrame(() => {
    fill.style.width = percent(totals.rate, 2);
  });
}

// Each meeting lands in exactly one sector bucket, so that dataset already sums
// to the full population — no extra endpoint needed for the headline numbers.
function overallTotals(payload) {
  const rows = payload.close_rate_by_sector?.length
    ? payload.close_rate_by_sector
    : payload.rep_performance;
  if (!Array.isArray(rows) || !rows.length) return null;

  const total = rows.reduce((sum, r) => sum + (r.total || 0), 0);
  const closed = rows.reduce((sum, r) => sum + (r.closed || 0), 0);
  if (!total) return null;
  return { total, closed, rate: closed / total };
}

// --- Section scaffold -------------------------------------------------------

function section(parent, { eyebrow, title, note }) {
  const el = document.createElement('section');
  el.className = 'sect';
  el.innerHTML = `
    <div class="sect__rail">
      <p class="eyebrow"></p>
      <h2 class="sect__title"></h2>
      <p class="sect__note"></p>
      <div class="sect__controls"></div>
    </div>
    <div class="sect__body"></div>`;
  parent.appendChild(el);

  const titleEl = el.querySelector('.sect__title');
  const noteEl = el.querySelector('.sect__note');
  el.querySelector('.eyebrow').textContent = eyebrow;
  titleEl.textContent = title;
  noteEl.textContent = note;

  return {
    el,
    titleEl,
    noteEl,
    controls: el.querySelector('.sect__controls'),
    body: el.querySelector('.sect__body'),
  };
}

function emptyState(container, message = 'Sin datos suficientes.') {
  container.innerHTML = `<div class="note">${message}</div>`;
}

// A slot a section can flip to when the active slice is empty, without
// destroying the chart nodes sitting next to it.
function emptySlot(parent, message = 'Sin datos suficientes.') {
  const el = document.createElement('div');
  el.className = 'note';
  el.hidden = true;
  el.textContent = message;
  parent.appendChild(el);
  return {
    show(text) {
      if (text) el.textContent = text;
      el.hidden = false;
    },
    hide() {
      el.hidden = true;
    },
  };
}

function axis(container, left, right) {
  const el = document.createElement('div');
  el.className = 'bars__axis';
  el.innerHTML = `<span>${left}</span><span>${right}</span>`;
  container.appendChild(el);
}

// --- 1. Conversion over time ------------------------------------------------

function timelineSection(parent, payload) {
  const rows = payload.close_rate_by_month;
  const perRep = payload.rep_performance_by_month || [];
  const missing = payload._meta?.rows_without_date || 0;
  const gate = minSample(payload);

  const sect = section(parent, { eyebrow: 'Tendencia', title: 'Conversión mes a mes', note: '' });

  // A single month is a number, not a trend — the chart would imply a slope
  // that isn't there.
  if (!Array.isArray(rows) || rows.length < 2) {
    emptyState(
      sect.body,
      missing
        ? 'Sin fechas suficientes. Ejecuta python -m scripts.backfill_enhanced_meeting_date.'
        : 'Se necesitan al menos dos meses de reuniones para dibujar una tendencia.'
    );
    return;
  }

  let activeRep = ALL;

  const reps = [...new Set(perRep.map((row) => row.rep))].sort((a, b) => a.localeCompare(b));
  if (reps.length) {
    const picker = createDropdown({
      label: 'Vendedor',
      options: [{ value: ALL, label: 'Equipo completo' }, ...reps.map((r) => ({ value: r, label: r }))],
      value: activeRep,
      onChange: (v) => {
        activeRep = v;
        draw();
      },
    });
    sect.controls.appendChild(picker.el);
  }

  const chart = createTimeSeries(sect.body, { minTotal: gate });

  function draw() {
    const team = { key: 'team', label: 'Equipo', tone: 'muted', rows };

    if (activeRep === ALL) {
      sect.noteEl.textContent =
        'Tasa de conversión de cada mes. El tamaño del punto indica cuántas reuniones lo ' +
        'respaldan; los puntos huecos tienen menos de ' +
        `${gate}. La línea punteada es la tasa general del período.` +
        (missing ? ` ${count(missing)} reuniones sin fecha quedan fuera.` : '');
      // The team line is the subject here, not context — so it takes the focus
      // tone rather than the muted one it wears behind a rep.
      chart.update([{ ...team, tone: 'focus' }], { baseline: baseRate(payload) });
      return;
    }

    const repRows = perRep.filter((row) => row.rep === activeRep);
    const months = repRows.length;
    sect.noteEl.textContent =
      `${activeRep} contra el equipo (línea tenue). ${count(months)} ` +
      `${months === 1 ? 'mes' : 'meses'} con reuniones; los meses sin ninguna cortan la línea, ` +
      'en vez de dibujar un 0% que nadie registró. Los puntos huecos tienen menos de ' +
      `${gate} reuniones — con un solo mes flaco la pendiente no significa gran cosa.`;

    chart.update([team, { key: activeRep, label: activeRep, tone: 'focus', rows: repRows }], {
      baseline: baseRate(payload),
    });
  }

  draw();
  return chart.destroy;
}

// --- 2. Close rate, seven ways ----------------------------------------------

function closeRateSection(parent, payload) {
  const sect = section(parent, {
    eyebrow: 'Conversión',
    title: 'Tasa de conversión por segmento',
    note: 'Siete cortes de las mismas reuniones. La línea punteada marca la tasa de conversión general.',
  });

  let activeDimension = 'sector';
  let sortBy = 'rate';

  const tabs = createSegmented(
    DIMENSIONS.map(({ value, label }) => ({ value, label })),
    { value: activeDimension, onChange: (v) => { activeDimension = v; draw(); } }
  );
  sect.controls.appendChild(tabs.el);

  const sort = createSegmented(
    [
      { value: 'rate', label: 'By rate' },
      { value: 'volume', label: 'By volume' },
    ],
    { value: sortBy, variant: 'quiet', onChange: (v) => { sortBy = v; draw(); } }
  );
  sect.controls.appendChild(sort.el);

  const chartHost = document.createElement('div');
  sect.body.appendChild(chartHost);
  // One list serves all seven cuts, so the label formatter reads the active
  // dimension at paint time rather than being fixed at construction.
  const list = createProportionList(chartHost, {
    labelWidth: '210px',
    labelFormat: (key) => {
      const annotate = DIMENSIONS.find((d) => d.value === activeDimension)?.annotate;
      const range = annotate?.[key];
      return range ? `${humanize(key)} (${range})` : humanize(key);
    },
  });
  axis(chartHost, '0%', '100% tasa de conversión');
  const empty = emptySlot(sect.body);

  function draw() {
    const dimension = DIMENSIONS.find((d) => d.value === activeDimension);
    const rows = payload[dimension.key];

    // Ordinal dimensions keep their own sequence, so a sort toggle would only
    // scramble it — hide rather than disable, there's nothing to explain.
    sort.el.hidden = Boolean(dimension.order);

    if (!Array.isArray(rows) || !rows.length) {
      chartHost.hidden = true;
      empty.show('Sin reuniones clasificadas en esta dimensión.');
      return;
    }

    chartHost.hidden = false;
    empty.hide();

    const ordered = dimension.order
      ? byOrder(rows, dimension.order)
      : sortBy === 'volume'
        ? [...rows].sort((a, b) => b.total - a.total || b.close_rate - a.close_rate)
        : [...rows].sort((a, b) => b.close_rate - a.close_rate || b.total - a.total);

    list.update(ordered, { baseline: weightedRate(rows) });
  }

  draw();
}

// --- 3. Needs complexity (ordinal, no selector) -----------------------------

function complexitySection(parent, payload) {
  const rows = payload.close_rate_by_needs_complexity;
  const sect = section(parent, {
    eyebrow: 'Complejidad',
    title: 'Tasa de conversión por número de necesidades',
    note: 'Reuniones agrupadas según cuántas necesidades distintas planteó el cliente.',
  });

  if (!Array.isArray(rows) || !rows.length) {
    emptyState(sect.body);
    return;
  }

  const list = createProportionList(sect.body, {
    labelFormat: (bucket) => `${bucket} needs`,
  });
  list.update(byOrder(rows, COMPLEXITY_ORDER), { baseline: weightedRate(rows) });
  axis(sect.body, '0%', '100% tasa de conversión');
}

// --- 4. Needs: demand and conversion ----------------------------------------
// Same categories, two measures. "How often is this asked for" and "does asking
// for it predict a close" are both questions about the needs list, so they share
// a section and a measure toggle rather than duplicating fifteen labels twice
// down the page.

function demandSection(parent, payload) {
  measureSection(parent, payload, {
    eyebrow: 'Necesidades',
    title: 'Necesidades más mencionadas',
    countRows: payload.needs_frequency,
    rateRows: payload.close_rate_by_need,
    labelKey: 'need',
    labelWidth: '260px',
    tone: null,
    top: 8,
    countNote:
      'Menciones en todas las transcripciones analizadas. Una reunión puede plantear varias necesidades.',
    rateNote:
      'Tasa de conversión de las reuniones que plantearon cada necesidad. Los grupos se solapan ' +
      '(una reunión cuenta en cada necesidad que menciona), así que se comparan contra la tasa general, ' +
      'no entre sí.',
  });
}

// --- 5 & 6. The two channel charts ------------------------------------------
// Kept as separate sections on purpose. "Discovery channel" is the marketing
// touchpoint that brought the client in; "current channel" is the support
// channel they already operate. The shared word is the only thing they share,
// and a toggle between them reads as two views of one metric.
//
// Only the current-channel section gets a conversion measure. Discovery's
// close-rate cut already lives in the dimension tab strip above (it's a
// single-select field, so it belongs with the cuts that partition); duplicating
// it here would give the page two places showing the same numbers.

function discoveryChannelSection(parent, payload) {
  measureSection(parent, payload, {
    eyebrow: 'Adquisición',
    title: 'Canales de descubrimiento',
    countRows: payload.discovery_channel_frequency,
    rateRows: null,
    labelKey: 'channel',
    labelWidth: '210px',
    tone: null,
    countNote:
      'Por dónde llegó cada cliente a Vambe, contado sobre todas las transcripciones analizadas.',
  });
}

function currentChannelSection(parent, payload) {
  measureSection(parent, payload, {
    eyebrow: 'Operación del cliente',
    title: 'Canales de atención en uso',
    countRows: payload.current_channel_frequency,
    rateRows: payload.close_rate_by_current_channel,
    labelKey: 'channel',
    labelWidth: '210px',
    tone: 'tide',
    countNote: 'Los canales con los que el cliente atiende hoy, antes de integrar Vambe.',
    rateNote:
      'Tasa de conversión de los clientes que ya operan cada canal. Un cliente cuenta en cada canal ' +
      'que usa, así que la comparación es contra la tasa general — y es asociativa: WhatsApp puede ' +
      'destacar porque el retail destaca, no por el canal en sí.',
  });
}

// One list of categories, up to two measures over it. `rateRows` is optional:
// without it the section is a plain frequency chart and no toggle appears.
//
// Both lists are built once and toggled with `hidden` rather than rebuilt —
// they're different components (count vs. proportion), and tearing one down on
// every switch would throw away the row-diffing that makes the bars tween.
function measureSection(parent, payload, config) {
  const {
    eyebrow,
    title,
    countRows,
    rateRows,
    labelKey,
    labelWidth,
    tone,
    countNote,
    rateNote,
    top = 0,
  } = config;

  const sect = section(parent, { eyebrow, title, note: countNote });

  if (!Array.isArray(countRows) || !countRows.length) {
    emptyState(sect.body, 'Sin datos registrados.');
    return;
  }

  const hasRate = Array.isArray(rateRows) && rateRows.length > 0;
  const base = baseRate(payload);
  const gate = minSample(payload);
  let measure = 'count';
  let showAll = !top || countRows.length <= top;

  if (hasRate) {
    const toggle = createSegmented(
      [
        { value: 'count', label: 'Menciones' },
        { value: 'rate', label: 'Conversión' },
      ],
      { value: measure, onChange: (v) => { measure = v; draw(); } }
    );
    sect.controls.appendChild(toggle.el);
  }

  const countHost = document.createElement('div');
  const rateHost = document.createElement('div');
  sect.body.append(countHost, rateHost);

  // No axis on the count view: each bar carries its own number and the scale is
  // relative to the largest category, not a fixed 0–100%.
  const countList = createCountList(countHost, { labelKey, tone, labelWidth });
  const rateList = hasRate
    ? createProportionList(rateHost, { labelWidth, subMode: 'lift', minTotal: gate })
    : null;
  if (hasRate) axis(rateHost, '0%', '100% tasa de conversión');

  // A long tail (15 needs) reads better truncated; the channel lists are short
  // enough that `top` is left at 0 and the button never appears.
  const more = document.createElement('button');
  more.className = 'btn btn--ghost btn--sm';
  more.hidden = !top || countRows.length <= top;
  more.addEventListener('click', () => {
    showAll = !showAll;
    draw();
  });
  sect.controls.appendChild(more);

  function draw() {
    const rate = measure === 'rate' && hasRate;
    const rows = rate ? rateRows : countRows;
    const shown = showAll || !top ? rows : rows.slice(0, top);

    rateHost.hidden = !rate;
    countHost.hidden = rate;
    sect.noteEl.textContent = rate ? rateNote : countNote;
    more.textContent = showAll ? `Ver top ${top}` : `Ver las ${rows.length}`;

    if (rate) rateList.update(shown, { baseline: base });
    else countList.update([...shown].sort((a, b) => b.count - a.count));
  }

  draw();
}

// --- 7. Needs matrix --------------------------------------------------------

function matrixSection(parent, payload) {
  const sect = section(parent, {
    eyebrow: 'Matriz',
    title: 'Necesidades por segmento',
    note: 'Menciones por celda. La intensidad se calcula sobre el valor máximo de la vista activa.',
  });

  let activeMatrixDimension = 'sector';

  const toggle = createSegmented(
    Object.entries(MATRIX_VIEWS).map(([value, v]) => ({ value, label: v.label })),
    { value: activeMatrixDimension, onChange: (v) => { activeMatrixDimension = v; draw(); } }
  );
  sect.controls.appendChild(toggle.el);

  // Columns are pinned to the union of both datasets so switching dimension
  // swaps the rows and leaves the need axis exactly where it was.
  const needColumns = [
    ...new Set(
      [...(payload.sector_needs_matrix || []), ...(payload.size_needs_matrix || [])].map((r) => r.need)
    ),
  ].sort();

  const host = document.createElement('div');
  sect.body.appendChild(host);

  function draw() {
    const view = MATRIX_VIEWS[activeMatrixDimension];
    const rows = payload[view.key];

    if (!Array.isArray(rows) || !rows.length) {
      emptyState(host, 'Sin necesidades registradas para esta segmentación.');
      return;
    }

    // The heatmap owns `host` outright and repaints it on every switch, so the
    // empty state above can share it without stranding chart nodes.

    renderHeatmap(host, rows, {
      rowKey: view.rowKey,
      colKey: 'need',
      colValues: needColumns,
      rowOrder: activeMatrixDimension === 'business_size' ? SIZE_ORDER : undefined,
    });
  }

  draw();
}

// --- 8. Rep performance, cut by segment -------------------------------------
// Two views of one team, on the same axis:
//
//   "Todos"     — every rep against the house average; click one to drill into
//                 their own book, broken down by the active segment.
//   a segment   — every rep *inside* that segment, against the segment's own
//                 rate. This is the comparison that's fair: 30% is strong where
//                 the segment closes at 18% and weak where it closes at 55%, and
//                 the rep who owns the hard sector shouldn't read as the worst
//                 on the team. Hence the `lift` readout rather than closed/total.
//
// Cells get thin fast — reps × 15 sectors — so the segment view applies
// `_meta.min_sample` and dims what it can't support.

function repSection(parent, payload) {
  const reps = payload.rep_performance;
  const gate = minSample(payload);

  const sect = section(parent, {
    eyebrow: 'Equipo comercial',
    title: 'Tasa de conversión por vendedor',
    note: '',
  });

  if (!Array.isArray(reps) || !reps.length) {
    emptyState(sect.body);
    return;
  }

  let activeCut = 'sector';
  let activeValue = ALL;

  const cutTabs = createSegmented(
    Object.entries(REP_CUTS).map(([value, cut]) => ({ value, label: cut.label })),
    {
      value: activeCut,
      onChange: (v) => {
        activeCut = v;
        activeValue = ALL;
        segments.setOptions(segmentOptions(), ALL);
        draw();
      },
    }
  );
  sect.controls.appendChild(cutTabs.el);

  const segments = createDropdown({
    label: 'Segmento',
    options: segmentOptions(),
    value: activeValue,
    onChange: (v) => {
      activeValue = v;
      draw();
    },
  });
  sect.controls.appendChild(segments.el);

  const teamHost = document.createElement('div');
  const segmentHost = document.createElement('div');
  sect.body.append(teamHost, segmentHost);

  const teamList = createProportionList(teamHost, {
    interactive: true,
    renderExpansion: (rep, container) => {
      const cut = REP_CUTS[activeCut];
      const rows = (payload[cut.key] || []).filter((row) => row.rep === rep);
      const head = document.createElement('p');
      head.className = 'bar-panel__head';
      head.textContent = `${rep} — por ${cut.noun}`;
      container.appendChild(head);

      if (!rows.length) {
        emptyState(container, 'Sin desglose para este vendedor.');
        return;
      }

      // Keyed on the segment, not the default: every row here carries the same
      // `rep`, so the default key would collapse them into one bar. No house
      // line either — the comparison inside the panel is rep vs. segment, which
      // the lift readout already carries.
      const inner = createProportionList(container, {
        baselined: false,
        subMode: 'lift',
        minTotal: gate,
        keyOf: (row) => row[cut.field],
      });
      inner.update([...rows].sort((a, b) => b.close_rate - a.close_rate || b.total - a.total));
    },
  });
  axis(teamHost, '0%', '100% tasa de conversión');

  const segmentList = createProportionList(segmentHost, {
    subMode: 'lift',
    minTotal: gate,
  });
  axis(segmentHost, '0%', '100% tasa de conversión');
  const empty = emptySlot(segmentHost);

  // Biggest segments first — that's the order someone scanning for where the
  // team actually spends its time wants.
  function segmentOptions() {
    const cut = REP_CUTS[activeCut];
    const volume = new Map();
    for (const row of payload[cut.key] || []) {
      volume.set(row[cut.field], (volume.get(row[cut.field]) || 0) + row.total);
    }
    return [
      { value: ALL, label: 'Todos' },
      ...[...volume.entries()]
        .sort((a, b) => b[1] - a[1])
        .map(([value]) => ({ value, label: humanize(value) })),
    ];
  }

  function draw() {
    const cut = REP_CUTS[activeCut];
    const team = activeValue === ALL;

    teamHost.hidden = !team;
    segmentHost.hidden = team;

    if (team) {
      sect.noteEl.textContent =
        'Cada vendedor contra la tasa general. Selecciona uno para ver su desglose por ' +
        `${cut.noun}, o elige un segmento para comparar al equipo dentro de él.`;
      teamList.update([...reps].sort((a, b) => b.close_rate - a.close_rate || b.total - a.total), {
        baseline: weightedRate(reps),
      });
      return;
    }

    const rows = (payload[cut.key] || []).filter((row) => row[cut.field] === activeValue);
    // Every row in a segment carries the same segment rate; that's the baseline.
    const segmentRate = rows.length ? rows[0].segment_close_rate : 0;

    // A chart where every row is dimmed reads as disabled rather than as a
    // warning, so say it in words instead of leaving the dimming to explain it.
    const allThin = rows.length > 0 && rows.every((row) => row.total < gate);

    sect.noteEl.textContent =
      `Vendedores dentro de ${humanize(activeValue)}, contra la tasa del propio segmento ` +
      `(${percent(segmentRate, 1)}). La cifra a la derecha es la diferencia en puntos. ` +
      (allThin
        ? `Ningún vendedor llega a ${gate} reuniones en este segmento: es indicativo, no concluyente.`
        : `Las filas atenuadas tienen menos de ${gate} reuniones.`);

    if (!rows.length) {
      segmentList.update([]);
      empty.show('Ningún vendedor registra reuniones en este segmento.');
      return;
    }

    empty.hide();
    segmentList.update(
      [...rows].sort((a, b) => b.close_rate - a.close_rate || b.total - a.total),
      { baseline: segmentRate }
    );
  }

  draw();
}

// --- shared helpers ---------------------------------------------------------

// Sentinel for the rep section's "no segment selected" state. A real segment
// value can't collide with it: every enum value is lowercase.
const ALL = '__ALL__';

// The population's close rate, straight from the backend. Not derivable on the
// client for the multi-select datasets — their groups overlap, so summing group
// totals over-counts every meeting that listed more than one value.
function baseRate(payload) {
  const meta = payload._meta || {};
  if (typeof meta.base_rate === 'number') return meta.base_rate;
  return overallTotals(payload)?.rate ?? 0;
}

// One small-sample gate for the whole page, sized by the backend against the
// population (see `min_sample()`), so a 200-row dataset and a 20k-row one don't
// silently use the same threshold.
function minSample(payload) {
  return payload._meta?.min_sample ?? 0;
}

// The dataset's own average, weighted by volume — not the mean of the rates,
// which would let a 2-deal group drag the line around. Only valid for datasets
// whose groups partition the population; multi-select charts use `baseRate`.
function weightedRate(rows) {
  const total = rows.reduce((sum, r) => sum + (r.total || 0), 0);
  const closed = rows.reduce((sum, r) => sum + (r.closed || 0), 0);
  return total ? closed / total : 0;
}

function byOrder(rows, order) {
  const rank = new Map(order.map((key, i) => [key, i]));
  const keyOf = (r) => r.group ?? r.needs_bucket ?? r.rep;
  return [...rows].sort((a, b) => (rank.get(keyOf(a)) ?? 99) - (rank.get(keyOf(b)) ?? 99));
}
