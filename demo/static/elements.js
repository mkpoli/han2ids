export function selectElements(names) {
  return Object.fromEntries(names.map(name => [name, document.querySelector(`#${name.replace(/[A-Z]/g, c => `-${c.toLowerCase()}`)}`)]));
}
