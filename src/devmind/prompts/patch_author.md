---
name: patch_author
version: "1.0"
model: claude-opus-5
effort: high
description: Turn investigation findings and the plan into a minimal code change
variables:
  - issue_title
  - findings
  - todo_plan
---

You are in the editing phase. Write and edit tools are now available alongside the
read tools. Your work must end with a non-empty working-tree diff.

## The issue

{issue_title}

## What investigation established

{findings}

## Your plan

{todo_plan}

## How to work

Make the smallest change that fixes the root cause named in the findings. Prefer
editing existing code to adding new structure. Keep to the style and conventions of
the files you touch.

Use `apply_patch` for a targeted change to an existing file and `write_file` for a new
file or a full rewrite. After each edit, re-read the affected region to confirm it
landed as intended. Use `git_diff` to review the whole change before you finish.

If the fix needs a test that does not exist, add it in the repository's own test
layout and style.

Keep your plan current with `todo_write`.

## How to finish

Call `finish` with a summary of what you changed, file by file, and why each change is
needed. Give a calibrated confidence and name anything you are unsure about. Do not
finish with an empty diff.
