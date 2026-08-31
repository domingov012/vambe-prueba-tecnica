// Small formatting helpers shared by the dashboard charts. Pure functions, no
// DOM — kept flat alongside api.js / router.js rather than in a lib/ folder.

// enum_value -> "Enum Value". Backend aggregation groups are raw enum strings
// (e.g. "retail_ecommerce", "google_search_ads"); charts want them readable.
// Capitalises at word starts only, never mid-word: sales reps arrive as real
// names, and \b sits between "ñ" and "o", which turned "Muñoz" into "MuñOz".
export function humanize(value) {
  if (value == null || value === '') return '—';
  return String(value)
    .replace(/_/g, ' ')
    .replace(/(^|\s)(\p{L})/gu, (_, space, char) => space + char.toUpperCase());
}

export function percent(fraction, digits = 0) {
  return `${(fraction * 100).toFixed(digits)}%`;
}

export function count(n) {
  return Number(n || 0).toLocaleString(LOCALE);
}

// A difference between two rates, in percentage points — never "%", which would
// read as a relative change. Always signed: the sign is the whole message.
export function points(fraction, digits = 0) {
  const value = (Number(fraction) || 0) * 100;
  // Sign comes off the ROUNDED figure: −0.4 pts displayed at zero decimals is
  // "±0 pts", never "−0 pts", which reads as a defect rather than as a rounding.
  const rounded = Number(value.toFixed(digits));
  const sign = rounded > 0 ? '+' : rounded < 0 ? '−' : '±';
  return `${sign}${Math.abs(rounded).toFixed(digits)} pts`;
}

// "2024-02" -> "feb 24". The backend buckets months as ISO year-month strings;
// parsed as UTC noon so a negative timezone offset can't roll it back a month.
export function monthLabel(month) {
  const [year, index] = String(month).split('-').map(Number);
  if (!year || !index) return month;
  return new Date(Date.UTC(year, index - 1, 1, 12))
    .toLocaleDateString(LOCALE, { month: 'short', year: '2-digit', timeZone: 'UTC' })
    .replace('.', '');
}

export const LOCALE = 'es-CL';

const UNITS = [
  ['año', 'años', 31536000],
  ['mes', 'meses', 2592000],
  ['día', 'días', 86400],
  ['hora', 'horas', 3600],
  ['minuto', 'minutos', 60],
];

// ISO timestamp -> "recién" / "hace 3 horas" / "hace 2 días".
export function relativeTime(iso) {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return iso || 'fecha desconocida';

  const seconds = Math.round((Date.now() - then) / 1000);
  if (seconds < 45) return 'recién';

  for (const [singular, plural, size] of UNITS) {
    const n = Math.round(seconds / size);
    if (n >= 1) return `hace ${n} ${n === 1 ? singular : plural}`;
  }
  return 'recién';
}

const DAY_MS = 86400 * 1000;

export function isStale(iso, maxAgeMs = DAY_MS) {
  const then = new Date(iso).getTime();
  return !Number.isNaN(then) && Date.now() - then > maxAgeMs;
}
