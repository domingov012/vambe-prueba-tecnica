// Thin fetch wrappers around the FastAPI backend. This is the only module that
// knows backend URL paths and response shapes. All requests are relative
// `/api/*` URLs — forwarded to the backend by the vite dev proxy, and by nginx
// in production (see deploy/).

const BASE = '/api';

async function request(path, options) {
  let res;
  try {
    res = await fetch(BASE + path, options);
  } catch (err) {
    throw new Error(`Network error: ${err.message}`);
  }

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (body && body.detail) {
        detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
      }
    } catch {
      /* non-JSON error body — keep statusText */
    }
    const err = new Error(detail);
    err.status = res.status; // lets callers distinguish 404 (no data yet) from real failures
    throw err;
  }

  return res.status === 204 ? null : res.json();
}

// POST a CSV file for ingestion. Resolves to { summary, enrichment_job_id }.
// `opts` maps to the endpoint's optional query params; omitted keys fall back to
// the backend's env defaults (LLM_BATCH_SIZE / LLM_MAX_TRANSCRIPTS_PER_JOB /
// LLM_THINKING_LEVEL). `thinkingLevel` is one of 'minimal' | 'low' | 'high'.
export function uploadCsv(file, opts = {}) {
  const form = new FormData();
  form.append('file', file);

  const params = new URLSearchParams();
  if (opts.batchSize) params.set('batch_size', opts.batchSize);
  if (opts.maxTranscripts) params.set('max_transcripts', opts.maxTranscripts);
  if (opts.thinkingLevel) params.set('thinking_level', opts.thinkingLevel);
  const query = params.toString();

  return request(`/ingestion/csv${query ? `?${query}` : ''}`, {
    method: 'POST',
    body: form,
  });
}

// GET the list of enrichment jobs, newest first.
export function listJobs() {
  return request('/jobs');
}

// GET a single enrichment job by id.
export function getJob(id) {
  return request(`/jobs/${id}`);
}

// GET the precomputed dashboard payload — all 10 chart datasets in one object
// (see aggregations.md for the shape). Throws with `.status === 404` until at
// least one enrichment job has completed and the blob has been built.
export function getDashboardInsights() {
  return request('/dashboard/insights');
}
