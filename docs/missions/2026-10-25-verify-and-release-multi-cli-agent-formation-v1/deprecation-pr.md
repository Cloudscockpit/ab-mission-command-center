# Assignment 7 — deprecation PR draft (not opened)

**Status:** prepared, waiting for the user's approval. Nothing has been pushed to the old repository.

| Field | Value |
|---|---|
| Repository | `Cloudscockpit/actionboard-build-mission-pipeline` (public) |
| Base | `main` at `4c14058` (v0.6.1) |
| Head | `docs/point-to-multi-cli-successor`, local commit `1ed1f07` in the nested checkout `actionboard-build-mission-pipeline/` |
| Diff | `README.md` only, 13 lines added (a banner under the title) |
| Merge | Do not merge from here; the PR stays open for the user |

## Blocker to resolve first

The old repository is **public** and `Cloudscockpit/ab-mission-command-center` is **private**.
Public readers who follow the banner get a 404, and the marketplace commands in the banner fail
for anyone without access. Choose one before the PR is opened:

1. Make `ab-mission-command-center` public, then open the PR as drafted (recommended if 1.0.0 is
   meant for the same audience as v0.6.1).
2. Open the PR now as a draft and merge it only after the new repository goes public.
3. Reword the banner to say that a successor is in private preview, without a link.

## Commands to open it (after approval)

```sh
cd actionboard-build-mission-pipeline
git push -u origin docs/point-to-multi-cli-successor
gh pr create --repo Cloudscockpit/actionboard-build-mission-pipeline \
  --base main --head docs/point-to-multi-cli-successor \
  --title "docs: point to the multi-CLI successor repository" \
  --body-file ../docs/missions/2026-10-25-verify-and-release-multi-cli-agent-formation-v1/deprecation-pr-body.md
```

Add `--draft` for option 2.

## PR title

docs: point to the multi-CLI successor repository

## PR body

See [`deprecation-pr-body.md`](deprecation-pr-body.md) (passed to `gh pr create --body-file`).
