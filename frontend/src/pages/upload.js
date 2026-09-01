// Data Upload page — CSV upload + LLM-enhancement job list.
// Uploads POST to the backend ingestion endpoint; the jobs table polls
// GET /api/jobs every 2s while any job is still queued/running.

import { uploadCsv, listJobs } from '../api.js';
import { LOCALE } from '../format.js';

const POLL_INTERVAL_MS = 2000;
const ACTIVE_STATUSES = ['queued', 'running'];

// Backend JobStatus enum -> .badge--* modifier in style.css.
const BADGE_CLASS = {
  queued: 'queued',
  running: 'running',
  completed: 'done',
  failed: 'failed',
};

export function renderUploadPage(mount) {
  const page = document.createElement('div');
  page.className = 'page';
  page.innerHTML = `
    <h1 class="page__title">Carga de datos</h1>
    <p class="page__subtitle">Sube un CSV de transcripciones de reuniones y sigue los jobs de enriquecimiento.</p>

    <div class="card">
      <h2 class="card__title">Subir CSV</h2>
      <div class="dropzone" id="dropzone">
        <p><strong>Arrastra un archivo .csv</strong> o haz clic para buscarlo</p>
        <p class="hint">Columnas esperadas: Nombre, Correo Electronico, Numero de Telefono, Fecha de la Reunion, Vendedor asignado, closed, Transcripcion</p>
        <input type="file" id="file-input" accept=".csv,text/csv" hidden />
      </div>
      <div id="file-info"></div>
      <div id="upload-result"></div>
      <div style="margin-top:16px; display:flex; gap:10px;">
        <button class="btn" id="start-btn" disabled>Iniciar enriquecimiento</button>
        <button class="btn btn--ghost" id="clear-btn" disabled>Limpiar</button>
      </div>
    </div>

    <div class="card">
      <h2 class="card__title">Jobs de enriquecimiento</h2>
      <table class="table">
        <thead>
          <tr><th>Job</th><th>Archivo</th><th>Progreso</th><th>Estado</th><th>Inicio</th></tr>
        </thead>
        <tbody id="jobs-body"></tbody>
      </table>
      <p class="hint" id="jobs-note"></p>
    </div>
  `;
  mount.appendChild(page);

  const dropzone = page.querySelector('#dropzone');
  const fileInput = page.querySelector('#file-input');
  const fileInfo = page.querySelector('#file-info');
  const uploadResult = page.querySelector('#upload-result');
  const startBtn = page.querySelector('#start-btn');
  const clearBtn = page.querySelector('#clear-btn');
  const jobsBody = page.querySelector('#jobs-body');
  const jobsNote = page.querySelector('#jobs-note');

  let selectedFile = null;
  let uploading = false;
  let pollTimer = null;
  let disposed = false;

  // ---- File selection ----

  function setFile(file) {
    uploadResult.innerHTML = '';
    if (file && !file.name.toLowerCase().endsWith('.csv')) {
      fileInfo.innerHTML = '<div class="file-pill" style="color:var(--flare)">El archivo no es .csv</div>';
      selectedFile = null;
    } else {
      selectedFile = file || null;
      fileInfo.innerHTML = selectedFile
        ? `<div class="file-pill">📄 ${selectedFile.name} · ${(selectedFile.size / 1024).toFixed(1)} KB</div>`
        : '';
    }
    syncButtons();
  }

  function syncButtons() {
    startBtn.disabled = uploading || !selectedFile;
    clearBtn.disabled = uploading || !selectedFile;
    startBtn.textContent = uploading ? 'Subiendo…' : 'Iniciar enriquecimiento';
  }

  dropzone.addEventListener('click', () => fileInput.click());
  fileInput.addEventListener('change', (e) => setFile(e.target.files[0]));

  ['dragenter', 'dragover'].forEach((ev) =>
    dropzone.addEventListener(ev, (e) => {
      e.preventDefault();
      dropzone.classList.add('dropzone--over');
    })
  );
  ['dragleave', 'drop'].forEach((ev) =>
    dropzone.addEventListener(ev, (e) => {
      e.preventDefault();
      dropzone.classList.remove('dropzone--over');
    })
  );
  dropzone.addEventListener('drop', (e) => setFile(e.dataTransfer.files[0]));

  clearBtn.addEventListener('click', () => {
    fileInput.value = '';
    setFile(null);
  });

  // ---- Upload ----

  startBtn.addEventListener('click', async () => {
    if (!selectedFile || uploading) return;
    uploading = true;
    uploadResult.innerHTML = '';
    syncButtons();

    try {
      const { summary } = await uploadCsv(selectedFile);
      uploadResult.innerHTML = `<p class="hint" style="color:var(--tide)">
        Se recibieron ${summary.rows_received.toLocaleString(LOCALE)} filas — job de
        enriquecimiento iniciado. Sigue el progreso abajo.</p>`;
      fileInput.value = '';
      selectedFile = null;
      fileInfo.innerHTML = '';
      startPolling();
    } catch (err) {
      uploadResult.innerHTML = `<p class="hint" style="color:var(--flare)">Falló la carga: ${err.message}</p>`;
    } finally {
      uploading = false;
      syncButtons();
    }
  });

  // ---- Jobs table + polling ----

  function renderJobs(jobs) {
    if (!jobs.length) {
      jobsBody.innerHTML = '';
      jobsNote.textContent = 'Aún no hay jobs de enriquecimiento.';
      return;
    }
    jobsBody.innerHTML = jobs
      .map((j) => {
        const total = j.total_candidates || 0;
        const done = (j.processed_count || 0) + (j.failed_count || 0);
        const pct = total ? Math.round((done / total) * 100) : 0;
        const badge = BADGE_CLASS[j.status] || 'queued';
        // total_candidates is 0 until the worker has filtered + capped the file.
        const progressText = total
          ? `${done.toLocaleString(LOCALE)} / ${total.toLocaleString(LOCALE)} (${pct}%)`
          : j.status === 'completed'
            ? 'sin transcripciones nuevas'
            : 'seleccionando transcripciones…';
        const skippedNote = j.skipped_existing
          ? ` · ${j.skipped_existing.toLocaleString(LOCALE)} ya enriquecidas`
          : '';
        const failedNote =
          j.failed_count > 0
            ? ` · <span style="color:var(--flare)">${j.failed_count} con error</span>`
            : '';
        // A fatal `error` explains a failed job; `last_error` explains a job
        // that is still running but not advancing — the case that used to show
        // "running, 0/N" with nothing to go on. Show whichever exists.
        const message =
          j.status === 'failed' && j.error ? j.error : j.last_error ? j.last_error : '';
        const errNote = message
          ? `<div class="hint" style="color:var(--flare)">${escapeHtml(message)}</div>`
          : '';
        return `
          <tr>
            <td>${shortId(j._id || j.id)}</td>
            <td>${j.filename ? escapeHtml(j.filename) : '—'}</td>
            <td>
              <div class="progress"><div class="progress__bar" style="width:${pct}%"></div></div>
              <span class="hint">${progressText}${skippedNote}${failedNote}</span>
              ${errNote}
            </td>
            <td><span class="badge badge--${badge}">${j.status}</span></td>
            <td>${formatDate(j.created_at)}</td>
          </tr>
        `;
      })
      .join('');
    jobsNote.textContent = jobs.some((j) => ACTIVE_STATUSES.includes(j.status))
      ? 'Actualizando…'
      : '';
  }

  async function poll() {
    if (disposed) return;
    try {
      const jobs = await listJobs();
      if (disposed) return;
      renderJobs(jobs);
      if (jobs.some((j) => ACTIVE_STATUSES.includes(j.status))) {
        pollTimer = setTimeout(poll, POLL_INTERVAL_MS);
      } else {
        pollTimer = null;
      }
    } catch (err) {
      if (disposed) return;
      jobsNote.textContent = `No se pudieron cargar los jobs: ${err.message}`;
      pollTimer = setTimeout(poll, POLL_INTERVAL_MS);
    }
  }

  function startPolling() {
    if (pollTimer) clearTimeout(pollTimer);
    pollTimer = null;
    poll();
  }

  startPolling();

  return () => {
    disposed = true;
    if (pollTimer) clearTimeout(pollTimer);
  };
}

function shortId(id) {
  return id ? String(id).slice(-6) : '—';
}

// Job errors quote the model's own output and filenames come from the user;
// both land in an innerHTML template.
function escapeHtml(text) {
  const el = document.createElement('span');
  el.textContent = String(text);
  return el.innerHTML;
}

function formatDate(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString(LOCALE);
}
