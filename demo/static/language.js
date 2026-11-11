import { selectElements } from './elements.js';
import { DEFAULT_LOCALE, LOCALES, matchLocale } from './i18n.js';

export function createLanguage(deps, els = selectElements(['languageList', 'languageButton', 'languageLabel', 'languageCode', 'languageMenu'])) {
  let locale = DEFAULT_LOCALE;
  let messages = LOCALES[locale].messages;

  function t(key, params = {}) {
    let text = messages[key] ?? LOCALES[DEFAULT_LOCALE].messages[key] ?? key;
    for (const [name, value] of Object.entries(params)) text = text.split(`{${name}}`).join(String(value));
    return text;
  }

  function storedLanguage() {
    try {
      return localStorage.getItem('han2ids:lang');
    } catch {
      return null;
    }
  }

  function initialLocale() {
    const query = new URLSearchParams(location.search).get('lang');
    const candidates = [query, storedLanguage(), ...(navigator.languages ?? []), navigator.language];
    for (const candidate of candidates) {
      const match = matchLocale(candidate);
      if (match) return match;
    }
    return DEFAULT_LOCALE;
  }

  function setLocale(value, { persist = true } = {}) {
    locale = LOCALES[value] ? value : DEFAULT_LOCALE;
    messages = LOCALES[locale].messages;
    if (persist) {
      try {
        localStorage.setItem('han2ids:lang', locale);
        const url = new URL(location.href);
        url.searchParams.set('lang', locale);
        history.replaceState(null, '', url);
      } catch {}
    }
    applyTranslations();
  }

  function applyTranslations() {
    document.documentElement.lang = LOCALES[locale].htmlLang;
    document.title = t('meta.title');
    document.querySelector('meta[name="description"]')?.setAttribute('content', t('meta.description'));
    for (const node of document.querySelectorAll('[data-i18n]')) node.textContent = t(node.dataset.i18n);
    for (const node of document.querySelectorAll('[data-i18n-aria]')) node.setAttribute('aria-label', t(node.dataset.i18nAria));
    for (const node of document.querySelectorAll('[data-i18n-title]')) node.title = t(node.dataset.i18nTitle);
    for (const node of document.querySelectorAll('[data-i18n-alt]')) node.alt = t(node.dataset.i18nAlt);
    renderLanguage();
    deps.onTranslationsChanged();
  }

  function languageOptions() {
    return [...els.languageList.querySelectorAll('[role="option"]')];
  }

  function selectedLanguageOption() {
    return languageOptions().find(option => option.getAttribute('aria-selected') === 'true');
  }

  function renderLanguage() {
    const language = LOCALES[locale];
    const label = `${t('language.label')}: ${language.label}`;
    els.languageButton.setAttribute('aria-label', label);
    els.languageButton.title = label;
    els.languageLabel.textContent = language.label;
    els.languageCode.textContent = language.code;
    els.languageList.setAttribute('aria-label', t('language.label'));
    for (const option of languageOptions()) {
      option.setAttribute('aria-selected', String(option.dataset.value === locale));
    }
  }

  function openLanguage() {
    if (els.languageButton.disabled) return;
    els.languageList.hidden = false;
    els.languageButton.setAttribute('aria-expanded', 'true');
    requestAnimationFrame(() => (selectedLanguageOption() ?? languageOptions()[0])?.focus());
  }

  function closeLanguage(refocus = false) {
    els.languageList.hidden = true;
    els.languageButton.setAttribute('aria-expanded', 'false');
    if (refocus) els.languageButton.focus();
  }

  function chooseLanguage(option) {
    if (!option) return;
    setLocale(option.dataset.value);
    closeLanguage(true);
  }

  els.languageButton.addEventListener('click', () => {
    if (els.languageList.hidden) openLanguage();
    else closeLanguage();
  });

  els.languageButton.addEventListener('keydown', event => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp' || event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      openLanguage();
    } else if (event.key === 'Escape' && !els.languageList.hidden) {
      event.preventDefault();
      closeLanguage(true);
    }
  });

  els.languageList.addEventListener('keydown', event => {
    const options = languageOptions();
    const at = options.indexOf(document.activeElement);
    if (event.key === 'Escape') {
      event.preventDefault();
      closeLanguage(true);
    } else if (event.key === 'Tab') {
      closeLanguage(true);
    } else if (event.key === 'Home' || event.key === 'End') {
      event.preventDefault();
      options[event.key === 'Home' ? 0 : options.length - 1]?.focus();
    } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      const step = event.key === 'ArrowDown' ? 1 : -1;
      options[(at + step + options.length) % options.length]?.focus();
    } else if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      chooseLanguage(document.activeElement);
    }
  });

  for (const option of languageOptions()) {
    option.addEventListener('click', () => chooseLanguage(option));
  }

  document.addEventListener('pointerdown', event => {
    if (!els.languageList.hidden && !els.languageMenu.contains(event.target)) closeLanguage();
  });

  return { t, start: () => setLocale(initialLocale(), { persist: false }) };
}
