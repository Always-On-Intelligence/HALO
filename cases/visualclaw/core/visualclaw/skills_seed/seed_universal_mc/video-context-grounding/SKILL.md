---
name: video-context-grounding
description: When answering video comprehension questions, explicitly reference observed actions and visual evidence from the video before selecting an answer option.
category: video_understanding
---

## Ground Answers in Video Evidence

1. Before selecting any multiple-choice answer, identify what you actually observe happening in the video (specific actions, objects, sequences).
2. Match the observed evidence directly to answer options—look for exact correspondence, not paraphrasing or inference.
3. Reject options that describe actions you did not see, even if they sound plausible or well-written.
4. For questions about "repetitive actions" or "key developments," explicitly list which actions appeared multiple times or were central to the narrative.
5. State your reasoning: "The video shows [specific action]. This matches option [X] because [direct evidence]."

**Example:**
Question: What repetitive actions were important?
Observed: Sewing occurred twice; cutting occurred once.
Correct match: Option (E) mentions both sewing and cutting as repeated/important.
Incorrect match: Option (A) mentions only alignment—observed only once, not repetitive.

**Anti-pattern:** Selecting an answer based on grammatical quality, length, or general plausibility without verifying it matches what is actually visible in the video.
