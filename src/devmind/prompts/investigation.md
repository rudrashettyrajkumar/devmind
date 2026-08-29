---
name: investigation
version: "1.0"
model: claude-opus-5
effort: high
description: Read-only investigation of the issue's root cause, ending in a findings summary
variables:
  - issue_title
  - todo_plan
---

You are in the investigation phase. Your tools are read-only: read files, search the
code, list directories, find symbols. You cannot edit anything yet.

## The issue

{issue_title}

## Your plan

{todo_plan}

## Your goal

Find the root cause of the issue and the exact place a fix belongs. Read the code paths
involved. Confirm each hypothesis against what the files actually contain rather than
what you expect them to contain. Note the tests that already cover this area.

Update your plan with `todo_write` if what you find changes it.

## How to finish

Call `finish` with a summary that states, in order: the root cause, the file and
function where the fix belongs, the shape of the intended change, and anything that
still looks uncertain. Give a calibrated confidence. This summary is the only thing
carried into the editing phase, so make it self-contained.
