---
name: behavioral-inference-validation
description: When inferring character intent or behavioral patterns from video, validate inferences against cumulative observed actions rather than isolated moments or assumptions.
category: video_understanding
---

## Validate Behavioral Inferences Against Full Action Sequence

1. Collect all observed actions and interactions throughout the video, not just isolated moments.
2. Identify the overall pattern: Are actions goal-directed, exploratory, disorganized, efficient, etc.?
3. Match the inferred behavioral pattern to the option that best summarizes the cumulative evidence.
4. Reject inferences based on single actions (e.g., "picking up a fork" or "taking a break") if the overall pattern contradicts that inference.
5. Prioritize options describing ongoing, consistent patterns over options describing isolated events or exceptions.

**Example:**
Observed actions: Character explores multiple rooms, interacts with various objects, examines surroundings methodically.
Correct inference: "exploring the house and interacting with objects" (pattern-based).
Incorrect inference: "trying to turn off lights" or "trying to escape" (isolated action or assumption).

**Anti-pattern:** Inferring intent from a single action or moment without considering the full sequence of behaviors and the overall context of the video.
