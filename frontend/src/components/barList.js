// The dashboard's one chart mark, in two flavours.
//
//   createProportionList — bar length = close rate, bar THICKNESS = sample size,
//     dashed rule = the dataset's overall close rate. The thickness encoding is
//     the point: 100% of 2 deals and 60% of 40 deals are not the same claim, so
//     a thin sliver reads as "small sample" without anyone hovering a tooltip.
//     Shape: [{ group|rep|needs_bucket, total, closed, close_rate }].
//
//   createCountList — bar length = count against the largest count in the set.
//     Shape: [{ <labelKey>, count }].
//
// Both are HTML/CSS rather than Chart.js: rows keyed by category so switching a
// dimension diffs in place (widths and thicknesses tween, positions FLIP) and
// rows can be real <button>s for the rep drill-down.

import { humanize, percent, points } from '../format.js';

const MIN_THICK = 5;   // px — a 1-deal group still has to be visible and clickable
const MAX_THICK = 24;

const prefersReducedMotion = () =>
  window.matchMedia('(prefers-reduced-motion: reduce)').matches;

// `minTotal` dims rows the dataset can't support. Thickness already whispers
// "small sample", but any list sorted by rate puts the thinnest bars on top —
// exactly the rows nobody should act on — so they also lose contrast.
// `subMode: 'lift'` swaps the closed/total readout for a signed points figure,
// used wherever the point of the row is its distance from a baseline.
export function createProportionList(container, options = {}) {
  const { minTotal = 0, subMode = 'count' } = options;
  return createList(container, {
    ...options,
    // The house line only means something against a full population; nested
    // lists (a single rep's sectors) opt out with `baselined: false`.
    baselined: options.baselined !== false,
    metrics: (row, scale) => ({
      width: percent(clamp01(row.close_rate), 0),
      // sqrt keeps a 90-deal group from dwarfing a 9-deal one by 10x
      thickness: MIN_THICK + (MAX_THICK - MIN_THICK) * Math.sqrt(safeRatio(row.total, scale.maxTotal)),
      value: percent(clamp01(row.close_rate), 0),
      sub: subMode === 'lift' && row.lift != null ? points(row.lift) : `${row.closed}/${row.total}`,
      faint: minTotal > 0 && row.total < minTotal,
      title:
        `${percent(clamp01(row.close_rate), 1)} de conversión · ${row.closed} de ${row.total} reuniones` +
        (row.lift != null ? ` · ${points(row.lift, 1)} vs. referencia` : '') +
        (minTotal > 0 && row.total < minTotal ? ` · muestra insuficiente (n < ${minTotal})` : ''),
    }),
    scaleOf: (rows) => ({ maxTotal: Math.max(...rows.map((r) => r.total || 0), 1) }),
  });
}

export function createCountList(container, options = {}) {
  const labelKey = options.labelKey || 'need';
  return createList(container, {
    ...options,
    keyOf: (row) => row[labelKey],
    metrics: (row, scale) => ({
      width: percent(safeRatio(row.count, scale.max), 1),
      thickness: 14,
      value: String(row.count),
      sub: '',
      title: `${humanize(row[labelKey])}: ${row.count} menciones`,
    }),
    scaleOf: (rows) => ({ max: Math.max(...rows.map((r) => r.count || 0), 1) }),
  });
}

// --- shared machinery -------------------------------------------------------

function createList(container, config) {
  const {
    metrics,
    scaleOf,
    keyOf = defaultKey,
    labelFormat = humanize,
    labelWidth = null,
    baselined = false,
    tone = null,
    interactive = false,
    renderExpansion = null,
  } = config;

  const list = document.createElement('ul');
  list.className = 'bars' + (baselined ? ' bars--baselined' : '') + (interactive ? ' bars--interactive' : '');
  if (tone) list.dataset.tone = tone;
  if (labelWidth) list.style.setProperty('--label-col', labelWidth);
  container.appendChild(list);

  const nodes = new Map(); // category key -> <li>
  let selected = null;
  let panel = null;

  function update(rows, { baseline = null } = {}) {
    collapse();

    if (baseline != null) list.style.setProperty('--baseline', percent(clamp01(baseline), 1));

    const scale = scaleOf(rows);
    const keys = rows.map((row) => String(keyOf(row)));

    for (const [key, node] of nodes) {
      if (!keys.includes(key)) {
        node.remove();
        nodes.delete(key);
      }
    }

    const entering = [];
    rows.forEach((row) => {
      const key = String(keyOf(row));
      let node = nodes.get(key);
      if (!node) {
        node = buildRow(key);
        nodes.set(key, node);
        entering.push(node);
      }
      paintRow(node, row, metrics(row, scale), entering.includes(node));
    });

    // Reorder in place; existing rows slide to their new slot instead of jumping.
    flip(list, () => rows.forEach((row) => list.appendChild(nodes.get(String(keyOf(row))))));

    if (entering.length) {
      requestAnimationFrame(() => {
        entering.forEach((node) => {
          node.classList.remove('bar--enter');
          node.style.setProperty('--w', node.dataset.targetWidth);
        });
      });
    }
  }

  function buildRow(key) {
    const li = document.createElement('li');
    li.className = 'bar bar--enter';
    li.dataset.key = key;

    const row = document.createElement(interactive ? 'button' : 'div');
    row.className = 'bar__row';
    if (interactive) {
      row.type = 'button';
      row.setAttribute('aria-expanded', 'false');
      row.addEventListener('click', () => toggle(key));
    }
    row.innerHTML = `
      <span class="bar__label"></span>
      <span class="bar__track"><span class="bar__rail"></span><span class="bar__fill"></span></span>
      <span class="bar__read"><span class="bar__value"></span><span class="bar__sub"></span></span>`;

    li.appendChild(row);
    return li;
  }

  function paintRow(node, row, m, isNew) {
    node.dataset.targetWidth = m.width;
    node.style.setProperty('--w', isNew ? '0%' : m.width);
    node.style.setProperty('--h', `${m.thickness.toFixed(1)}px`);
    node.classList.toggle('bar--faint', Boolean(m.faint));

    node.querySelector('.bar__label').textContent = labelFormat(keyOf(row));
    node.querySelector('.bar__row').title = m.title;
    node.querySelector('.bar__value').textContent = m.value;
    node.querySelector('.bar__sub').textContent = m.sub;
  }

  // --- drill-down -----------------------------------------------------------

  function toggle(key) {
    if (selected === key) {
      collapse();
      return;
    }
    collapse();

    const node = nodes.get(key);
    if (!node || !renderExpansion) return;

    selected = key;
    node.classList.add('bar--on');
    node.querySelector('.bar__row').setAttribute('aria-expanded', 'true');

    panel = document.createElement('li');
    panel.className = 'bar-panel';
    const inner = document.createElement('div');
    inner.className = 'bar-panel__inner';
    const body = document.createElement('div');
    body.className = 'bar-panel__body';
    inner.appendChild(body);
    panel.appendChild(inner);
    list.insertBefore(panel, node.nextSibling);

    renderExpansion(key, body);
    requestAnimationFrame(() => panel.classList.add('bar-panel--open'));
  }

  function collapse() {
    if (!selected) return;
    const node = nodes.get(selected);
    if (node) {
      node.classList.remove('bar--on');
      node.querySelector('.bar__row').setAttribute('aria-expanded', 'false');
    }
    if (panel) panel.remove();
    panel = null;
    selected = null;
  }

  return { update, collapse, el: list };
}

// Measure, reorder, then play each row back from where it was.
function flip(list, reorder) {
  if (prefersReducedMotion()) {
    reorder();
    return;
  }
  const before = new Map();
  for (const node of list.children) before.set(node, node.getBoundingClientRect().top);

  reorder();

  for (const node of list.children) {
    const previous = before.get(node);
    if (previous == null) continue;
    const delta = previous - node.getBoundingClientRect().top;
    if (!delta) continue;
    node.animate(
      [{ transform: `translateY(${delta}px)` }, { transform: 'none' }],
      { duration: 360, easing: 'cubic-bezier(0.22, 0.61, 0.36, 1)' }
    );
  }
}

// close-rate datasets label their category under different keys depending on
// the aggregation: `group` (single-select dimensions), `rep`, `needs_bucket`,
// `value` (the multi-select membership datasets). Rows whose category isn't
// unique on its own — the signal board, where "other" appears under several
// dimensions — pass an explicit `keyOf`.
function defaultKey(row) {
  return row.group ?? row.rep ?? row.needs_bucket ?? row.value;
}

const clamp01 = (n) => Math.min(1, Math.max(0, Number(n) || 0));
const safeRatio = (n, d) => (d ? clamp01(n / d) : 0);
