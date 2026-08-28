---
name: devmind-prompt-authoring
description: How to author and modify the markdown prompt files in src/devmind/prompts/ — frontmatter schema, variable declaration, versioning, and prompting conventions for Claude Opus 5 (adaptive thinking, effort, no prefill, no budget_tokens). Use when creating or editing any DevMind prompt.
---

# Authoring DevMind Prompts

Every prompt is a versioned markdown file. **No prompt text ever lives in a Python string.**

## File shape

`src/devmind/prompts/<name>.md`

```markdown
---
name: test_failure_analysis
version: 1.0
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

This is attempt {attempt_number} of {max_attempts}.

State the root cause in one sentence, then make the smallest change that fixes it.
If the failure is identical to the previous attempt, say so and change your hypothesis
rather than re-applying the same reasoning.
```

### Frontmatter contract

| Key | Required | Notes |
|---|---|---|
| `name` | ✅ | Must equal the filename stem. `PromptLoader` asserts this |
| `version` | ✅ | Bump on any semantic change to the body |
| `model` | ✅ | Exact id — `claude-opus-5`. Never a date-suffixed variant |
| `effort` | ✅ | `low` \| `medium` \| `high` \| `xhigh` \| `max` |
| `description` | ✅ | One line, what this prompt is for |
| `variables` | ✅ | Every `{placeholder}` in the body. Validated at render — a missing or extra variable is an error, not a silent gap |

## Writing conventions

- **Second person, imperative.** "You are diagnosing…", "State the root cause."
- **Structure with markdown headings**, not walls of prose. The model navigates structure.
- **Say what to do, not what not to do.** "Make the smallest change that fixes it" beats
  "don't make sweeping changes."
- **State the output contract explicitly** when the caller parses the result — and prefer
  structured outputs or a tool call over asking for JSON in prose.
- **Give the model its constraints as facts**, not warnings: attempt number, remaining budget,
  which tools are available in this phase.
- **Don't restate the system prompt** in a phase prompt. Phase prompts add context; the system
  prompt carries identity and rules.

## Model-specific rules (Claude Opus 5)

These are current API facts, not preferences. Getting them wrong is a 400 or a silent quality
loss:

- **Adaptive thinking:** `thinking={"type": "adaptive"}`. Thinking is on by default on Opus 5.
- **`budget_tokens` is removed** on this model family — passing it returns a 400. There is no
  fixed thinking budget any more; use `effort` instead.
- **Effort** lives at `output_config={"effort": "..."}`, not top-level. `high` is the default;
  `xhigh` suits long-horizon agentic work; `low` suits cheap classification calls.
- **Assistant prefill is removed** — a last-assistant-turn prefill returns 400. Constrain
  output with `output_config.format` or an explicit instruction in the prompt body.
- **Sampling params (`temperature`, `top_p`, `top_k`) are removed** — they return 400. Don't
  put them in frontmatter.
- **Don't disable thinking** to save money; lower `effort` instead. With thinking disabled Opus
  5 can write a tool call into visible text instead of a `tool_use` block, which fails silently
  inside an agent loop.

## Caching discipline

Prompt caching is a prefix match — any byte change invalidates everything after it. So:

- **Keep prompt bodies stable.** Never interpolate a timestamp, a step counter, a uuid, or a
  `datetime.now()` into a cached prefix. Volatile values belong in the message that follows the
  last cache breakpoint.
- Render order is `tools` → `system` → `messages`. The system prompt and the repo brief are the
  cacheable prefix; per-step content is not.
- A sustained `cache_read_input_tokens == 0` means a silent invalidator crept in. Treat it as a
  bug and hunt it.

## Versioning & changes

- Bump `version` on any semantic change; note what changed in the commit body.
- Changing a prompt is changing behaviour — expect the prompt-contract test to need updating,
  and expect to re-run the affected service tests.
- Never delete a variable without updating every caller; `PromptLoader` will raise, which is the
  point.

## The inventory

| Prompt | Purpose |
|---|---|
| `system_agent` | Identity, rules, safety constraints, tool discipline. The cached prefix |
| `planner` | Issue + repo brief → a concrete todo plan |
| `investigation` | Read-only exploration; must end with a findings summary |
| `patch_author` | Findings + plan → code changes |
| `test_failure_analysis` | Failure report → root cause → next fix |
| `change_summary` | Final diff + evidence → human-readable summary and risk notes |
| `pr_body` | Summary + evidence → PR description with provenance footer |

## Checklist

- [ ] `name` matches the filename stem.
- [ ] Every `{placeholder}` is declared in `variables`, and every declared variable appears.
- [ ] `model` is an exact current id; no date suffix.
- [ ] No `temperature`, `top_p`, `top_k`, or `budget_tokens` anywhere.
- [ ] No volatile value interpolated into a cached prefix.
- [ ] Output contract stated if the caller parses it.
- [ ] `version` bumped if the body changed.
