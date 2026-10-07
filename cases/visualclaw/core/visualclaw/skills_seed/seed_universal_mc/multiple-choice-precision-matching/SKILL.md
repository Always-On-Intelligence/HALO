---
name: multiple-choice-precision-matching
description: When selecting from multiple-choice options about video content, perform exact matching between the question focus and the option text rather than selecting based on partial keyword overlap.
category: visual_reasoning
---

## Match Question Scope to Answer Precision

1. Identify what the question is asking:
   - Recurring actions? → Look for repeated patterns across the video
   - Key turning points? → Look for crucial moments, not routine actions
   - Overarching activity? → Look for the main shared activity, not individual actions
   - Core process? → Look for the essential steps, not all variations
2. Reject options that are too broad or include unrelated elements.
3. Reject options that describe only part of the activity or add contradictory details.
4. Cross-reference: Does this option directly answer the specific question asked?

**Example:** Question asks for "key turning points" → Option D ("walks, puts hands on knees, lifts hands") is routine movement, not a turning point. Option C ("tackles the ball") is a decisive moment.

**Anti-pattern:** Selecting an option because it mentions relevant words (e.g., "walking") without verifying it answers the actual question being asked (e.g., turning points vs. recurring actions).
