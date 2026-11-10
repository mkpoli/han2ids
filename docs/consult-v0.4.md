# v0.4 consultation

Panel: fable, opus, astra, grok, muse, ember, deepseek.

| lane | result |
| --- | --- |
| deepseek | ok |
| muse | ok |
| fable | skipped at the quota gate |
| opus | skipped at the quota gate |
| astra | skipped at the quota gate |
| ember | returned empty |
| grok | OpenRouter 402, no credits |

## The finding

DeepSeek found that 4,274 of the 4,752 current test characters are in v0.1's training split. The
84.44% v0.1 score and the 90.17% v0.1+v0.3 oracle are leaked. Muse's recommendation to fine-tune v0.1
is therefore not usable. The clean baseline is v0.3 at 82.88%.

## Consensus

Both useful reports agree on continuing the clean model rather than reviving v0.1. DeepSeek's staged
plan is in `docs/v0.4-plan.md`: v0.4a, Jigmo specialist, font router, optional clean reranker.
Musa's beam/candidate display suggestion remains compatible with the final system.
