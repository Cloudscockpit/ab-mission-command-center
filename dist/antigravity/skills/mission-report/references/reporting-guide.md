# Mission Report — Scoring Rubric, Metrics, and Dashboard Guide

Reference details for the `mission-report` skill. Load only when scoring maturity stages, running
`render_dashboard.py`, or handling edge cases.

## Five-stage maturity scoring rubric

Score each dispatched assignment (done or blocked; never-dispatched work is not scored) as `pass` or
`fail`, with one line of evidence each. A stage you cannot score is a fail. Never round up.

| Stage | Pass when |
|---|---|
| Orchestrator | Assignment, file ownership, and dispatch order were right for the goal; no ownership conflict or re-plan was needed |
| Data | Inputs (recon, files, upstream outputs) were located, current, and complete |
| Analysis | Approach the Agent took was correct for the goal; no rework was needed |
| Action | Acceptance criterion was met on the first attempt and verified by someone other than the Agent that did the work (Yellow verifies Red/Blue; Black verifies Yellow by re-running Yellow's exact test command) |
| Defense/Audit | No policy or guard violation, no High security finding, no unlogged side effect, and `Files created/changed:` matches actual changes |

Use `--retried` in `maturity.py record` when the work only went green on a second attempt.
The operator's certified maturity level (`L1`–`L7`) comes from `.actionboard/config.json`
(`"operator_level"`) or from asking the user. Never assume it and never raise it. If not provided,
keep the stage table and write `Execution mode: not computed (operator level not provided)`.

## Metrics & dashboard flags

- `--started-at`: UTC time Black Agent recorded at "go" (e.g. `2026-10-26T09:30:00Z`); `--ended-at`: current UTC time.
- `--git-base`: commit recorded at mission start (plain ref, no leading `-`, no spaces). Untracked files are counted automatically; `.gitignore`d files are excluded.
- `--test`: repeat once per suite Yellow reported (`"<suite-name>,<test-command>,<passed>,<failed>,<skipped>"`). Copy counts verbatim; omit when no suite ran.
- Omit anything you cannot supply; the dashboard renders "Not recorded" for missing fields.
- A render failure is a reported defect, never a silent skip; Markdown and JSON-LD stay authoritative on disk.
- Include any stderr line containing `WARNING` (e.g. `render_dashboard: WARNING ...`) in the Mission Summary.

## Writing rules

- Report what happened, not what was supposed to happen.
- Every `FailedActionStatus` needs an actionable `error` string ("Failed" alone is noise).
- Keep deferred assignments in the graph with their reason so the next mission does not rediscover them.
- Lead with the Outcome table; never shorten or omit a required section.
