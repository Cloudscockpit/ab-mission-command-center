# Submit Mission — Control-Plane & Direct-Mode Reference

Reference details for the `submit-mission` skill. Load only when configuring direct AppSync/AWS
mode or troubleshooting authentication/storage paths.

## End-to-end control-plane & data-plane flow

1. **Authenticate (browser sign-in / `auth_refreshToken`):** Signs in through the ActionBoard hosted login page and stores tokens in the OS keychain (macOS Keychain, Windows Credential Manager, Linux Secret Service), falling back to `~/.actionboard/credentials.json` (`0600`) or `.actionboard/credentials.json`.
2. **Resolve Pod & SSO Exchange:** `pods_getMyPods` -> `pods_createExchangeCode` -> `pods_consumeExchangeCode` yields a Pod-scoped `idToken` carrying `custom:podId` and `custom:profileId`.
3. **Select Board:** `boards_getMyBoards` saves `pod_id` and `board_id` in `.actionboard/config.json`.
4. **Create or Match Mission:** Reuses an existing mission ID (`.actionboard/config.json`, `--mission-id`, or title match) or creates a new mission (`assistprofile_createMission`).
5. **Submit Mission Plan:** Publishes combined Brief + Plan Markdown (`assistprofile_createMissionPlan` / `assistprofile_updateMissionPlan` / `assistprofile_submitMissionPlan`).
6. **Upload Deliverables & Register:** Uploads mission files via edge proxy presigned URLs (or Pod route / AWS SigV4 when AWS keys are set) and registers them on the board.
7. **Mark Completed:** Updates mission status to `COMPLETED` when `mission-report.md` is present.

## Direct mode configuration (optional)

By default every call routes through the ActionBoard edge proxy (no API key or AWS keys needed).
To switch an existing API-key setup onto the edge proxy, run
`configure --edge-proxy-url https://actionboard-edge-proxy.ab-mobile.workers.dev` (`""` to revert).

For direct AppSync / S3 mode:

```sh
python ${CLAUDE_PLUGIN_ROOT}/skills/mission-report/scripts/submit_mission.py configure \
  --from-env-file mission-plan-api.md

python ${CLAUDE_PLUGIN_ROOT}/skills/mission-report/scripts/submit_mission.py configure \
  --endpoint <APPSYNC_GRAPHQL_ENDPOINT> \
  --api-key <APPSYNC_API_KEY> \
  --s3-region ap-southeast-1 \
  --s3-bucket actionboard-kb-agent \
  --s3-prefix "PremiumBoardKB/Boards/Investor+Boards"
```

For CI login without a browser, set `ACTIONBOARD_EMAIL` and `ACTIONBOARD_PASSWORD`. Run `logout` to clear stored tokens.
