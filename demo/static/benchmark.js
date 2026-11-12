import { initTheme } from './theme.js';
import { createLanguage } from './language.js';

const MEASURES = ['sameAxis', 'exact', 'family', 'f1', 'tree'];
const COLUMNS = [...MEASURES, 'top5', 'expanded'];
const els = {
  measures: document.querySelector('#measures'),
  tracks: document.querySelector('#tracks'),
  tip: document.querySelector('#tip'),
};
let data = null;
let measure = MEASURES[0];

initTheme();
const language = createLanguage({ onTranslationsChanged: render });
const t = (...args) => language.t(...args);
language.start();

fetch(new URL('./benchmark.json', import.meta.url))
  .then(response => (response.ok ? response.json() : Promise.reject(new Error(`HTTP ${response.status}`))))
  .then(loaded => {
    data = loaded;
    render();
  })
  .catch(() => {
    els.tracks.textContent = t('bench.failed');
  });

function element(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === 'dataset') Object.assign(node.dataset, value);
    else if (key in node) node[key] = value;
    else node.setAttribute(key, value);
  }
  node.append(...children);
  return node;
}

const percent = value => `${value.toFixed(2)}%`;
const span = ([low, high]) => `${low.toFixed(2)}–${high.toFixed(2)}%`;
const shortName = reader => (reader.group === 'han2ids' ? reader.name.replace('han2ids ', '') : reader.name);

function renderMeasures() {
  const legend = els.measures.querySelector('legend');
  els.measures.replaceChildren(legend, ...MEASURES.map(key => {
    const input = element('input', { type: 'radio', name: 'measure', value: key, checked: key === measure });
    input.addEventListener('change', () => {
      measure = key;
      render();
    });
    return element('label', { className: 'ui-segment' }, [
      input,
      element('span', { className: 'ui-segment-face', textContent: t(`bench.measure.${key}`) }),
    ]);
  }));
}

function showTip(row, reader, scores) {
  const pairs = COLUMNS.filter(key => key in scores).flatMap(key => [
    element('span', { textContent: t(`bench.measure.${key}`) }),
    element('span', { textContent: key === 'expanded' ? span(scores.expanded) : percent(scores[key]) }),
  ]);
  els.tip.replaceChildren(element('strong', { textContent: reader.name }), ...pairs);
  els.tip.hidden = false;
  const box = row.getBoundingClientRect();
  const tip = els.tip.getBoundingClientRect();
  const left = Math.min(Math.max(8, box.right - tip.width), innerWidth - tip.width - 8);
  const above = box.top - tip.height - 6;
  els.tip.style.left = `${left}px`;
  els.tip.style.top = `${above > 8 ? above : box.bottom + 6}px`;
}

function panel(track) {
  const shown = track.id === 'candidates' ? 'top5' : measure;
  const latest = data.readers.filter(reader => reader.group === 'han2ids' && track.rows[reader.id]).at(-1);
  const rows = data.readers.filter(reader => track.rows[reader.id]).map(reader => {
    const scores = track.rows[reader.id];
    const [low, high] = scores.expanded;
    const row = element('li', {
      className: 'bench-row', tabIndex: 0,
      dataset: { group: reader.group, overlap: String(reader.overlap), latest: String(reader === latest) },
    }, [
      element('span', { className: 'bench-name', textContent: shortName(reader), title: reader.name }),
      element('span', { className: 'bench-track' }, [
        element('span', { className: 'bench-bar', style: `inline-size:${scores[shown]}%` }),
        element('span', { className: 'bench-span', style: `inset-inline-start:${low}%;inline-size:${high - low}%` }),
      ]),
      element('span', { className: 'bench-value', textContent: percent(scores[shown]) }),
    ]);
    row.setAttribute('aria-label', `${reader.name}: ${t(`bench.measure.${shown}`)} ${percent(scores[shown])}, ${t('bench.range')} ${span(scores.expanded)}`);
    for (const type of ['pointerenter', 'focus']) row.addEventListener(type, () => showTip(row, reader, scores));
    for (const type of ['pointerleave', 'blur']) row.addEventListener(type, () => { els.tip.hidden = true; });
    return row;
  });

  const columns = COLUMNS.filter(key => key in Object.values(track.rows)[0]);
  const table = element('table', {}, [
    element('thead', {}, [element('tr', {}, [
      element('th', { scope: 'col', textContent: t('bench.reader') }),
      ...columns.map(key => element('th', { scope: 'col', textContent: t(`bench.measure.${key}`) })),
    ])]),
    element('tbody', {}, data.readers.filter(reader => track.rows[reader.id]).map(reader => element('tr', {}, [
      element('td', { textContent: reader.name }),
      ...columns.map(key => element('td', {
        textContent: key === 'expanded' ? span(track.rows[reader.id].expanded) : percent(track.rows[reader.id][key]),
      })),
    ]))),
  ]);

  return element('section', { className: 'ui-card bench-panel' }, [
    element('div', { className: 'bench-panel-head' }, [
      element('h2', { textContent: t(`bench.track.${track.id}`) }),
      element('div', { className: 'bench-chips' }, [
        element('span', { className: 'ui-chip', textContent: t(`bench.measure.${shown}`) }),
        element('span', {
          className: 'ui-chip', textContent: t(track.reviewed ? 'bench.reviewed' : 'bench.unreviewed'),
          dataset: track.reviewed ? { variant: 'accent' } : {},
        }),
      ]),
      element('span', { className: 'bench-count', textContent: t('bench.count', {
        images: track.images.toLocaleString(document.documentElement.lang),
        characters: track.characters.toLocaleString(document.documentElement.lang),
      }) }),
    ]),
    element('ul', { className: 'bench-chart' }, rows),
    element('div', { className: 'bench-axis', ariaHidden: 'true' }, [
      element('span', { className: 'bench-ticks' }, [0, 25, 50, 75, 100].map(tick => element('span', { textContent: String(tick) }))),
    ]),
    element('details', { className: 'bench-table', open: Boolean(document.querySelector(`#table-${track.id}`)?.open), id: `table-${track.id}` }, [
      element('summary', { textContent: t('bench.table') }),
      element('div', { className: 'bench-scroll' }, [table]),
    ]),
  ]);
}

function render() {
  renderMeasures();
  if (!data) return;
  els.tip.hidden = true;
  els.tracks.replaceChildren(...data.tracks.map(panel));
}
