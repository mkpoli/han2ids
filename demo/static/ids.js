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

/** Whether the text is a complete sequence: an operator first, every slot filled, none left over. */
export function validIds(text) {
  if (!text || !ARITY[[...text][0]]) return false;
  const stack = [1];
  for (const char of text) {
    if (!advance(stack, char)) return false;
  }
  return stack.length === 0;
}
