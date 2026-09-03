---
name: pr_body
version: "1.1"
model: claude-opus-5
effort: medium
description: Render the reviewer-facing body of a draft pull request from the approved change summary and test evidence
variables:
  - issue_reference
  - change_summary
  - test_evidence
  - attempts_used
  - approved_by
---

You are writing the body of a **draft** pull request that a human has already
reviewed and approved. Write it for the reviewers who will read the PR with the diff
open next to them. Be concrete and factual. Do not oversell the change and do not
speculate beyond the source material.

## Source material

Issue reference: {issue_reference}

Approved change summary:

{change_summary}

Test evidence:

{test_evidence}

Fix attempts used: {attempts_used}
Reviewed and approved by: {approved_by}

## Output

Produce GitHub-flavoured markdown with **exactly these headings, in this order**, and
nothing before the first one:

## Summary

Two or three sentences: what this PR changes and the effect, tightened for a reviewer
who has the diff open.

## The issue

The problem being solved, in the reporter's terms. If `{issue_reference}` is a
`#`-number, end this section with a line on its own reading `Closes {issue_reference}`.
If it is not a number, omit that line entirely.

## Changes

A short bullet list of the concrete edits, grouped by file or by area. One line each.

## Test evidence

Restate the test evidence above as a fenced code block, then one sentence on what it
shows. Name any failure that was pre-existing on the base branch, and any that was
introduced and then fixed across the {attempts_used} attempt(s).

## Risks and what to review closely

The bullets from the change summary's risk notes, plus anything a reviewer should
check by hand. If the change is genuinely low-risk, say so in one line and name the
one thing still worth a look.

Do not add a provenance or attribution section — that is appended after your output.
