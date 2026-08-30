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
    throw new Error(detail);
  }

  return res.status === 204 ? null : res.json();
}

// POST a CSV file for ingestion. Resolves to { summary, enrichment_job_id }.
export function uploadCsv(file) {
  const form = new FormData();
  form.append('file', file);
  return request('/ingestion/csv', { method: 'POST', body: form });
}

// GET the list of enrichment jobs, newest first.
export function listJobs() {
  return request('/jobs');
}

// GET a single enrichment job by id.
export function getJob(id) {
  return request(`/jobs/${id}`);
}
