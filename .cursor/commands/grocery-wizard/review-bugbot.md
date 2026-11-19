# Review (Bugbot-style)

**Goal:** Review **branch changes vs `main`**, fix real issues, re-run verify, and leave the PR ready for CI/merge.

Does **not** require GitHub Bugbot to be enabled ([#551](https://github.com/rachelgramlich/grocery-wizard/issues/551) deferred). Optional: comment `bugbot run` on the PR only if the owner turned on dashboard Bugbot.

## Steps

1. Confirm you are on the **PR branch** and `git fetch origin main`.
2. Launch the **Bugbot** subagent (**`subagent_type: bugbot`**, `run_in_background: false`) with:

```text
Full Repository Path: /agent/repos/grocery-wizard
Diff: branch changes
Custom Instructions: Grocery Wizard: follow CONTRIBUTING.md and AGENTS.md. UI tests use tests/src/grocery_wizard/ui/ui_source.py. Prefer minimal fixes.
```

3. **Implement** warranted fixes from the review; skip nitpicks and false positives. Follow **`tidy-first`** (S vs B commits when both apply).
4. Run **`just check`** (and **`just smoke-ui`** / **`/app-smoke`** when UI paths changed per **`AGENTS.md`**).
5. Push fixes; update PR body if manual verification changed.
6. If review feedback was posted on GitHub (Bot or human), **reply**, **`resolve_comment`** when fixed, and **`subscribe_github_pr`** per **`AGENTS.md`**.

## After a PR is first created

Run this workflow **once** in the same chat before ending the turn (unless the user said **`/no-test`** or skip review). Then subscribe to CI + PR and wait on external results instead of polling.