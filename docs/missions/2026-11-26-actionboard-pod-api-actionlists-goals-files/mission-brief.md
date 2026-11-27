# Mission Brief — ActionBoard Pod API integration: ActionLists, action items, Goals, and Files

**Objective:** Let the plugin's ActionBoard CLI and skills create and read ActionLists, read and update the status of ActionLists and their action items, manage board Goals, and list, upload, download, and delete board files, all through the live ActionBoard GraphQL API behind the existing edge proxy.

- **Mission ID:** `actionboard-pod-api-actionlists-goals-files`
- **Date:** 2026-11-26
- **Repository:** `ab-mission-command-center`, branch `main`, base commit `7a2d68fc472c292607ec488d742e973544dd6fb3`
- **Requested by the operator:** "add the new actionboard ai pod api integration to add actionlist and read and update actionlist status and action items. actionboard goals api and actionboard file service and actiongraph service api actions via the plugin". The operator chose live schema introspection as the source of the API contract. Green Agent captured the live schema (500 types, 295 root fields) on 2026-11-26.

## Scope

1. ActionLists (`actionlists_*`): create; list with a status filter and pagination; show one by a filtered list lookup, because the schema has no single-get operation; update fields and `actionListStatus`; delete with confirmation.
2. Action items (`actionlists_createAction`, `getAction`, `getAllActions`, `updateAction`, `deleteAction`): create an item in a list; list the items of a list with a status filter; get one by id; update fields and `ActionStatus`; delete with confirmation.
3. Goals (`actiongoals_*`): create with title and priority plus optional description, status, and dates; list by board; get one; update fields including status; delete with confirmation.
4. File Service (`filemanager_*`): list folders; create a folder, because an upload needs a `folderId`; list the files in a folder; upload a local file through the edge presign route and `filemanager_createFile`; download a file by id into a local directory; delete a file with confirmation.
5. Four new subcommand groups on the existing `submit_mission.py` CLI, `actionlist`, `action`, `goal`, and `files`, which default the Pod and Board to `.actionboard/config.json`, accept a `--board` override, and support `--json` and `--no-input`.
6. Three thin skills, `ab-actionlist`, `ab-goals`, and `ab-files`, that tell an agent how to run those commands, built to the Claude, Antigravity, OpenCode (including commands), and Codex targets.
7. A registry entry in `actions-map.json`, plus updates to the CLI reference, the CLI README, the root README, and the `## Unreleased` section of the changelog.
8. Mocked-transport unit tests, validation of every new GraphQL document against the captured live schema, and a live smoke test on the operator's board that cleans up after itself.

## Out of Scope

1. ActionGraph. No ActionGraph, graph, node, or edge type or operation exists in the live schema. It is deferred until the operator supplies its endpoint and API contract, which may live on the pod gateway rather than in GraphQL.
2. ActionList transfer, accept, reject, assign, bookmark, comments and replies, the cross-board master list, and the shared list.
3. Goal bulk delete, and renaming or deleting folders.
4. The pod-gateway REST API (`/v3/*`) and the `actionboard-ai` MCP plugin.
5. Linking missions to ActionLists or Goals; the schema has no such relationship.
6. The known `status` defect that reports a session as logged in whenever a refresh token is stored, and the swallowed refresh error behind it. This stays a separate follow-up.
7. A version bump, a release, or reinstalling the plugin.
8. Committing, pushing, or opening a pull request, unless the operator asks afterwards.

## Success Criteria

1. **Every new GraphQL document is valid against the live schema.** `graphql.validate()` from graphql-core 3.2.6, the version CI pins, returns zero errors for each new `QUERY_*` and `MUTATION_*` constant when checked against the captured `schema.json`. Checked by Yellow Agent.
2. **The build is clean and every suite passes.** `python3 scripts/build.py --check` exits 0, and the guard, build, install, maturity, report, and installer unittest suites each report `OK`, including the new `tests/report/test_pod_services.py`. Checked by Yellow Agent with exact counts, and re-run by Black Agent.
3. **The CLI surface matches the scope.** The `--help` output of `actionlist`, `action`, `goal`, and `files` lists every in-scope verb, and a status or priority value outside the schema enum exits with status 2. Checked by Yellow Agent.
4. **The live round trip works on the board "Actionboard Mission Board".** Using `--no-input --json`, the CLI creates an ActionList, adds an action item, moves the item from `New` to `In_Progress` to `Done`, moves the list to `Done`, creates a goal and moves it from `PENDING` to `IN_PROGRESS` to `COMPLETED`, uploads a file and downloads it again with an identical SHA-256 digest, and each read-back shows the new status. Every record it created is then deleted and a final listing shows none remain. Checked by Yellow Agent's live smoke test.
5. **No secret leaks.** No access token, refresh token, password, or `Authorization` header value appears in command output, `--json` output, error messages, or test fixtures. Checked by Yellow Agent's security review and a search of the captured outputs.
6. **Downloads cannot escape their directory.** A server-supplied file name such as `../../evil` is written inside the chosen output directory or refused. Checked by a unit test.
7. **Deletes are never silent.** Under `--no-input` and without `--yes`, every delete command exits non-zero and sends no delete mutation. Checked by a unit test that counts delete calls.

## Constraints

1. The CLI talks GraphQL through the edge proxy and reuses the existing pod-token path (`_resolve_pod_token_and_profile`); no new runtime dependency is added, and the code stays Python 3.9+ standard library only so it runs on Windows (`py`), macOS, and Linux.
2. `src/` is the canonical source and `dist/` is regenerated from it by `scripts/build.py`; nobody edits `dist/` by hand.
3. Operation, argument, field, and enum names come only from the live schema captured on 2026-11-26 in the session scratchpad (`schema-introspection/schema.json`).
4. Assumption: ActionList status is `actionListStatus` and action item status is `ActionStatus`, both using the `Actionlists_Status` enum (`New`, `Todo`, `Active`, `In_Progress`, `Done`, `AutoActionAiAgent`, `ActionAssistAgent`); Goal status uses `PENDING`, `IN_PROGRESS`, `COMPLETED` and Goal priority uses `LOW`, `MEDIUM`, `HIGH`.
5. Assumption: update mutations may require the record's current `_version` for AppSync conflict detection, so update wrappers read the record first and send it.
6. Assumption: the required `userId` on goal creation comes from the signed-in identity; Blue Agent confirms which claim and the live smoke test verifies it.
7. The live smoke test writes to the operator's real board; every record it creates is titled with the prefix `[ab-cli smoke]` and is deleted at the end. The operator's "go" on 2026-11-26 approved these writes.
8. The operator's certified maturity level is L4 (from `.actionboard/config.json`), and the mission runs in ActionList mode.
9. The operator's uncommitted changes to `.actionboard/config.json` and `.graphifyignore` stay out of the feature.
