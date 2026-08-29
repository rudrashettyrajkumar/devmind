---
name: test_failure_analysis
version: "1.0"
model: claude-opus-5
effort: high
description: Diagnose a failing test run and produce the next fix hypothesis
variables:
  - failure_report
  - current_diff
  - todo_plan
  - attempt_number
  - max_attempts
---

You are diagnosing a failed test run inside an autonomous coding session.

## The failure

{failure_report}

## Your last change

{current_diff}

## The plan you are working

{todo_plan}

## Your constraints

This is fix attempt {attempt_number} of {max_attempts}. When the attempts are used up,
the session stops unfixed, so spend each one on a distinct hypothesis.

## What to produce

State the root cause of the failure in one sentence. Then make the smallest change that
addresses that cause, using the edit tools.

If this failure is the same as the previous attempt's, say so explicitly and change
your hypothesis — repeating the last reasoning wastes the attempt. When the fix is in
place, call `finish` with what you changed and why it resolves the reported failure.
