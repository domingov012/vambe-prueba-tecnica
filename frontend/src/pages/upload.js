// Data Upload page — CSV upload + LLM-enhancement job list.
// No backend yet: uploads are captured client-side and jobs are mock data
// that simulate progress so the layout can be built against realistic state.

const MOCK_JOBS = [
  { id: 'job_1a2b', file: 'vambe_clients_10k.csv', rows: 10000, done: 10000, status: 'done', started: '2026-08-29 15:12' },
  { id: 'job_3c4d', file: 'clients_batch_feb.csv', rows: 4200, done: 1830, status: 'running', started: '2026-08-30 09:41' },
  { id: 'job_5e6f', file: 'clients_batch_mar.csv', rows: 900, done: 0, status: 'queued', started: '2026-08-30 09:44' },
];

export function renderUploadPage(mount) {
  const page = document.createElement('div');
  page.className = 'page';
  page.innerHTML = `
    <h1 class="page__title">Data Upload</h1>
    <p class="page__subtitle">Upload a CSV of client meeting transcripts and track LLM-enhancement jobs.</p>

    <div class="card">
      <h2 class="card__title">Upload CSV</h2>
      <div class="dropzone" id="dropzone">
        <p><strong>Drop a .csv file here</strong> or click to browse</p>
        <p class="hint">Expected columns: Nombre, Correo Electronico, Numero de Telefono, Fecha de la Reunion, Vendedor asignado, closed, Transcripcion</p>
        <input type="file" id="file-input" accept=".csv,text/csv" hidden />
      </div>
      <div id="file-info"></div>
      <div style="margin-top:16px; display:flex; gap:10px;">
        <button class="btn" id="start-btn" disabled>Start enhancement</button>
        <button class="btn btn--ghost" id="clear-btn" disabled>Clear</button>
      </div>
    </div>

    <div class="card">
      <h2 class="card__title">Enhancement jobs</h2>
      <table class="table">
        <thead>
          <tr><th>Job</th><th>File</th><th>Progress</th><th>Status</th><th>Started</th></tr>
        </thead>
        <tbody id="jobs-body"></tbody>
      </table>
      <p class="hint">Showing placeholder data — not yet connected to the backend.</p>
    </div>
  `;
  mount.appendChild(page);

  const dropzone = page.querySelector('#dropzone');
  const fileInput = page.querySelector('#file-input');
  const fileInfo = page.querySelector('#file-info');
  const startBtn = page.querySelector('#start-btn');
  const clearBtn = page.querySelector('#clear-btn');
  const jobsBody = page.querySelector('#jobs-body');

  let selectedFile = null;

  function setFile(file) {
    if (file && !file.name.toLowerCase().endsWith('.csv')) {
      fileInfo.innerHTML = '<div class="file-pill" style="color:var(--err)">Not a .csv file</div>';
      selectedFile = null;
      startBtn.disabled = true;
      clearBtn.disabled = true;
      return;
    }
    selectedFile = file || null;
    if (selectedFile) {
      const kb = (selectedFile.size / 1024).toFixed(1);
      fileInfo.innerHTML = `<div class="file-pill">📄 ${selectedFile.name} · ${kb} KB</div>`;
      startBtn.disabled = false;
      clearBtn.disabled = false;
    } else {
      fileInfo.innerHTML = '';
      startBtn.disabled = true;
      clearBtn.disabled = true;
    }
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
  dropzone.addEventListener('drop', (e) => {
    const file = e.dataTransfer.files[0];
    setFile(file);
  });

  clearBtn.addEventListener('click', () => {
    fileInput.value = '';
    setFile(null);
  });

  startBtn.addEventListener('click', () => {
    // Placeholder: no upload yet. Add a local mock job to visualise the flow.
    MOCK_JOBS.unshift({
      id: 'job_' + Math.random().toString(16).slice(2, 6),
      file: selectedFile.name,
      rows: 0,
      done: 0,
      status: 'queued',
      started: new Date().toISOString().slice(0, 16).replace('T', ' '),
    });
    fileInput.value = '';
    setFile(null);
    renderJobs();
  });

  function renderJobs() {
    jobsBody.innerHTML = MOCK_JOBS.map((j) => {
      const pct = j.rows ? Math.round((j.done / j.rows) * 100) : 0;
      return `
        <tr>
          <td>${j.id}</td>
          <td>${j.file}</td>
          <td>
            <div class="progress"><div class="progress__bar" style="width:${pct}%"></div></div>
            <span class="hint">${j.done.toLocaleString()} / ${j.rows.toLocaleString()} (${pct}%)</span>
          </td>
          <td><span class="badge badge--${j.status}">${j.status}</span></td>
          <td>${j.started}</td>
        </tr>
      `;
    }).join('');
  }

  renderJobs();

  // Simulate the one running job advancing, so the UI feels alive.
  const timer = setInterval(() => {
    const running = MOCK_JOBS.find((j) => j.status === 'running');
    if (running) {
      running.done = Math.min(running.rows, running.done + 120);
      if (running.done >= running.rows) running.status = 'done';
      renderJobs();
    }
  }, 1500);

  return () => clearInterval(timer);
}
