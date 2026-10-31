---
title: What a trace can show
description: Self-reported steps, end-to-end evidence for closed products, and how the plugin relates to run mode's A/B tests.
---

## The agent reports its own steps

An MCP server sees only the calls an agent makes to it. HALO therefore cannot watch a product's memory or decisions from the inside. It receives the steps the agent chooses to log, and its report shows how those steps link. HALO checks the links, not whether the steps happened, and every report ends with that sentence.

Two habits keep a trace close to what the agent did:

- **Log in the flow.** A standing instruction makes the agent log each step while it works, in ordinary use and in the actions it starts by itself. Steps logged afterwards are still useful, and the agent should say so in the summary, as the dot in [ChatGPT dots](/HALO/connect/chatgpt-dots/) did.
- **Put HALO in the path where it can be.** When an action goes through HALO, for example a message that HALO delivers or a tool call that HALO forwards, HALO sees the action and its result without relying on the agent's report. Memory inside a closed product stays out of view either way.

## Closed products allow end-to-end evidence only

Most personal agents are products whose code is closed. For them, HALO can work only from the outside, with three kinds of evidence:

| Evidence | Source | Shows |
|---|---|---|
| Read mode | the product's documentation | which channels and steps the product says it has |
| The plugin | the steps the agent logs while it runs | which channels and steps appear in what it did |
| A/B at the product's boundary | the same inputs run with and without a control the product exposes | whether removing that control changes the output |

The third row is run mode applied end to end. A product exposes some switches: memory on or off, a plugin connected or not, feedback given or withheld. Running the same scripted inputs with a switch on and off, and letting a judge compare the outputs without knowing which run is which, tests the channel behind the switch.

## Why run mode is an A/B test

A source, or an agent's own log, can show that a channel exists. Neither shows that the channel matters. In the survey, AiGet passes the user profile to Action by two paths. Cutting either path alone left a blind judge without a clear preference, while cutting both made the judge prefer the original suggestions. Only a controlled comparison shows such effects. Run mode therefore keeps the inputs and the model fixed and removes one channel or evidence step at a time. With released code the cut happens inside the code, at the receiving end of the channel. With a closed product it can happen only at the product's boundary, which is why its evidence is end to end.

## Reading a report

- **Not observed is not absent.** An agent that keeps memory but never logged a recall in a later session shows no state durability in its trace.
- **A level is a lower bound.** It is the highest level the logged steps support.
- **A revision needs the agent as its author.** A rule the user wrote is not a revision by the agent, and a revision without the user's approval or bounds does not reach L5.

## Privacy and security

- The ledger stays on the machine that runs the server. Summaries should leave out secrets, passwords, and raw personal data, and the tool descriptions tell agents so.
- A hosted agent needs a public HTTPS address. `halo serve --public-host` serves the plugin under a random path segment, so only someone with the full address can reach it, and answers 404 everywhere else.
- Hosts may share chat content or memories with a connected plugin. ChatGPT says so when the plugin is connected. Disconnect the plugin in the host to stop it.
