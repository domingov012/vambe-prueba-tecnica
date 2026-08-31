// Synthetic dashboard payload — a stand-in for GET /api/dashboard/insights
// while the database is empty. Shapes and sort order match the backend
// aggregation (app/aggregation/insights.py) exactly, so the real charts render
// against it unchanged. Deterministic (seeded RNG) so the demo looks stable
// across reloads.

// --- Enum domains (mirror app/models/enhanced_transcript.py) ---
const SECTORS = [
  'retail_ecommerce', 'health_medical', 'food_beverage', 'education',
  'professional_b2b_services', 'logistics_distribution', 'real_estate_construction',
  'hospitality_tourism', 'manufacturing_industrial', 'finance_insurance',
  'technology_software', 'beauty_wellness', 'nonprofit', 'agriculture', 'other',
];
const BUSINESS_MODELS = ['b2c', 'b2b', 'b2b2c', 'nonprofit_donor_facing', 'unclear'];
const BUSINESS_SIZES = ['solo_micro', 'small', 'medium', 'large', 'unclear'];
const DISCOVERY_CHANNELS = [
  'linkedin', 'google_search_ads', 'peer_referral', 'industry_event_conference',
  'webinar', 'podcast', 'social_media', 'blog_magazine_article',
  'word_of_mouth_group', 'email_marketing', 'other', 'unclear',
];
const CHANNELS = [
  'whatsapp', 'phone_calls', 'email', 'instagram', 'facebook',
  'in_person_only', 'website_form', 'other', 'unclear',
];
const NEEDS = [
  'multi_channel_support', 'appointment_scheduling', 'crm_erp_pos_lms_integration',
  'order_shipment_inventory_tracking', 'extended_24_7_availability', 'multi_language_support',
  'human_escalation', 'lead_qualification_sales_pipeline', 'business_knowledge',
  'brand_tone_alignment', 'quote_pricing_calculation', 'data_privacy_compliance',
  'emergency_urgent_triage', 'personalized_recommendations', 'other',
];
const REGULATORY = ['health_data', 'financial_fiscal_data', 'minors_student_data', 'none_apparent', 'other'];
const URGENCY = ['high', 'medium', 'low', 'unclear'];
const INQUIRY_VOLUMES = ['low', 'medium', 'high', 'very_high', 'unclear'];
const REPS = ['Camila Torres', 'Diego Rojas', 'Valentina Vega', 'Mateo Díaz', 'Josefa Muñoz', 'Benjamín Silva'];

const NEEDS_BUCKETS = ['0', '1-2', '3-4', '5+'];

// mulberry32 — tiny deterministic PRNG so the synthetic dashboard is stable.
function rng(seed) {
  let a = seed;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// Reseeded on every buildSampleInsights() call so the payload is identical
// across reloads and repeated "sample data" toggles.
let rand = rng(20260830);
const between = (lo, hi) => lo + Math.floor(rand() * (hi - lo + 1));
const round4 = (n) => Math.round(n * 10000) / 10000;

// { group, total, closed, close_rate }, sorted desc by close_rate then total —
// matches close_rate_by_dimension().
function closeRateRows(groups, groupKey = 'group') {
  return groups
    .map((g) => {
      const total = between(6, 90);
      const rate = 0.12 + rand() * 0.5;
      const closed = Math.min(total, Math.round(total * rate));
      return { [groupKey]: g, total, closed, close_rate: round4(total ? closed / total : 0) };
    })
    .sort((a, b) => b.close_rate - a.close_rate || b.total - a.total);
}

// { <key>: value, count }, sorted desc by count — matches _frequency().
function frequencyRows(values, key) {
  return values
    .map((v) => ({ [key]: v, count: between(3, 120) }))
    .sort((a, b) => b.count - a.count || String(a[key]).localeCompare(b[key]));
}

// Flat [{ <dimension>, need, count }] cross-tab — matches needs_matrix().
function needsMatrix(dimValues, dimension) {
  const rows = [];
  for (const dim of dimValues) {
    for (const need of NEEDS) {
      if (rand() < 0.45) continue; // sparse, like real data
      rows.push({ [dimension]: dim, need, count: between(1, 22) });
    }
  }
  return rows.sort(
    (a, b) => String(a[dimension]).localeCompare(b[dimension]) || b.count - a.count
  );
}

function repPerformance() {
  return REPS.map((rep) => {
    const total = between(30, 120);
    const closed = Math.round(total * (0.2 + rand() * 0.4));
    return { rep, total, closed, close_rate: round4(closed / total) };
  }).sort((a, b) => b.close_rate - a.close_rate || b.total - a.total);
}

function needsComplexity() {
  return NEEDS_BUCKETS.map((bucket) => {
    const total = between(20, 140);
    const rate = { '0': 0.15, '1-2': 0.28, '3-4': 0.41, '5+': 0.33 }[bucket];
    const closed = Math.round(total * rate);
    return { needs_bucket: bucket, total, closed, close_rate: round4(closed / total) };
  });
}

// Rep × segment. Carries the segment's own rate and the rep's distance from it,
// as _rep_group() does when given an extra key.
function repPerformanceBySegment(values, field, keep = 0.45) {
  const rows = [];
  const segmentRate = new Map(values.map((v) => [v, 0.18 + rand() * 0.4]));
  for (const rep of REPS) {
    for (const value of values) {
      if (rand() > keep) continue;
      const total = between(2, 18);
      const rate = Math.max(0, Math.min(1, segmentRate.get(value) + (rand() - 0.5) * 0.35));
      const closed = Math.round(total * rate);
      rows.push({
        rep,
        [field]: value,
        total,
        closed,
        close_rate: round4(closed / total),
        segment_close_rate: round4(segmentRate.get(value)),
        lift: round4(closed / total - segmentRate.get(value)),
      });
    }
  }
  return rows.sort((a, b) => a.rep.localeCompare(b.rep) || b.total - a.total);
}

// Multi-select membership: groups overlap, so totals deliberately sum past the
// population and each row carries its own lift — matches close_rate_by_membership().
function membershipRows(values, base) {
  return values
    .map((value) => {
      const total = between(25, 260);
      const rate = Math.max(0.02, Math.min(0.95, base + (rand() - 0.45) * 0.34));
      const closed = Math.round(total * rate);
      return {
        value,
        total,
        closed,
        close_rate: round4(closed / total),
        lift: round4(closed / total - base),
      };
    })
    .sort((a, b) => b.close_rate - a.close_rate || b.total - a.total);
}

// Assembled from the datasets above rather than generated on its own, exactly
// as signal_board() re-derives from the same rows — otherwise the sample would
// show a ranking that contradicts the charts it's meant to summarise.
function signalBoard(datasets, base, floor) {
  const entries = [];
  for (const [dimension, rows] of datasets) {
    for (const row of rows) {
      entries.push({
        dimension,
        value: row.group ?? row.value,
        total: row.total,
        closed: row.closed,
        close_rate: row.close_rate,
        lift: round4(row.close_rate - base),
      });
    }
  }
  return entries
    .filter((entry) => entry.total >= floor)
    .sort(
      (a, b) =>
        Math.abs(b.lift) - Math.abs(a.lift) ||
        b.total - a.total ||
        a.dimension.localeCompare(b.dimension)
    );
}

const SAMPLE_MONTHS = Array.from({ length: 12 }, (_, i) => `2024-${String(i + 1).padStart(2, '0')}`);

// A year of meetings, oldest first, drifting gently upward so the trend chart
// has something to show.
function monthlyTrend(base) {
  return SAMPLE_MONTHS.map((month, i) => {
    const total = between(18, 90);
    const rate = Math.max(0.05, base - 0.1 + i * 0.017 + (rand() - 0.5) * 0.09);
    const closed = Math.round(total * rate);
    return { month, total, closed, close_rate: round4(closed / total) };
  });
}

// Per-rep series. Months a rep took no meetings are omitted rather than zeroed
// — the real aggregation does the same, and the line chart breaks its path over
// them, so the sample has to exercise that gap.
function repMonthlyTrend(base) {
  const rows = [];
  for (const rep of REPS) {
    for (const [i, month] of SAMPLE_MONTHS.entries()) {
      if (rand() < 0.18) continue;
      const total = between(2, 14);
      const rate = Math.max(0.03, Math.min(0.97, base - 0.08 + i * 0.015 + (rand() - 0.5) * 0.3));
      const closed = Math.round(total * rate);
      rows.push({ rep, month, total, closed, close_rate: round4(closed / total) });
    }
  }
  return rows.sort((a, b) => a.rep.localeCompare(b.rep) || a.month.localeCompare(b.month));
}

export function buildSampleInsights() {
  rand = rng(20260830);

  // Generated first: the sector cut partitions the population, so it defines
  // both N and the house rate the rest of the payload is measured against.
  const bySector = closeRateRows(SECTORS);
  const rowsAggregated = bySector.reduce((sum, r) => sum + r.total, 0);
  const base = round4(bySector.reduce((sum, r) => sum + r.closed, 0) / rowsAggregated);
  const floor = Math.max(5, Math.floor(rowsAggregated / 100));

  const byModel = closeRateRows(BUSINESS_MODELS);
  const bySize = closeRateRows(BUSINESS_SIZES);
  const byVolume = closeRateRows(INQUIRY_VOLUMES);
  const byUrgency = closeRateRows(URGENCY);
  const byDiscovery = closeRateRows(DISCOVERY_CHANNELS);
  const byRegulatory = closeRateRows(REGULATORY);
  const byNeed = membershipRows(NEEDS, base);
  const byCurrentChannel = membershipRows(CHANNELS, base);

  return {
    close_rate_by_sector: bySector,
    close_rate_by_business_model: byModel,
    close_rate_by_business_size: bySize,
    needs_frequency: frequencyRows(NEEDS, 'need'),
    discovery_channel_frequency: frequencyRows(DISCOVERY_CHANNELS, 'channel'),
    current_channel_frequency: frequencyRows(CHANNELS, 'channel'),
    rep_performance: repPerformance(),
    rep_performance_by_sector: repPerformanceBySegment(SECTORS, 'sector'),
    rep_performance_by_business_model: repPerformanceBySegment(BUSINESS_MODELS, 'business_model', 0.85),
    close_rate_by_urgency: byUrgency,
    close_rate_by_needs_complexity: needsComplexity(),
    close_rate_by_discovery_channel: byDiscovery,
    sector_needs_matrix: needsMatrix(SECTORS, 'sector'),
    close_rate_by_regulatory_flag: byRegulatory,
    size_needs_matrix: needsMatrix(BUSINESS_SIZES, 'business_size'),
    close_rate_by_inquiry_volume: byVolume,
    close_rate_by_need: byNeed,
    close_rate_by_current_channel: byCurrentChannel,
    signal_board: signalBoard(
      [
        ['sector', bySector],
        ['business_model', byModel],
        ['business_size', bySize],
        ['inquiry_volume', byVolume],
        ['discovery_channel', byDiscovery],
        ['regulatory_flag', byRegulatory],
        ['pain_point_urgency', byUrgency],
        ['client_needs', byNeed],
        ['current_channels', byCurrentChannel],
      ],
      base,
      floor
    ),
    close_rate_by_month: monthlyTrend(base),
    rep_performance_by_month: repMonthlyTrend(base),
    _meta: {
      rows_aggregated: rowsAggregated,
      base_rate: base,
      min_sample: floor,
      rows_without_date: 0,
    },
    computed_at: new Date(Date.now() - 3 * 3600 * 1000).toISOString(),
  };
}
