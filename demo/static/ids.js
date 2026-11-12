/* The IDS operand grammar, shared by the page and the decoder worker.
   Mirrors src/han2ids/grammar.py. */

export const IDC = /[⿰-⿿〾㇯]/;

export const ARITY = {
  '⿰': 2, '⿱': 2, '⿲': 3, '⿳': 3, '⿴': 2, '⿵': 2, '⿶': 2, '⿷': 2,
  '⿸': 2, '⿹': 2, '⿺': 2, '⿻': 2, '⿼': 2, '⿽': 2, '㇯': 2,
  '⿾': 1, '⿿': 1, '〾': 1,
};

/** Fill one operand slot and push an operator's operands. False when no slot was open. */
export function advance(stack, char) {
  while (stack.length && stack[stack.length - 1] === 0) stack.pop();
  if (!stack.length) return false;
  stack[stack.length - 1] -= 1;
  if (ARITY[char]) stack.push(ARITY[char]);
  while (stack.length && stack[stack.length - 1] === 0) stack.pop();
  return true;
}

const SELECTOR = /[\u{FE00}-\u{FE0F}\u{E0100}-\u{E01EF}]/u;

/** Tokens of a sequence: one per character, with variation selectors kept on their base. */
export function split(text) {
  const tokens = [];
  for (const char of text) {
    if (tokens.length && SELECTOR.test(char)) tokens[tokens.length - 1] += char;
    else tokens.push(char);
  }
  return tokens;
}

/** The reading with each printed form replaced by the component that stands for it. */
export function unify(text, forms) {
  return split(text).map(token => forms[token] ?? token.replace(SELECTOR, '')).join('');
}

/** Whether the text is a complete sequence: an operator first, every slot filled, none left over. */
export function validIds(text) {
  if (!text || !ARITY[[...text][0]]) return false;
  const stack = [1];
  for (const token of split(text)) {
    if (token.length > 1 && ARITY[token[0]]) return false;
    if (!advance(stack, token)) return false;
  }
  return stack.length === 0;
}
