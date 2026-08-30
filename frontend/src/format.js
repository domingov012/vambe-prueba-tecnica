// Small formatting helpers shared by the dashboard charts. Pure functions, no
// DOM — kept flat alongside api.js / router.js rather than in a lib/ folder.

// enum_value -> "Enum Value". Backend aggregation groups are raw enum strings
// (e.g. "retail_ecommerce", "google_search_ads"); charts want them readable.
export function humanize(value) {
  if (value == null || value === '') return '—';
  return String(value)
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export function percent(fraction, digits = 0) {
  return `${(fraction * 100).toFixed(digits)}%`;
}

// ISO timestamp -> "just now" / "3 hours ago" / "2 days ago".
export function relativeTime(iso) {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return iso || 'unknown';

  const seconds = Math.round((Date.now() - then) / 1000);
  if (seconds < 45) return 'just now';

  const units = [
    ['year', 31536000],
    ['month', 2592000],
    ['day', 86400],
    ['hour', 3600],
    ['minute', 60],
  ];
  for (const [name, size] of units) {
    const n = Math.round(seconds / size);
    if (n >= 1) return `${n} ${name}${n > 1 ? 's' : ''} ago`;
  }
  return 'just now';
}

const DAY_MS = 86400 * 1000;

export function isStale(iso, maxAgeMs = DAY_MS) {
  const then = new Date(iso).getTime();
  return !Number.isNaN(then) && Date.now() - then > maxAgeMs;
}
