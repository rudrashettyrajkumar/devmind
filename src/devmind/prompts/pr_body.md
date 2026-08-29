---
name: pr_body
version: "1.0"
model: claude-opus-5
effort: medium
description: Render the draft pull-request description from the approved change summary and evidence
variables:
  - issue_reference
  - change_summary
  - test_evidence
  - attempts_used
  - approved_by
---

You are writing the description for a draft pull request that a human has already
approved. Write it for the reviewers who will read the PR.

## Source material

Issue: {issue_reference}

Approved change summary:

{change_summary}

Test evidence:

{test_evidence}

Fix attempts used: {attempts_used}
Approved by: {approved_by}

## What to write

Produce the PR body as markdown with these sections and headings:

### What changed

The summary, tightened for a reviewer who has the diff open.

### Why

The problem this solves, referencing the issue.

### Testing

What was run and the result, including any failed-then-fixed attempts.

### Provenance

State as plain fact: this change was produced by DevMind, an autonomous coding agent,
working from the issue above; the code was reviewed and approved by {approved_by}
before this pull request was opened; the pull request is a draft and no merge is
automated.

End with a line linking the issue: `Closes {issue_reference}`.
