// Persistent top navigation, rendered once outside the router outlet.

const LINKS = [
  { path: '/', label: 'Carga de datos' },
  { path: '/dashboard', label: 'Dashboard' },
];

export function renderNav(container) {
  const nav = document.createElement('nav');
  nav.className = 'nav';

  const brand = document.createElement('span');
  brand.className = 'nav__brand';
  brand.textContent = 'Vambe';
  nav.appendChild(brand);

  LINKS.forEach(({ path, label }) => {
    const a = document.createElement('a');
    a.className = 'nav__link';
    a.href = `#${path}`;
    a.dataset.route = path;
    a.textContent = label;
    nav.appendChild(a);
  });

  container.appendChild(nav);
}
