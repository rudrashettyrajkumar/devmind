---
name: planner_retry
version: "1.0"
model: claude-opus-5
effort: high
description: Appended to the planner prompt when the first plan failed the quality guards
variables:
  - reason
  - minimum
  - maximum
---

## Your previous plan was rejected

Reason: {reason}

Decompose the work into between {minimum} and {maximum} concrete, ordered steps. Each
step must name the file or area it touches and the change or check it makes — a step a
developer could pick up on its own. Order them so each depends only on earlier ones.

Call `todo_write` again with the corrected plan, then `finish`.
