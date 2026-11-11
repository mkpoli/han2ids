import { IDC } from './ids.js';

export function renderIds(element, text) {
  const fragment = document.createDocumentFragment();
  let buffer = '';
  for (const char of text) {
    if (IDC.test(char)) {
      if (buffer) fragment.append(document.createTextNode(buffer));
      buffer = '';
      const span = document.createElement('span');
      span.className = 'idc';
      span.textContent = char;
      fragment.append(span);
    } else {
      buffer += char;
    }
  }
  if (buffer) fragment.append(document.createTextNode(buffer));
  element.replaceChildren(fragment);
}
