---
title: Loop-closure levels
description: The six levels from L0 to L5, and what a trace must show for each.
---

The survey places services on six cumulative levels of loop closure. Two properties make a service always-on: **state durability**, so what it learns persists across interactions, and **operational continuity**, so it decides between requests whether to act. Both hold from L3 on.

| Level | Name | Adds | What a HALO trace must show |
|---|---|---|---|
| L0 | Session local | | at least one event |
| L1 | Retained state | state durability | something kept in memory and used in a later session |
| L2 | State-guided decision | retained state guides decisions through M→A or M→S | memory from an earlier session used by an action or an observation |
| L3 | Unrequested action | operational continuity | an action the agent decided on by itself between requests, logged with trigger `self` |
| L4 | Attributed outcomes | attribution through A→S or A→M | an outcome linked to the action it concerns and then used by a later action or revision, with A→S or A→M in the trace |
| L5 | Governed revision | governed self-evolution | a revision by the agent, approved or bounded by the user, that a later action used |

Levels are cumulative, so the report gives the highest level whose condition, and those of every level below it, appear in the trace.

## Requested or unrequested

L2 and L3 differ in who decides to act. A reminder the user set for 9:00 is requested, even when it fires while the user is away, so the action is logged with trigger `request`. The same holds for every step inside a run the user scheduled: choosing another data source or picking which papers to send is the agent's choice of how to do a requested task, not a decision to act. A check after a meeting that ends in a reminder, or in a decision to wait, is the agent's own decision whether to act, so it is logged with trigger `self`. Running in the background or on a timer does not by itself make a service always-on.

## Governed revision

A revision is governed when it stays within a scope the user authorized: the user approved the change (`approved`), or the change stays inside limits the user set in advance (`bounded`). A revision with governance `none` counts as a revision step but does not reach L5.

## A level is a lower bound

A trace shows only what the agent logged. An agent that keeps memory but did not log a recall in a later session stays at L0 in its report. The report says what the next level needs, so missing steps can be found and logged when they happen.
