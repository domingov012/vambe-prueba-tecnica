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

// Backend ThinkingLevel enum -> Spanish label for the jobs table.
const THINKING_LABELS = {
  minimal: 'razonamiento mínimo',
  high: 'razonamiento alto',
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

      <div class="opts">
        <label class="field">
          <span class="field__label">Nivel de razonamiento</span>
          <select class="field__control" id="opt-thinking">
            <option value="">Por defecto del servidor</option>
            <option value="minimal">Mínimo</option>
            <option value="high">Alto</option>
          </select>
        </label>
        <label class="field">
          <span class="field__label">Tamaño de batch</span>
          <input class="field__control" id="opt-batch" type="number" min="1" step="1"
                 inputmode="numeric" placeholder="10" />
        </label>
        <label class="field">
          <span class="field__label">Máx. transcripciones</span>
          <input class="field__control" id="opt-max" type="number" min="1" step="1"
                 inputmode="numeric" placeholder="100" />
        </label>
      </div>
      <p class="hint">Deja un campo vacío para usar el valor por defecto del servidor.</p>

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
          <tr><th>Job</th><th>Archivo</th><th>Parámetros</th><th>Progreso</th><th>Estado</th><th>Inicio</th></tr>
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
  const thinkingSelect = page.querySelector('#opt-thinking');
  const batchInput = page.querySelector('#opt-batch');
  const maxInput = page.querySelector('#opt-max');
  const optControls = [thinkingSelect, batchInput, maxInput];
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
    optControls.forEach((el) => {
      el.disabled = uploading;
    });
    startBtn.textContent = uploading ? 'Subiendo…' : 'Iniciar enriquecimiento';
  }

  // Read the three job-option controls. Returns null (and shows why) when a
  // number field holds something that isn't a positive integer — the backend
  // would 422 anyway, but catching it here keeps the message in Spanish.
  function readOptions() {
    const opts = { thinkingLevel: thinkingSelect.value || undefined };
    for (const [input, key, label] of [
      [batchInput, 'batchSize', 'tamaño de batch'],
      [maxInput, 'maxTranscripts', 'máx. transcripciones'],
    ]) {
      const raw = input.value.trim();
      if (!raw) continue;
      const value = Number(raw);
      if (!Number.isInteger(value) || value < 1) {
        uploadResult.innerHTML = `<p class="hint" style="color:var(--flare)">El ${label} debe ser un entero mayor que 0.</p>`;
        return null;
      }
      opts[key] = value;
    }
    return opts;
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

    uploadResult.innerHTML = '';
    const opts = readOptions();
    if (opts === null) return; // validation message already shown

    uploading = true;
    syncButtons();

    try {
      const { summary } = await uploadCsv(selectedFile, opts);
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
        const spinner = ACTIVE_STATUSES.includes(j.status)
          ? '<span class="spinner" aria-hidden="true"></span>'
          : '';
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
        const paramNotes = [
          `batch ${(j.batch_size ?? 0).toLocaleString(LOCALE)}`,
          `máx ${(j.max_transcripts ?? 0).toLocaleString(LOCALE)}`,
        ];
        if (j.thinking_level) {
          paramNotes.push(THINKING_LABELS[j.thinking_level] || j.thinking_level);
        }
        return `
          <tr>
            <td>${shortId(j._id || j.id)}</td>
            <td>${j.filename ? escapeHtml(j.filename) : '—'}</td>
            <td><span class="hint">${paramNotes.join(' · ')}</span></td>
            <td>
              <div class="progress"><div class="progress__bar" style="width:${pct}%"></div></div>
              <span class="hint">${progressText}${skippedNote}${failedNote}</span>
              ${errNote}
            </td>
            <td><span class="status-cell">${spinner}<span class="badge badge--${badge}">${j.status}</span></span></td>
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
