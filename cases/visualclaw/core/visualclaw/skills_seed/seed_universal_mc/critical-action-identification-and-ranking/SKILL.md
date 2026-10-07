---
name: critical-action-identification-and-ranking
description: When asked to identify critical actions in a video, distinguish between preparatory/support actions and core actions that directly contribute to the main objective, and rank them by significance to the end goal.
category: video_understanding
---

## Identify and Rank Actions by Contribution to Main Goal

1. **Define the end goal**: Determine what the person is ultimately trying to achieve (e.g., plant seedlings, fix a frame, complete a wood project).
2. **Map all visible actions**: List every action performed in sequence.
3. **Classify each action**:
   - **Core actions**: Directly move toward the end goal (e.g., picking up seedlings, dropping them in soil)
   - **Support actions**: Enable core actions but are not themselves the goal (e.g., picking up a trowel, holding a sack)
4. **Select critical actions**: Choose the core actions that most directly achieve the objective, not the preparatory steps.
5. **Verify importance**: Ask: "If this action were skipped, would the main goal still be accomplished?" Core actions fail this test; support actions pass it.

**Example**: In Failure 5, the assistant focused on "picking the trowel" and "holding the sack," which are preparatory. The critical actions were "picking up seedlings" and "dropping them in the container"—the actions that actually plant them.

**Anti-pattern**: Confusing preparatory or support actions with the core actions that achieve the primary objective.
