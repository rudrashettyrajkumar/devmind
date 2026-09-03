---
name: change_summary
version: "1.1"
model: claude-opus-5
effort: medium
description: Produce the human-facing change summary and risk notes for the approval gate
variables:
  - issue_title
  - todo_plan
  - final_diff
  - test_evidence
---

You are writing the summary a human will read before deciding whether to approve this
change. They can see the raw diff; they need you to explain it.

## The issue

{issue_title}

## The plan as worked

{todo_plan}

## The final diff

{final_diff}

## Test evidence

{test_evidence}

## What to write

Produce markdown with exactly these five sections and headings:

### Issue understanding

One short paragraph, in your own words: what the reporter is actually asking for and
what the underlying problem is. This is the restatement a reviewer checks your work
against — do not copy the issue text back, interpret it. Do not leave this section
empty.

### Summary

Two or three sentences: what was wrong, and what the change does about it.

### Changes by file

One bullet per file in the diff — the path, and what changed in it and why.

### Verification

What the test evidence shows: the baseline result, the final result, and any failing
attempts in between.

### Risks and uncertainties

The assumptions you made that could be wrong, anything the tests do not cover, and any
part of the fix you are not fully confident in. If you genuinely have none, write
"None identified" and give the reason the change is low-risk. Do not leave this section
empty.
