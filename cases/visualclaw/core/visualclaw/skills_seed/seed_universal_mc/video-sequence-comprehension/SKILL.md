---
name: video-sequence-comprehension
description: Trigger when analyzing multi-frame video sequences or action sequences to ensure the assistant correctly identifies the complete sequence of actions and their order rather than selecting incomplete or partially correct options.
category: video_understanding
---

## Comprehend Complete Action Sequences in Videos

1. **Identify all key frames**: Examine each image/frame sequentially to map out every distinct action step.
2. **Track action order**: Note the temporal sequence of actions—what happens first, second, third, etc.
3. **Match full sequences**: Compare the complete action sequence observed against all options, not just the first matching action.
4. **Verify endpoint**: Ensure the final state in the video matches the conclusion described in the correct answer option.
5. **Cross-check details**: Pay attention to specific objects, tools, and methods used (e.g., "rinses" vs. "puts in dryer").

**Example**: In the dog mat scenario, frames show: pickup → sink wash → rinse off. Option (E) matches this complete sequence. Option (B) incorrectly ends with "dryer," which is not shown.

**Anti-pattern**: Selecting an option because it mentions the first action (washing) without verifying the final action matches the video.
