---
name: submit-mission
description: Submit ActionBoard V5 Mission Brief, Mission Plan, and Mission Report documents directly from the CLI to a Board inside an ActionBoard Pod. Use when the user asks to "submit the mission", "upload the mission report", "push mission to ActionBoard", "submit to pod/board", or after completing a mission report.
---

> Paths written `<skill-dir>/...` are relative to the directory that contains this SKILL.md.

# Submit Mission to ActionBoard Pod & Board

Uploads a mission's **Brief**, **Plan**, and **Report** (Markdown, HTML dashboard, JSON-LD knowledge graphs, and metrics) directly to an ActionBoard Pod's Board from the CLI — without opening the web UI.

## How it works

The submission CLI (`<skill-dir>/../mission-report/scripts/submit_mission.py`, Python 3.9+ standard library only) executes the full ActionBoard control-plane and data-plane flow:

1. **Authenticate (`auth_login` / `auth_refreshToken`):** Signs in to the ActionBoard main user pool and caches tokens with `0600` permissions in `~/.actionboard/credentials.json` (falling back to `.actionboard/credentials.json` inside restricted sandboxes).
2. **Resolve Pod & SSO Exchange (`pods_getMyPods` -> `pods_createExchangeCode` -> `pods_consumeExchangeCode`):** Exchanges the main access token for a Pod-scoped `idToken` carrying `custom:podId` and `custom:profileId`.
3. **Select Board (`boards_getMyBoards`):** Lists boards inside the chosen Pod and saves the selected `pod_id` and `board_id` in `.actionboard/config.json`.
4. **Create or Match Mission (`assistprofile_listMissionsByBoard` / `assistprofile_createMission`):** Reuses an existing mission ID (from `.actionboard/config.json`, `--mission-id`, or title match) or creates a new mission on the board with its dedicated `missionFolderId` and `reportsSubfolderId`.
5. **Submit Mission Plan (`assistprofile_createMissionPlan` / `assistprofile_updateMissionPlan` / `assistprofile_submitMissionPlan`):** Publishes the combined Mission Brief and Mission Plan Markdown to the board's mission plan record.
6. **Upload Deliverables to S3 & Register Reports (`assistprofile_submitReports`):** Uploads `mission-report.md`, `mission-report.html`, `mission-report.jsonld`, `mission-brief.md`, `mission-brief.jsonld`, `mission-plan.md`, `mission-plan.jsonld`, and `mission-metrics.json` to `s3://<S3_BUCKET_NAME>/<S3_PREFIX>/<boardId>/missions/<missionId>/` using AWS SigV4 and registers them on the mission (with automatic fallback to `filemanager_createFolder` + `filemanager_createFile` for legacy missions).
7. **Mark Completed (`assistprofile_updateMissionStatus`):** Sets mission status to `COMPLETED` when `mission-report.md` is present.

## Step-by-step execution

### Step 1 — Check CLI status

Run `status` first to see whether AppSync credentials, login tokens, S3 credentials, and a default Pod/Board are already configured:

```sh
python <skill-dir>/../mission-report/scripts/submit_mission.py status
```

On Windows use `py` instead of `python`.

### Step 2 — Configure endpoint & S3 (first time only)

If `AppSync endpoint` is `NOT SET`, import settings from an env/config file or pass them explicitly:

```sh
python <skill-dir>/../mission-report/scripts/submit_mission.py configure \
  --from-env-file mission-plan-api.md
```

Or configure individual settings:

```sh
python <skill-dir>/../mission-report/scripts/submit_mission.py configure \
  --endpoint <APPSYNC_GRAPHQL_ENDPOINT> \
  --api-key <APPSYNC_API_KEY> \
  --s3-region ap-southeast-1 \
  --s3-bucket actionboard-kb-agent \
  --s3-prefix "PremiumBoardKB/Boards/Investor+Boards"
```

To enable binary S3 uploads (in addition to standard `~/.aws/credentials` or `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` environment variables), you can also pass `--aws-access-key-id` and `--aws-secret-access-key` to `configure`.

### Step 3 — Log in to ActionBoard (when not authenticated)

If `Authenticated` is `no`, log in once. Credentials and refresh tokens are cached in `~/.actionboard/credentials.json` (`0600`):

```sh
python <skill-dir>/../mission-report/scripts/submit_mission.py login --email <user-email>
```

For non-interactive / CI environments, set `ACTIONBOARD_EMAIL` and `ACTIONBOARD_PASSWORD` (or pass `--email` and `--password`).

### Step 4 — Select Pod & Board (first submit in a project, or to switch boards)

List available Pods and Boards or save a project default in `.actionboard/config.json`:

```sh
# List pods the user belongs to
python <skill-dir>/../mission-report/scripts/submit_mission.py pods

# List boards inside a pod
python <skill-dir>/../mission-report/scripts/submit_mission.py boards --pod <podId-or-slug>

# Save default pod and board for this project
python <skill-dir>/../mission-report/scripts/submit_mission.py select --pod <podId-or-slug> --board <boardId-or-name>
```

When run in an interactive terminal without `--pod` or `--board`, `select` and `submit` present a numbered Pod & Board picker.

### Step 5 — Submit the mission

```sh
# Auto-detect the latest mission folder in docs/missions/ or actionboard-v5-missions/
python <skill-dir>/../mission-report/scripts/submit_mission.py submit

# Or specify the mission directory, pod, board, or mission ID explicitly
python <skill-dir>/../mission-report/scripts/submit_mission.py submit \
  --mission-dir docs/missions/<YYYY-MM-DD-slug> \
  --pod <podId-or-slug> \
  --board <boardId-or-name>
```

Useful flags for `submit`:
- `--dry-run`: Validate local mission files and print the JSON payload summary without calling AppSync or S3.
- `--mission-id <id>`: Attach the plan and reports to a specific existing mission on the board.
- `--invitation-id <id>`: Submit the mission plan against an `AssistProfile` mission invitation (`assistprofile_submitMissionPlan`).
- `--create-mission`: Always create a fresh mission entry on the board even if a mission with the same title exists.
- `--update-mission`: Update the title and short description of an existing mission.
- `--status <INITIATED|IN_PROGRESS|COMPLETED|FAILED|ARCHIVED>`: Override the mission status written after upload.
- `--skip-s3`: Register report metadata in AppSync without performing the S3 `PUT` request.
- `--json`: Print machine-readable JSON output.

## Security rules

- Never commit `.actionboard/credentials.json`, `~/.actionboard/credentials.json`, or raw API keys/passwords to git.
- Keep credential files at `0600` (`-rw-------`) permissions.

