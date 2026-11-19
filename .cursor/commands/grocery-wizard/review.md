# Review

Pick **one** review to run (Bugbot-style code review or security review). This is **agent-side** review of the branch diff — not the same as enabling GitHub Bugbot on the repo (deferred: [#551](https://github.com/rachelgramlich/grocery-wizard/issues/551)).

## When the user invokes `/review`

If the **AskQuestion** tool is available, ask exactly one single-select question:

- `bugbot` → follow **`/review-bugbot`**
- `security` → follow **`/review-security`**

If AskQuestion is not available, ask in chat with the same two options. **Do not run both** unless the user asks.

## When the agent opens a PR (automatic)

Follow **`AGENTS.md`** **Post-PR review loop** — default to **`/review-bugbot`** without asking. Also run **`/review-security`** when the diff touches auth, secrets, tokens, or untrusted input boundaries (see **`review-security.md`**).