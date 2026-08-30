import './style.css';
import { registerRoute, startRouter } from './router.js';
import { renderNav } from './components/nav.js';
import { renderUploadPage } from './pages/upload.js';
import { renderDashboardPage } from './pages/dashboard.js';

const app = document.querySelector('#app');

renderNav(app);

const outlet = document.createElement('div');
outlet.id = 'outlet';
outlet.style.flex = '1';
outlet.style.display = 'flex';
outlet.style.flexDirection = 'column';
app.appendChild(outlet);

registerRoute('/', renderUploadPage);
registerRoute('/dashboard', renderDashboardPage);

function notFound(mount) {
  const p = document.createElement('div');
  p.className = 'page';
  p.innerHTML = '<h1 class="page__title">Not found</h1><p class="page__subtitle">No page for this route.</p>';
  mount.appendChild(p);
}

startRouter(outlet, notFound);
