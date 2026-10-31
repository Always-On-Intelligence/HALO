---
title: Agent instructions
description: A standing instruction that keeps an agent logging its loop while it works.
---

An agent logs to HALO only when it is told to. `halo_guide` returns the short version, and the server sends the same text as its MCP instructions. For an agent that should log over days, put a standing instruction in its memory or settings once, so it logs during ordinary use and in the actions it starts by itself.

```text title="Standing instruction"
From now on, log each step of your work to HALO while you do it, in a few words:
- halo_observe when you take in something new, such as my message, a page, or a tool result.
- halo_remember when you keep something for later conversations, and halo_recall when you look it up.
- halo_act when you do something for me or decide to stay silent. Use trigger "self" when you
  decided on your own between my requests, and "request" when I asked or set the time.
- halo_outcome when you learn how one of your actions went. Pass the action's id as about.
- halo_revise when you change your own way of working for the future.
Always pass uses with the ids of the earlier steps you relied on. Use one session label per
conversation or wake-up, and agent "<name>". Log only what really happened, mark anything logged
afterwards as such, and leave out secrets and private text.
```

## Habits that make a trace useful

- **Label sessions consistently.** State durability is read across sessions, so a session per conversation or per scheduled wake-up is enough. Reusing one label for everything hides it.
- **Log silence.** Deciding not to act is an Action with form `silence`. For an always-on agent, a decision to wait is part of operational continuity.
- **Separate content from revisions.** A new fact or preference is a `remember`. A rule the agent will apply in future runs is a `revise`.
- **Name the user's role.** A change the user wrote is logged with `made_by: user`. A change the agent made after the user approved it is `made_by: agent` with governance `approved`.
