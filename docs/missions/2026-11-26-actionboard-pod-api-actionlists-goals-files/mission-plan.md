# Mission Plan — ActionBoard Pod API integration: ActionLists, action items, Goals, and Files

- **Mission ID:** `actionboard-pod-api-actionlists-goals-files`
- **Brief:** [mission-brief.md](mission-brief.md)
- **Date:** 2026-11-26
- **Approved:** the operator replied "go" on 2026-11-26. Mission start 2026-11-27T01:26:39Z, base commit `7a2d68fc472c292607ec488d742e973544dd6fb3`. Board sync is on for this mission.
- **Dispatch order:** A1, then A2, then A3 and A4 in one Yellow Agent dispatch. A2 calls the functions A1 creates, so they run in sequence rather than in parallel. Within the Yellow dispatch, the A4 security review finishes before A3's live smoke test runs, and the smoke test does not run while a High finding is open.

## Agent Assignments

| ID | Agent | Task | Files Owned | Depends On | Acceptance |
|---|---|---|---|---|---|
| A1 | Blue Agent | Add GraphQL documents for every in-scope ActionList, action item, Goal, and File Service operation, using exact live-schema names, and a service module of wrappers that unwrap the `{success, message, data}` envelope. Upload and download reuse the existing edge presign, upload, and download helpers. | `src/skills/mission-report/scripts/actionboard_cli/operations.py`, `src/skills/mission-report/scripts/actionboard_cli/pod_services.py` (new) | none | Every new constant uses only fields present in the captured schema. A `success: false` response raises `RuntimeError` carrying the server's message. Update wrappers send the record's `_version`. Downloads are confined to the output directory. The module docstring lists every public function with its arguments and return shape. Verified by Yellow Agent in A3. |
| A2 | Red Agent | Add the `actionlist`, `action`, `goal`, and `files` subcommand groups, with handlers in a new module that `commands.py` only registers and dispatches. Status and priority arguments use the schema enums as choices; deletes require `--yes` under `--no-input` and an interactive confirmation otherwise. Write the three skills, the documentation, and the registry entry, then regenerate `dist/` with `python3 scripts/build.py`. | `src/skills/mission-report/scripts/actionboard_cli/pod_commands.py` (new), `src/skills/mission-report/scripts/actionboard_cli/commands.py`, `src/skills/ab-actionlist/SKILL.md` (new), `src/skills/ab-goals/SKILL.md` (new), `src/skills/ab-files/SKILL.md` (new), `src/skills/submit-mission/references/cli-reference.md`, `src/skills/mission-report/scripts/actionboard_cli/README.md`, `README.md`, `CHANGELOG.md`, `src/skills/skills-registry/actions-map.json`, `dist/` | A1 | The `--help` output of each group lists its verbs. Enum values are enforced and a bad value exits with status 2. The board defaults from `.actionboard/config.json` and `--board` overrides it. `python3 scripts/build.py --check` exits 0 and the existing suites still pass. Verified by Yellow Agent in A3. |
| A3 | Yellow Agent | Write `tests/report/test_pod_services.py` with a mocked opener, asserting the operation name and variables for every subcommand, plus envelope failure, enum rejection, `--json` output shape, deletes without `--yes`, path traversal, and `_version` on update. Validate every new constant against the captured schema with graphql-core 3.2.6 in a scratchpad virtual environment. Run the build check and all six suites. Run the live smoke test last, with cleanup. | `tests/report/test_pod_services.py` (new) | A1, A2 | The report gives the exact test commands with pass, fail, and skip counts, marks success criteria 1, 2, 3, 4, 6, and 7 as met or unmet with evidence, and lists by id any record left on the board after cleanup. Black Agent re-runs Yellow Agent's test command to verify it. |
| A4 | Yellow Agent | Security review of A1 and A2: token handling and redaction in output and errors, delete confirmation, download path safety, server-supplied text echoed to the terminal, and any new dependency. Runs before A3's live smoke test. | none | A1, A2 | Findings are rated by severity with `file:line` references, success criterion 5 is marked met or unmet with evidence, and no High finding is open when the live smoke test starts. |

Green Agent completed both recon passes (code map and live schema introspection) before the plan was approved and has no assignment. No file appears in more than one assignment.

## Skills Gap

| Capability | Status | Notes |
|---|---|---|
| GraphQL wrappers for `actionlists_*`, `actiongoals_*`, and `filemanager_*` | covered | Registry action `api-integration`, owned by Blue Agent. Reuses `api.graphql_request` and the edge presign helpers already in the CLI. |
| CLI subcommands, handlers, documentation, and the `dist/` rebuild | covered | Registry actions `code-implementation` and `file-scaffolding`, owned by Red Agent. |
| The three new `SKILL.md` files | covered | These are product files written to the existing pattern, like `ab-signup`, not skills the Agents need, so `skill-creator` is not used. |
| An authoritative API contract | covered | Registry action `codebase-recon` plus live introspection, both completed by Green Agent; `schema.json` and `schema.graphql` are saved in the session scratchpad. |
| Validating new operations against the schema | covered | Registry action `test-authoring`, owned by Yellow Agent, using graphql-core 3.2.6 as pinned by CI's `schema-contract.yml`. It is installed only in a scratchpad virtual environment after a `version-lookup` check; that action's precondition, a working Context7 MCP, is met. |
| Mocked-transport unit tests | covered | Registry action `test-authoring`, reusing the `MockActionBoardTransport` and `opener` pattern from `tests/report/test_submit_mission.py`. |
| A live smoke test on the operator's real board | covered | Registry action `test-authoring`. Its precondition, the operator's approval of board writes with cleanup, was met by "go"; the token is fresh from the operator's sign-in on 2026-11-26. |
| Security review | covered | Registry action `security-review`, owned by Yellow Agent. This is its first scored run, so its risk tier is classified when the report is written. |
| Mission documents, maturity scoring, and the dashboard | covered | Skills `mission-brief`, `mission-plan`, and `mission-report`, with `maturity.py` and `render_dashboard.py`; the operator level is L4. |
| Board sync | covered | Skill `submit-mission`; `mission_sync` is `ask` and the operator chose to sync this mission. |

No capability needs a new skill. ActionGraph is not a skills gap: the API itself is missing from the schema, so it is recorded under Out of Scope in the brief.

## Risk Register

| Category | Risk | Severity | Mitigation |
|---|---|---|---|
| Integration | Updates are rejected without the record's current `_version`, so status changes fail live even though mocked tests pass. | H | Update wrappers read the record and send `_version`; success criterion 4 reads each status back; the mocks assert that `_version` is sent. |
| Data-loss | Delete subcommands permanently remove board data. | H | `--yes` is required under `--no-input` and an interactive confirmation otherwise; the target is shown before deletion; success criterion 7's test proves no unconfirmed delete call is sent. |
| Integration | Introspection does not expose per-field authorization or RBAC, so some operations may need the main token or a role the pod token lacks. | M | Follow the existing pod-token convention; the live smoke test exercises every operation class and reports the server's message verbatim on failure. |
| Integration | Goal creation requires `userId`; the wrong identity source fails or attaches the goal to the wrong user. | M | Blue Agent derives it from the signed-in identity, and the live read-back checks `userId` and `profileId`. |
| Scope | ActionGraph was requested but is absent from the live schema. | M | It is explicitly deferred with the evidence and resumes when the operator provides its endpoint and contract. |
| Scope | `commands.py` is already 2,018 lines and four new groups would bloat it further. | M | Handlers go in the new `pod_commands.py` and logic in `pod_services.py`; `commands.py` receives registration and dispatch lines only. |
| Data-loss | A smoke test that fails midway leaves test records on the operator's board. | M | Records carry the `[ab-cli smoke]` prefix, cleanup always runs, and any leftover ids are reported for manual removal. |
| Technical | A server-supplied file name could write outside the download directory. | M | Downloads are confined to the output directory and success criterion 6 tests a `../` name. |
| Technical | The known swallowed token-refresh error could make agents see "not logged in" mid-mission. | M | The operator signed in fresh on 2026-11-26; if it recurs, re-run the browser login. The defect itself stays out of scope. |
| Technical | Secrets appear in `--json` output or error text. | M | Yellow Agent's A4 review and a search of captured outputs, recorded against success criterion 5. |
| Technical | The local Python is 3.14 while CI also runs 3.9, so newer syntax would break CI. | L | No `match` statements or PEP 604 union annotations; the CI matrix confirms when a pull request is opened. |
| Technical | The backend schema changes after the 2026-11-26 capture. | L | CI's live `schema-contract` check catches drift, and the captured schema is dated. |
