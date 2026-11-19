# Review (security)

**Goal:** Security pass on **branch changes vs `main`**, fix or document real findings, re-run verify.

## When to run

- User chose **`security`** from **`/review`**, or
- **`AGENTS.md`** post-PR loop flagged security-sensitive paths (see below), or
- User explicitly asked for security review.

**Security-sensitive paths (non-exhaustive):** `src/grocery_wizard/integrations/` (Notion, NYT), `config/`, `ui/access_gate.py`, household auth, `.github/workflows/` secrets usage, any new `subprocess` / `eval` / pickle / unsanitized URL fetch.

## Steps

1. Confirm you are on the **PR branch** and `git fetch origin main`.
2. Launch the **security-review** subagent (**`subagent_type: security-review`**, `run_in_background: false`) with:

```text
Full Repository Path: /agent/repos/grocery-wizard
Diff: branch changes
Custom Instructions: Streamlit app; Notion API; no prod secrets in repo. Call out credential handling and user-controlled URLs.
```

3. Fix **substantive** findings; file a follow-up issue for deferred risks.
4. Run **`just check`**.
5. Push; update PR if needed; respond on PR threads per **`AGENTS.md`**.