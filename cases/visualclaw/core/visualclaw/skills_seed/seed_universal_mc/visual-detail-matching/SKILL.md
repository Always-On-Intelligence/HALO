---
name: visual-detail-matching
description: Trigger when multiple-choice answers contain similar but subtly different details to prevent selecting plausible-sounding options that don't match the actual visual evidence.
category: visual_reasoning
---

## Match Visual Details Precisely Against Options

1. **Extract specific visual elements**: Identify concrete details from images—object types, colors, materials, tools, locations (sink, floor, cup, etc.).
2. **Compare option-by-option**: For each option, check if every stated detail appears in the visual evidence.
3. **Flag contradictions**: Mark options that describe actions or objects NOT visible in the frames.
4. **Prioritize precision over plausibility**: Choose based on what you see, not what sounds reasonable.
5. **Verify descriptive claims**: If an option makes a judgment (e.g., "professional," "efficient," "gracefully"), check if the visual evidence supports that characterization.

**Example**: In the woodworker scenario, option (D) states "few adjustments"—this requires observing actual adjustment attempts in the frames. Option (A) or (C) may sound professional but lack visual support.

**Anti-pattern**: Selecting an answer because it uses professional language or sounds logical without confirming visual evidence supports every claim.
