// Monthly conversion trend — a line chart, in SVG.
//
// The rest of the dashboard encodes sample size as bar thickness. A line has no
// thickness to spend, so it moves to the POINT: each month is a dot scaled by
// how many meetings it rests on, and months under the dataset's `min_sample`
// are drawn hollow. The line itself carries only the rate, which is the whole
// reason to prefer it here — direction between months is the question, and a
// column chart makes you compare tops instead of reading a slope.
//
// Two series at most: the team (context) and one rep (focus). A rep with no
// meetings in a month leaves a GAP — the line breaks rather than diving to 0%,
// because "sold nothing" and "wasn't working" are different claims and the data
// can't tell them apart.
//
// Laid out in real pixels against a ResizeObserver rather than a scaled
// viewBox: `preserveAspectRatio="none"` would stretch the dots into ellipses
// and the strokes with them.

import { count, monthLabel, percent } from '../format.js';

const PAD = { top: 14, right: 8, bottom: 0, left: 8 };
const MIN_DOT = 2.5;
const MAX_DOT = 7;
const SVG_NS = 'http://www.w3.org/2000/svg';

export function createTimeSeries(container, { height = 200, minTotal = 0 } = {}) {
  const el = document.createElement('div');
  el.className = 'line';
  el.innerHTML = `
    <div class="line__plot" style="height:${height}px">
      <svg class="line__svg"></svg>
      <span class="line__cap">100%</span>
      <span class="line__mark" hidden></span>
    </div>
    <div class="line__axis"></div>
    <div class="line__legend" hidden></div>`;
  container.appendChild(el);

  const plot = el.querySelector('.line__plot');
  const svg = el.querySelector('.line__svg');
  const axis = el.querySelector('.line__axis');
  const mark = el.querySelector('.line__mark');
  const legend = el.querySelector('.line__legend');

  let state = { series: [], months: [], baseline: null };

  // One redraw path for both new data and a resize, so the two can't diverge.
  const observer = new ResizeObserver(() => draw());
  observer.observe(plot);

  function update(series, { baseline = null } = {}) {
    // The x axis is the union of every series' months, so a rep's line sits on
    // the same grid as the team's even where the rep has no meetings.
    const months = [...new Set(series.flatMap((s) => s.rows.map((r) => r.month)))].sort();
    state = { series, months, baseline };

    el.classList.toggle('line--baselined', baseline != null);
    mark.hidden = baseline == null;
    if (baseline != null) mark.textContent = `promedio ${percent(clamp01(baseline), 0)}`;

    legend.hidden = series.length < 2;
    legend.innerHTML = series
      .map(
        (s) =>
          `<span class="line__key line__key--${s.tone}"><i></i>${escapeHtml(s.label)}</span>`
      )
      .join('');

    renderAxis(months);
    draw();
  }

  function renderAxis(months) {
    axis.style.gridTemplateColumns = `repeat(${months.length}, minmax(0, 1fr))`;
    axis.innerHTML = '';
    // Past a dozen months every label collides; thin them out but always keep
    // the first and last so the span of the chart stays readable.
    const stride = months.length > 12 ? Math.ceil(months.length / 8) : 1;
    months.forEach((month, index) => {
      const tick = document.createElement('span');
      tick.className = 'line__tick';
      tick.textContent =
        index % stride === 0 || index === months.length - 1 ? monthLabel(month) : '';
      axis.appendChild(tick);
    });
  }

  function draw() {
    const { series, months, baseline } = state;
    const width = plot.clientWidth;
    if (!width || !months.length) return;

    const inner = width - PAD.left - PAD.right;
    const top = PAD.top;
    const bottom = plot.clientHeight - PAD.bottom;
    // Each month owns a slot; points sit in the middle of theirs, so the first
    // and last dots don't get clipped by the plot edge.
    const slot = inner / months.length;
    const x = (month) => PAD.left + slot * (months.indexOf(month) + 0.5);
    const y = (rate) => bottom - clamp01(rate) * (bottom - top);

    if (baseline != null) mark.style.bottom = `${plot.clientHeight - y(baseline)}px`;

    svg.setAttribute('width', width);
    svg.setAttribute('height', plot.clientHeight);
    svg.innerHTML = '';

    if (baseline != null) svg.appendChild(baselineRule(y(baseline), width));

    const maxTotal = Math.max(
      ...series.flatMap((s) => s.rows.map((r) => r.total || 0)),
      1
    );

    for (const s of series) {
      const points = [...s.rows].sort((a, b) => a.month.localeCompare(b.month));
      const group = document.createElementNS(SVG_NS, 'g');
      group.setAttribute('class', `line__series line__series--${s.tone}`);

      // Break the path wherever the series skips a month on the shared axis.
      for (const run of contiguousRuns(points, months)) {
        if (run.length < 2) continue;
        const path = document.createElementNS(SVG_NS, 'path');
        path.setAttribute(
          'd',
          run.map((p, i) => `${i ? 'L' : 'M'}${x(p.month).toFixed(1)},${y(p.close_rate).toFixed(1)}`).join(' ')
        );
        path.setAttribute('class', 'line__path');
        group.appendChild(path);
      }

      for (const point of points) {
        const dot = document.createElementNS(SVG_NS, 'circle');
        dot.setAttribute('cx', x(point.month).toFixed(1));
        dot.setAttribute('cy', y(point.close_rate).toFixed(1));
        // sqrt, as in barList: a 90-meeting month shouldn't be 10x the radius
        // of a 9-meeting one, only visibly heavier.
        dot.setAttribute(
          'r',
          (MIN_DOT + (MAX_DOT - MIN_DOT) * Math.sqrt(safeRatio(point.total, maxTotal))).toFixed(2)
        );
        dot.setAttribute(
          'class',
          `line__dot${minTotal && point.total < minTotal ? ' line__dot--thin' : ''}`
        );
        const title = document.createElementNS(SVG_NS, 'title');
        title.textContent =
          `${s.label} · ${monthLabel(point.month)} · ${percent(clamp01(point.close_rate), 1)} ` +
          `de conversión · ${count(point.closed)} de ${count(point.total)} reuniones`;
        dot.appendChild(title);
        group.appendChild(dot);
      }

      svg.appendChild(group);
    }
  }

  function baselineRule(yPos, width) {
    const rule = document.createElementNS(SVG_NS, 'line');
    rule.setAttribute('x1', 0);
    rule.setAttribute('x2', width);
    rule.setAttribute('y1', yPos.toFixed(1));
    rule.setAttribute('y2', yPos.toFixed(1));
    rule.setAttribute('class', 'line__baseline');
    return rule;
  }

  return {
    update,
    el,
    destroy() {
      observer.disconnect();
    },
  };
}

// Split a series into runs of months that are adjacent on the shared axis, so
// the path breaks over the months this series has no data for.
function contiguousRuns(points, months) {
  const runs = [];
  let run = [];
  let previous = -2;
  for (const point of points) {
    const index = months.indexOf(point.month);
    if (index !== previous + 1 && run.length) {
      runs.push(run);
      run = [];
    }
    run.push(point);
    previous = index;
  }
  if (run.length) runs.push(run);
  return runs;
}

const clamp01 = (n) => Math.min(1, Math.max(0, Number(n) || 0));
const safeRatio = (n, d) => (d ? clamp01(n / d) : 0);
const escapeHtml = (s) =>
  String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
