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

function repPerformanceBySector() {
  const rows = [];
  for (const rep of REPS) {
    for (const sector of SECTORS) {
      if (rand() < 0.55) continue;
      const total = between(2, 18);
      const closed = Math.round(total * (0.1 + rand() * 0.6));
      rows.push({ rep, sector, total, closed, close_rate: round4(closed / total) });
    }
  }
  return rows.sort((a, b) => a.rep.localeCompare(b.rep) || b.total - a.total);
}

function needsComplexity() {
  return NEEDS_BUCKETS.map((bucket) => {
    const total = between(20, 140);
    const rate = { '0': 0.15, '1-2': 0.28, '3-4': 0.41, '5+': 0.33 }[bucket];
    const closed = Math.round(total * rate);
    return { needs_bucket: bucket, total, closed, close_rate: round4(closed / total) };
  });
}

export function buildSampleInsights() {
  rand = rng(20260830);
  return {
    close_rate_by_sector: closeRateRows(SECTORS),
    close_rate_by_business_model: closeRateRows(BUSINESS_MODELS),
    close_rate_by_business_size: closeRateRows(BUSINESS_SIZES),
    needs_frequency: frequencyRows(NEEDS, 'need'),
    discovery_channel_frequency: frequencyRows(DISCOVERY_CHANNELS, 'channel'),
    current_channel_frequency: frequencyRows(CHANNELS, 'channel'),
    rep_performance: repPerformance(),
    rep_performance_by_sector: repPerformanceBySector(),
    close_rate_by_urgency: closeRateRows(URGENCY),
    close_rate_by_needs_complexity: needsComplexity(),
    close_rate_by_discovery_channel: closeRateRows(DISCOVERY_CHANNELS),
    sector_needs_matrix: needsMatrix(SECTORS, 'sector'),
    close_rate_by_regulatory_flag: closeRateRows(REGULATORY),
    size_needs_matrix: needsMatrix(BUSINESS_SIZES, 'business_size'),
    computed_at: new Date(Date.now() - 3 * 3600 * 1000).toISOString(),
  };
}
