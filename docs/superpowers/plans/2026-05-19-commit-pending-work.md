# Commit Pending Work Plan

> Status: not started. This plan documents the commit process for two completed-but-uncommitted features. It does not execute the commits.

## Goal

Land two independent, completed feature diffs into `main` as clean, well-scoped commits:

- **F1 — tire cliff detection** (plan: `docs/superpowers/plans/2026-05-15-tire-cliff-detection.md`)
- **F2 — deterministic parallel tool execution** (plan: `docs/superpowers/plans/2026-05-15-deterministic-parallel-tool-execution.md`)

Both features are functional in the working tree, have tests, and are ready to ship. The only complication is that `server/chat.py` contains diffs from both features and must be split across two commits.

## Current Working-Tree State

Files modified in working tree (per `git status`):

| File | Belongs to | Notes |
|---|---|---|
| `server/f1_data.py` (+148/-1) | F1 | Regression helpers, `_detect_cliff()`, stint splitting, cliff fields |
| `server/chat.py` (+72/-40) | **F1 + F2** | Mixed: cliff widget fields + system-prompt language (F1) AND `ThreadPoolExecutor`, `_execute_analysis_tool_call()`, `_execute_analysis_tool_calls()` (F2) |
| `server/tools.py` (+5) | F1 | `analyze_stint_degradation` description update |
| `client/src/components/chat-widgets/DegTrendChart.jsx` (+78/-9) | F1 | Pre/post-cliff regression segments, marker, stat |
| `server/main.py` (+3) | F2 | `run_in_threadpool` import + wrap |
| `server/tests/test_f1_data.py` (+187) | F1 | 11 new tests across 3 test classes |
| `server/tests/test_chat.py` (+87) | F2 | 5 new tests for parallel execution |
| `.claude/settings.local.json` | unrelated | Permissions allowlist; not part of either feature |

Untracked (do not commit as part of F1/F2):

- `docs/superpowers/plans/2026-05-15-deterministic-parallel-tool-execution.md`
- `docs/superpowers/plans/2026-05-15-tire-cliff-detection.md`

---

## Task 1: Pre-Commit Verification

Run all of these from the repo root. If anything fails, **stop** — fix the failure before committing anything. See Risks below.

```powershell
# Backend tests — feature-specific first
cd server
python -m pytest tests/test_f1_data.py -v
python -m pytest tests/test_chat.py -v

# Full backend suite
python -m pytest tests/ -v

# Client build
cd ..\client
npm run build
```

Acceptance:

- All `TestDetectCliff`, `TestFitStintDegradationStintSplitting`, and `TestFitStintDegradationCliffFields` tests pass.
- All 5 new parallel-execution tests in `test_chat.py` pass.
- The full backend suite is green.
- `npm run build` finishes without errors.

Optional manual smoke test:

- Start `uvicorn main:app --reload --port 8000` and `npm run dev`.
- Ask a deg-trend question for a race known to have a clear cliff (e.g. a hard-tyre stint that visibly fell off) and confirm the chart renders pre/post-cliff segments and the marker.

---

## Task 2: Commit Strategy

Recommended: **two separate commits**, because the features are independent and have separate plans. This keeps `git log` and `git blame` clean and makes either commit individually revertible.

The friction point is `server/chat.py`, which has diffs from both features. Two options:

- **(a) Split `server/chat.py` with `git add -p`.** Stage cliff-related hunks for commit A, then stage parallel-execution hunks for commit B. Clean history, modest manual labour (~5 minutes if hunks are well-separated).
- **(b) One combined commit.** Faster, but conflates two unrelated features in one log entry. Only fall back to this if `git add -p` shows hunks that genuinely overlap.

Recommendation: **(a)**. The two changes in `chat.py` touch different functions (cliff fields live in `_make_deg_trend_chart_widget()` and the system-prompt blob; parallel execution lives in new `_execute_analysis_tool_call*` helpers and `_retrieve_analysis_evidence()`), so hunks should not overlap.

`.claude/settings.local.json` is unrelated tooling config and should be a **separate, third commit** — or excluded entirely from the push if it contains machine-specific permissions. Inspect the diff first; do not push secrets.

### Commit A — Tire cliff detection

Files (whole-file `git add`):

- `server/f1_data.py`
- `server/tools.py`
- `client/src/components/chat-widgets/DegTrendChart.jsx`
- `server/tests/test_f1_data.py`

Files (partial via `git add -p`):

- `server/chat.py` — only cliff-related hunks: the new fields in `_make_deg_trend_chart_widget()` and the tyre-language update in the system prompt.

### Commit B — Parallel deterministic tool execution

Files (whole-file `git add`):

- `server/main.py`
- `server/tests/test_chat.py`

Files (partial via `git add -p`):

- `server/chat.py` — only the parallel-execution hunks: `ThreadPoolExecutor` import, `MAX_DETERMINISTIC_TOOL_WORKERS` constant, `_execute_analysis_tool_call()`, `_execute_analysis_tool_calls()`, and the call-site change in `_retrieve_analysis_evidence()`.

### Commit C (optional) — Tooling config

- `.claude/settings.local.json` — only if intentionally being shared. Otherwise leave uncommitted.

Suggested sequence:

```powershell
git add server/f1_data.py server/tools.py client/src/components/chat-widgets/DegTrendChart.jsx server/tests/test_f1_data.py
git add -p server/chat.py    # cliff hunks only
git diff --cached --stat     # sanity check
git commit ...               # message A (see Task 3)

git add server/main.py server/tests/test_chat.py
git add -p server/chat.py    # parallel hunks only
git diff --cached --stat
git commit ...               # message B
```

After both commits, `git diff server/chat.py` should be empty.

---

## Task 3: Commit Messages

Do **not** include emoji. Do **not** include `Co-Authored-By` lines unless the user explicitly asks for them.

### Commit A message

```
feat: tire cliff detection with BIC piecewise regression

Adds two-segment linear regression with BIC model selection to detect
when tyre performance shifts from normal degradation into a materially
worse phase. Renders pre/post-cliff regression segments and a cliff
marker in the DegTrendChart widget. Includes stint-splitting fix for
same-compound tyre-age resets.

Plan: docs/superpowers/plans/2026-05-15-tire-cliff-detection.md
```

### Commit B message

```
feat: parallel deterministic tool execution

Runs independent planned tool calls concurrently using a 4-worker
ThreadPoolExecutor while preserving evidence order. Wraps
answer_f1_payload in run_in_threadpool so the FastAPI event loop
doesn't block. Single-call fast-path bypasses the executor.

Plan: docs/superpowers/plans/2026-05-15-deterministic-parallel-tool-execution.md
```

Pass each message via a PowerShell single-quoted here-string (`git commit -m @'...'@`). The closing `'@` must sit at column 0.

---

## Task 4: Post-Commit Verification

```powershell
# Confirm the two new commits
git log -3 --oneline

# Working tree clean (or only the unrelated settings file remaining)
git status

# Sanity: each commit's stat should match the file list in Task 2
git show --stat HEAD~1
git show --stat HEAD
```

Acceptance:

- Two new commits at the tip of `main`, in the order A then B (or B then A — order is not load-bearing).
- `server/chat.py` has no remaining unstaged diff.
- All tests still pass after both commits (re-run Task 1 if paranoid).
- No tag is required; this project does not currently use semver tags. Skip unless asked.

Push (only when the user confirms):

```powershell
git push origin main
```

---

## Risks

Per the user's risk-management protocol — surface, propose, decide before continuing.

| Risk | Trigger | Proposed resolution |
|---|---|---|
| A test fails during Task 1 | Pre-commit verification | **Stop. Do not commit.** Fix the failure (or report it back), then re-run the full suite. Committing red tests poisons `main`. |
| `git add -p` hunks overlap between F1 and F2 in `chat.py` | Task 2 split | Fall back to a single combined commit with a message that names both plans. Acceptable degradation; flag in the commit body. |
| `.claude/settings.local.json` contains machine-specific or sensitive entries | Task 2 commit C | Inspect with `git diff .claude/settings.local.json` first. If anything is local-only, leave it uncommitted. Never push secrets. |
| Client build fails after commits land | Task 4 | Roll back with `git reset --soft HEAD~2` (preserves working tree), fix the build, re-commit. Confirm with the user before any `--hard` reset. |
| Hidden coupling between the F1 and F2 `chat.py` changes (e.g. one feature's helper imports the other's constant) | Task 1 | Re-run the full test suite **after staging commit A but before committing**, then again after commit B. If commit A in isolation breaks tests, the features aren't independent and (b) — single commit — is the only honest option. |

---

## Validation Checklist

- [ ] All cliff-detection tests pass (`TestDetectCliff`, `TestFitStintDegradationStintSplitting`, `TestFitStintDegradationCliffFields`).
- [ ] All 5 new parallel-execution tests in `test_chat.py` pass.
- [ ] Full backend suite green (`python -m pytest tests/ -v`).
- [ ] `npm run build` succeeds.
- [ ] `server/chat.py` cleanly splits into two non-overlapping hunk sets.
- [ ] Commit A contains only cliff-detection files and hunks.
- [ ] Commit B contains only parallel-execution files and hunks.
- [ ] Neither commit message includes emoji or `Co-Authored-By`.
- [ ] `git log -3 --oneline` shows the two new commits.
- [ ] `git status` is clean (or contains only `.claude/settings.local.json`).
- [ ] Tests still pass at `HEAD` after both commits.

## Non-Goals

- Not pushing to remote. The user pushes manually when ready.
- Not tagging a release.
- Not committing `.claude/settings.local.json` unless explicitly instructed.
- Not committing the two source plan documents (`2026-05-15-*.md`) — they describe completed work and can land in a separate docs commit if desired.
