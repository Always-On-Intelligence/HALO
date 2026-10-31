---
title: Analysis
description: The rules that turn a trace into channels, evidence steps, and a level.
---

The analysis reads only the kinds of events and the links between them. It is in `halo/mcp/analysis.py` and calls no model, so the same trace always gives the same report.

## Channels

A channel X→Y is observed when an event of module Y names an event of module X in `uses`. Links within one module, such as a recall that names a remember, are not channels. Revisions belong to no module, so links to and from them are not channels either.

| An event of kind | that uses | shows |
|---|---|---|
| act | observe or outcome | S→A |
| remember | observe or outcome | S→M |
| act | remember or recall | M→A |
| observe or outcome | act | A→S |
| observe or outcome | remember or recall | M→S |
| remember | act | A→M |

Only a `remember` event receives a channel into Memory, because S→M and A→M carry information that Memory keeps. A recall that uses an observation is a lookup the input prompted. Its result reaching an action is M→A, as the survey counts answer-time retrieval.

## Evidence steps

| Step | Observed when |
|---|---|
| record | a `remember` event uses an `act` event |
| outcome | a `remember` event uses an `outcome` event, so the outcome is kept |
| attribution | an `outcome` names its action in `about`, and a later `act` or `revise` uses the outcome, directly or through other events |
| revision | a `revise` event has `made_by: agent` |
| later use | a later `act` uses that revision, directly or through other events |

The report also looks for one connected chain: an action, an outcome about it, a revision that used the outcome, and a later action that used the revision. In the survey's read mode, only three of the 40 reviewed works state all five steps.

## Levels

| Level | Its own condition |
|---|---|
| L1 | some event uses a `remember` event from an earlier session, directly or through other events |
| L2 | such an event is an `act`, `observe`, or `outcome` |
| L3 | some `act` has trigger `self` |
| L4 | attribution is observed, and A→S or A→M is observed |
| L5 | a revision with `made_by: agent` and governance `approved` or `bounded` is used by a later action |

The level is the highest one whose condition holds together with the conditions of every level below it. L0 needs only one event.

## Reading the evidence column

| Notation | Meaning |
|---|---|
| `e3→e5` | event e5 used event e3 |
| `e5⇠e7→e9` | outcome e7 is about action e5, and e9 used e7 |
| `e9` | the event itself, for example a revision |

Every cell lists at most three examples. `halo_trace` lists all events with their links.
