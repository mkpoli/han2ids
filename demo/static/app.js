import { initTheme } from './theme.js';
import { createLanguage } from './language.js';
import { createFiles } from './files.js';
import { createStage } from './stage.js';
import { createQueue } from './queue.js';
import { createReading } from './reading.js';
import { createDisplay } from './display.js';
import { RAW } from './prepare.js';

initTheme();
const language = createLanguage({ onTranslationsChanged() {
  queue.renderQueue(); stage.renderStage(); display.renderResult(); display.clearLive();
} });
const t = (...args) => language.t(...args);
const files = createFiles({ t, onError: error => reading.showError(error), onSourceLoaded(source) {
  display.clearError();
  const items = queue.add(source);
  queue.selectItem(items[0].id);
  queue.renderQueue();
  reading.enqueue(items);
} });
const queue = createQueue({ t, getSource: id => files.getSource(id), onSelect({ scroll }) {
  display.clearCopied();
  reading.cancelScheduled();
  stage.renderStage();
  queue.renderQueue({ scroll });
  display.renderResult();
} });
const stage = createStage({
  t, selectedItem: () => queue.selectedItem(), itemsOf: id => queue.itemsOf(id),
  getSource: id => files.getSource(id), sourceUrl: source => files.sourceUrl(source),
  bitmapFor: source => files.bitmapFor(source), selectItem: id => queue.selectItem(id),
  scheduleRead: delay => reading.scheduleRead(delay), cancelScheduled: () => reading.cancelScheduled(),
  onCropChanged: item => reading.cropChanged(item), showError: error => reading.showError(error),
  clearError: () => display.clearError(),
  onCleanChanged() {
    reading.enqueue(queue.all());
  },
  onQuickCut(source, found) {
    files.updateAnalysis(source, found);
    const items = queue.replaceSource(source, found.boxes);
    queue.selectItem(items[0].id);
    queue.renderQueue();
    reading.enqueue(items);
  },
});
const display = createDisplay({ t, selectedItem: () => queue.selectedItem(),
  getSource: id => files.getSource(id), itemsOf: id => queue.itemsOf(id), isLoading: () => reading.isLoading() });
const reading = createReading({
  selectedItem: () => queue.selectedItem(), byId: id => queue.byId(id), isDragging: () => stage.isDragging(),
  getSource: id => files.getSource(id), bitmapFor: source => files.bitmapFor(source),
  makeThumb: (item, view) => queue.makeThumb(item, view),
  prepareOptions: () => (stage.isClean() ? {} : RAW),
  showModelProgress: fraction => display.showModelProgress(fraction), hideModelProgress: () => display.hideModelProgress(),
  setStatus: (key, kind) => display.setStatus(key, kind), showError: error => display.showError(error),
  announceReading: item => display.announceReading(item),
  touch(item) {
    queue.updateRow(item); stage.renderBoxes();
    if (item.id === queue.selectedItem()?.id) display.renderResult();
  },
  cropInvalidated(item) {
    display.clearCopied();
    queue.updateRow(item); stage.renderBoxes(); display.renderResult();
  },
  loadInference: () => import('./inference.js'),
});
language.start();
