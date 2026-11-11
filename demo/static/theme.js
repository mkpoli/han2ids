export function initTheme() {
  const themeRadios = [...document.querySelectorAll('input[name="theme"]')];
  const themeMeta = document.querySelector('meta[name="color-scheme"]');

  function storedTheme() {
    try {
      const value = localStorage.getItem('han2ids:theme');
      return value === 'light' || value === 'dark' ? value : 'system';
    } catch {
      return 'system';
    }
  }

  function applyTheme(theme) {
    themeMeta.content = theme === 'light' || theme === 'dark' ? theme : 'light dark';
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

  window.addEventListener('storage', event => {
    try {
      if (event.storageArea === localStorage && (event.key === 'han2ids:theme' || event.key === null)) {
        applyTheme(storedTheme());
      }
    } catch {}
  });

  applyTheme(storedTheme());
}
