// Minimal hash-based router. Routes map a path to a render function that
// receives the mount element and returns an optional cleanup callback.

const routes = new Map();
let currentCleanup = null;

export function registerRoute(path, render) {
  routes.set(path, render);
}

function normalize(hash) {
  const path = (hash || '').replace(/^#/, '');
  return path === '' ? '/' : path;
}

export function currentPath() {
  return normalize(window.location.hash);
}

export function navigate(path) {
  window.location.hash = path;
}

export function startRouter(mountEl, notFound) {
  const handle = () => {
    const path = currentPath();
    const render = routes.get(path) || notFound;

    if (typeof currentCleanup === 'function') {
      currentCleanup();
      currentCleanup = null;
    }
    mountEl.innerHTML = '';
    currentCleanup = render(mountEl) || null;

    document.querySelectorAll('[data-route]').forEach((el) => {
      el.classList.toggle('nav__link--active', el.dataset.route === path);
    });
  };

  window.addEventListener('hashchange', handle);
  handle();
}
