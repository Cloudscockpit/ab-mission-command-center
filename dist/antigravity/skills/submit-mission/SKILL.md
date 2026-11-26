---
name: submit-mission
description: Submit ActionBoard Mission Brief, Plan, and Report to a Pod Board through the ActionBoard MCP tools. Use when asked to submit, upload, or push a mission, or to post mission progress.
---

> Paths written `<skill-dir>/...` are relative to the directory that contains this SKILL.md.

# Submit Mission to ActionBoard Pod & Board

Uploads a mission's Brief, Plan, Report, JSON-LD graphs, metrics, and HTML dashboard to the
selected ActionBoard Board with the `actionboard` MCP server's `ab_*` tools.

## Step 1: Check login and Board

Call `ab_auth_status`. If `logged_in` is `false`, `active_board_id` is empty, or the `ab_*` tools
are missing, run the `ab-login` skill first.

## Step 2: Submit

Call `ab_submit_mission`. Arguments, all optional:

- `mission_dir`: the mission folder; defaults to the newest folder under `docs/missions/`.
- `pod_id` / `board_id`: a Pod or Board other than the selected one.
- `mission_id` / `invitation_id`: the board mission to update. A fetched or earlier-submitted
  folder is already linked, so it updates the same mission; otherwise a mission with the same
  title is reused or a new one is created.
- `status`: `INITIATED`, `IN_PROGRESS`, `COMPLETED`, `FAILED` or `ARCHIVED`. Without one, a
  folder with `mission-report.md` is marked `COMPLETED`.
- `dry_run: true`: list what would be uploaded, without logging in or changing anything.
- `keep_old: true`: keep previous versions of changed files instead of replacing them.
- `phase`: also group the files under `Missions/<mission-name>/<phase>/` (a phase or milestone name).

Files land in the board's File Manager under `Missions/<mission-name>/`. Re-submitting is idempotent: `skipped_files` lists unchanged files, and only files this
integration uploaded are ever replaced; files people uploaded in the app are never touched.
Report `uploaded_files`, `skipped_files` and `status` to the user in one or two lines.

## Step 3: Live progress (optional)

Call `ab_post_progress` with `mission_dir` (or `mission_id`), a `status` (default `IN_PROGRESS`),
and/or a one-line `comment`. Never put secrets, tokens, or file contents in a comment.

To change how missions sync, call `ab_select_board` with the current `pod_id`, `board_id` and
`sync` (`ask`, `auto` or `off`).

Direct AppSync/AWS mode setup and the full control-plane flow: `<skill-dir>/references/cli-reference.md`.

## Security rules

- Never commit `.actionboard/credentials.json`; the tools never return tokens.
- Never ask for the user's password in chat; `ab_login` signs in through the browser.
