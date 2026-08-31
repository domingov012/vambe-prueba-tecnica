// Segmented control — the one selector shape the dashboard uses, whether it's
// six close-rate dimensions or a two-way channel toggle. Every option stays
// visible, so switching a view never costs an extra click.
//
// Roving-tabindex tablist: arrows move between options, only the active one is
// in the tab order.

export function createSegmented(options, { value, onChange, variant } = {}) {
  const el = document.createElement('div');
  el.className = 'seg' + (variant === 'quiet' ? ' seg--quiet' : '');
  el.setAttribute('role', 'tablist');

  const buttons = options.map((option) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'seg__opt';
    button.setAttribute('role', 'tab');
    button.textContent = option.label;
    button.dataset.value = option.value;
    button.addEventListener('click', () => {
      if (option.value === current) return;
      setValue(option.value);
      onChange(option.value);
    });
    el.appendChild(button);
    return button;
  });

  let current = value;

  function setValue(next) {
    current = next;
    buttons.forEach((button) => {
      const on = button.dataset.value === String(next);
      button.classList.toggle('seg__opt--on', on);
      button.setAttribute('aria-selected', String(on));
      button.tabIndex = on ? 0 : -1;
    });
  }

  el.addEventListener('keydown', (event) => {
    const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[event.key];
    if (!step) return;
    event.preventDefault();
    const index = buttons.findIndex((b) => b.dataset.value === String(current));
    const next = buttons[(index + step + buttons.length) % buttons.length];
    next.focus();
    next.click();
  });

  setValue(value);

  return { el, setValue };
}
