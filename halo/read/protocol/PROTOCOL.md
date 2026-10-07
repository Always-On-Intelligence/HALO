# HALO read-mode protocol

This protocol is given to every oversight agent in read mode. Each agent reviews one
work on its own, from the work's primary sources, and returns one JSON object that
follows `halo/read/schema.json`. Three agents review every work, and a majority
vote decides each cell (see `halo/read/vote.py`).

## The framework in one paragraph

An always-on personal service is a loop of three functional modules.
- **Sensing** acquires and interprets current observations, including user input,
  sensor streams, screen state, external events, and observed execution state.
- **Memory** retains information across interactions.
- **Action** selects the service's behavior: silence, communication, preparation, or
  execution.

Assign operations by function, not by component name. One model, tool, shared
context, or controller may realize several roles. A *coupling channel* is a
directed information flow in which one module supplies information that another
module uses for its decisions or state updates.

Of the six channels, the basic S→A path (current input reaching Action) is
present in every agent system and is not reviewed. You review the other five.

## The five channels you review

| Channel | Reported when the source describes… |
|---|---|
| **S→M** | sensed or user-supplied evidence delivered to Memory for admission, integration, or correction. A static benchmark profile alone does not establish a write path. |
| **M→A** | retained information delivered to Action decisions about timing, content, effector, commitment, preparation, execution, or silence. |
| **A→S** | intentions, plans, information needs, or execution state from Action that guide Sensing targets, acquisition, interpretation, or expected-effect checks. A grader outside the service is not an in-system flow. |
| **M→S** | retained priors supplied to Sensing for sampling, attention, compression, or interpretation. Answer-time retrieval alone is M→A. A memory-guided Action decision that requests a new observation is the composition M→A→S. Do not mark M→S from that composition alone. |
| **A→M** | action context, plans, trajectories, assistant utterances, execution records, or associated outcomes delivered to Memory for retention, integration, or correction. Feedback supplied solely by Sensing is S→M, even when it concerns an action. |

A configured shared store or fused hand-off can implement a flow without a separate
message or API. Merely locating two roles in one system does not establish a flow.

### Channel labels

- `reported`: the source describes an implemented flow to the receiving function.
  No causal or service-outcome evidence is required.
- `absent`: the source explicitly excludes, disables, or identifies the whole route
  as unimplemented in this configuration. A missing arrow in a figure is not enough.
- `insufficient`: the source leaves a necessary link or the retention scope
  unknown. Missing information does not establish absence.

A simulation, short deployment, small sample, missing ablation, weak utility, fixed
policy, or fused implementation does not negate a reported flow.

## The five evidence steps for self-evolution

Judge each step independently. Do not force the steps to be cumulative.

1. **Record.** The service keeps records of its own actions (what it decided, did,
   or delivered), in memory or in logs it keeps for later use. Research trial logs
   that only the authors analyse do not count.
2. **Outcome.** Later evidence about those actions (reply, rating, dismissal,
   correction, receipt, observed state change, task result) is obtained and retained.
3. **Attribution.** The outcome is linked to the decision it concerns and used to
   check or correct assistance. An immediate check counts even if nothing is kept.
   Offline benchmark scoring by the authors does not.
4. **Revision.** The service itself makes a durable change to its mechanism: model
   parameters, prompts, skills, reusable rules, code, or harness. Classify by role,
   not by storage:
   - content used by a fixed mechanism (user facts, preferences, task state, maps)
     is not a revision;
   - a reusable rule that later runs apply as a rule is a revision;
   - changes written by developers or users are not revisions.
   Name what is revised.
5. **Later use.** The source states that later steps ran under the revised
   mechanism. Code that would load the revision, without a reported run, is noted
   but not marked.

### Step labels

- `stated`: the primary source states it. Give a verbatim quote and a locator.
- `not_stated`: not reported, or too vague. Give a one-line reason.

Be strict. Diagrams without text, marketing phrases such as "learns over time", and
future-work statements are `not_stated`.

## Sources and scope

- Review the configuration named in the case file (`cases/<id>/case.yaml`), not the
  paper in general. If the source describes several modes, judge the named one.
- Use the primary sources listed in the case file: the paper or blog, the product
  documentation, and the code repository at the listed commit when there is one.
  Read the code alongside the text when code is available, and the text alone
  otherwise.
- Quote the source itself. Only mark a quote as verbatim if you confirmed the exact
  wording. When a tool paraphrases a page, label the quote `UNVERIFIED`.
- Give every judgment a locator: a section, figure, table, line, file path, or URL.

## Output

Return exactly one JSON object that validates against `halo/read/schema.json`:
one entry for each of the five channels, one for each of the five steps, and a
short note on the configuration you judged and the sources you read.
