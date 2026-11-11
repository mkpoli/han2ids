export function initTheme() {
  const themeRadios = [...document.querySelectorAll('input[name="theme"]')];

  function storedTheme() {
    try {
      const value = localStorage.getItem('han2ids:theme');
      return value === 'light' || value === 'dark' ? value : 'system';
    } catch {
      return 'system';
    }
  }

  function applyTheme(theme) {
    if (theme === 'light' || theme === 'dark') document.documentElement.dataset.theme = theme;
    else delete document.documentElement.dataset.theme;
    for (const radio of themeRadios) radio.checked = radio.value === theme;
  }

  for (const radio of themeRadios) {
    radio.addEventListener('change', () => {
      if (!radio.checked) return;
      applyTheme(radio.value);
      try {
        if (radio.value === 'system') localStorage.removeItem('han2ids:theme');
        else localStorage.setItem('han2ids:theme', radio.value);
      } catch {}
    });
  }

  applyTheme(storedTheme());
}
