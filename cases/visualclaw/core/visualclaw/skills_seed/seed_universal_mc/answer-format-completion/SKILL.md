---
name: answer-format-completion
description: Trigger when the assistant begins generating explanatory text instead of providing a direct answer in multiple-choice scenarios, ensuring responses match the expected format.
category: common_mistakes
---

## Provide Complete Direct Answers

1. **Recognize multiple-choice format**: When presented with options (A), (B), (C), (D), (E), a single letter answer is expected.
2. **Commit to a choice**: Select the single best option based on visual and contextual analysis.
3. **Deliver answer first**: Provide the letter choice immediately, not a partial explanation.
4. **Only elaborate if requested**: Add reasoning only if the prompt asks "why" or "explain"—not by default.
5. **Avoid incomplete responses**: Do not start analysis and trail off; complete the answer.

**Example**: When asked to choose between dog mat washing outcomes, respond with "(E)" not "Based on the visual evidence in the keyframes, the person is seen washing..."

**Anti-pattern**: Beginning a multi-sentence explanation when a single letter choice is required, leaving the response incomplete or ambiguous.
