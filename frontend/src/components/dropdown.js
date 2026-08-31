// Dropdown selector — the second selector shape on the dashboard, for the one
// case a segmented control can't take: picking one of ~15 sectors.
//
// A native <select> rather than a custom listbox. It gets keyboard support,
// type-ahead and the platform's own overlay for free, and on a phone it opens
// the OS picker instead of a list that would run off the bottom of the section.
// Only the closed state is styled — an <option> can't be, and faking one to
// match the palette is not worth a re-implementation of a control the browser
// already ships.

export function createDropdown({ label, options, value, onChange }) {
  const el = document.createElement('label');
  el.className = 'drop';

  const caption = document.createElement('span');
  caption.className = 'drop__label';
  caption.textContent = label;

  const select = document.createElement('select');
  select.className = 'drop__select';
  select.addEventListener('change', () => onChange(select.value));

  el.append(caption, select);

  function setOptions(next, selected) {
    select.innerHTML = '';
    next.forEach((option) => {
      const node = document.createElement('option');
      node.value = option.value;
      node.textContent = option.label;
      select.appendChild(node);
    });
    select.value = selected ?? next[0]?.value ?? '';
  }

  setOptions(options, value);

  return { el, setOptions, get value() { return select.value; } };
}
