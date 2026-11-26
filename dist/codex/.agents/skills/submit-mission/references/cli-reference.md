# Submit Mission — Control-Plane & Direct-Mode Reference

Reference details for the `submit-mission` skill. Load only when configuring direct AppSync/AWS
mode or troubleshooting authentication/storage paths.

## End-to-end control-plane & data-plane flow

1. **Authenticate (browser sign-in / `auth_refreshToken`):** Signs in through the ActionBoard hosted login page and stores tokens in the OS keychain (macOS Keychain, Windows Credential Manager, Linux Secret Service), falling back to `~/.actionboard/credentials.json` (`0600`) or `.actionboard/credentials.json`.
2. **Resolve Pod & SSO Exchange:** `pods_getMyPods` -> `pods_createExchangeCode` -> `pods_consumeExchangeCode` yields a Pod-scoped `idToken` carrying `custom:podId` and `custom:profileId`.
3. **Select Board:** `boards_getMyBoards` saves `pod_id` and `board_id` in `.actionboard/config.json`.
4. **Create or Match Mission:** Reuses an existing mission ID (`.actionboard/config.json`, `--mission-id`, or title match) or creates a new mission (`assistprofile_createMission`).
5. **Submit Mission Plan:** Publishes combined Brief + Plan Markdown (`assistprofile_createMissionPlan` / `assistprofile_updateMissionPlan` / `assistprofile_submitMissionPlan`).
6. **Upload Deliverables & Organize in Board File Manager:** Finds or creates the root `Missions` folder, creates a short subfolder `Missions/<mission-name>/` (plus `<phase-or-milestone>/` with `--phase` / `--milestone`), preserves nested folders such as `case-files/`, uploads files via edge proxy presigned URLs (or Pod route / AWS SigV4 when AWS keys are set) to the selected Pod's S3 bucket and region, and registers them with `filemanager_createFolder` + `filemanager_createFile`.
7. **Mark Completed:** Updates mission status to `COMPLETED` when `mission-report.md` is present.

## Direct mode configuration (optional)

By default every call routes through the ActionBoard edge proxy (no API key or AWS keys needed).
To switch an existing API-key setup onto the edge proxy, run
`configure --edge-proxy-url https://actionboard-edge-proxy.ab-mobile.workers.dev` (`""` to revert).

For direct AppSync / S3 mode:

```sh
python <skill-dir>/../mission-report/scripts/submit_mission.py configure \
  --from-env-file mission-plan-api.md

python <skill-dir>/../mission-report/scripts/submit_mission.py configure \
  --endpoint <APPSYNC_GRAPHQL_ENDPOINT> \
  --api-key <APPSYNC_API_KEY> \
  --s3-region ap-southeast-1 \
  --s3-bucket actionboard-kb-agent \
  --s3-prefix "PremiumBoardKB/Boards/Investor+Boards"
```

AWS keys are optional. Without them, files upload through presigned URLs from the edge proxy (or, in direct mode, through the Pod's own upload route). To upload straight to S3 instead, set `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`, select a shared credentials profile with `AWS_PROFILE` (or a file with `AWS_SHARED_CREDENTIALS_FILE`), or pass `--aws-access-key-id` and `--aws-secret-access-key` to `configure`. A `~/.aws/credentials` `[default]` profile on its own is not used, so an unrelated AWS account never takes over the upload.

### Sign up (`signup`)

`submit_mission.py signup [--region bd|us] [--no-input] [--json]` helps someone with no account. It never takes a password, verification code, email or URL.

- `--region`: `bd` (Bangladesh, https://actionboard.com.bd/auth/signup) or `us` (United States, https://actionboard.ai/auth/signup). Case and spaces are ignored. Without it, a terminal prompts; with `--no-input` or no terminal it fails with exit 2.
- `bd`: opens the sign-up page, tells the user to create the account and verify the email in the browser, then run `login`. In a terminal (no `--no-input`) it waits for Enter, asks before replacing an existing session, runs the browser `login`, and notes if the account has no Pod yet.
- `us`: opens nothing, prints the sign-up link, says plugin sign-in is not available yet, and exits 2.
- `--json` for `bd`: `{"success": true, "region", "label", "signup_url", "opened", "next_step": "login"}`.
- `--json` for `us` (exit 2): `{"success": false, "status": "region_pending", "region", "label", "signup_url"}`.

For CI login without a browser, set `ACTIONBOARD_EMAIL` and `ACTIONBOARD_PASSWORD`. Run `logout` to clear stored tokens.
