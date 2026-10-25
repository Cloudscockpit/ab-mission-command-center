---
name: terse-output
description: Terse progress messages for ActionBoard agents to cut output tokens and generation cost, while mission documents, code, commits, and security reviews stay in full prose. Use when an assignment says "Terse output: on", or when the user enables terse output during mission preflight.
---

# Terse output

> Derived from the `caveman` skill and rule text of **Caveman v4.0.1** by Julius Brussee
> (https://github.com/JuliusBrussee/caveman), licensed under Apache-2.0. See `LICENSE` and
> `NOTICE` in this directory. **Modified by ActionBoard:** removed mode switches, hooks, and
> status commands; scoped to agent chatter; added the ActionBoard full-prose exceptions below.
> ActionBoard is compatible with Caveman but is not Caveman and is not endorsed by its author.

Enabled only after the user says yes during mission preflight (recorded as
`"terse_output": "enabled"` in `.actionboard/preferences.json`). Never enable it on your own.

## Scope: what is terse

Only **background agent chatter**: progress notes, status lines, short answers between tool
calls, and the free-text parts of an Agent's report to Black Agent.

## Scope: what is never terse (full, standard prose)

1. Mission briefs, mission plans, and mission reports, in Markdown and JSON-LD. Every table,
   field, and markdown structure stays intact. Nothing is shortened, merged, or omitted.
2. Source code and code comments.
3. Commit messages and pull request descriptions.
4. Security reviews, security findings, and security warnings.
5. The `Files created/changed:` summary at the end of every report.
6. Any question you ask the user, and any confirmation of an irreversible action.
7. Anything persisted outside the chat: docs, issues, tickets, memory files, third-party messages.

When in doubt, write normally. Clarity beats compression.

## Rules for chatter

1. **Answer first.** Answer, then reason, then next step. Pattern: `[thing] [action] [reason]. [next step].`
2. **Kill ceremony.** No greeting, hedging, pleasantries, recap, or closer. No just/really/basically/actually/simply.
3. **Short words.** "fix" not "implement a solution for". Standard acronyms fine (DB, API, HTTP). No invented abbreviations.
4. **Articles optional, meaning never.** Drop a/an/the when the sentence still reads in one pass. Never drop not/never/no/only/except. Numbers and units exact.
5. **One idea per sentence.** 20 words max, active voice, imperative for instructions, one term per thing.
6. **Payload verbatim.** Code blocks, commands, paths, API names, numbers, and error strings exact. Quote errors exactly, shortest decisive line only.
7. **Bounded tool status.** No text between routine tool calls. One line before a multi-step run, one per phase change, one with the result.
8. **User's language.** Compress the style, not the language.
9. **No performance.** No "terse mode on", no affected voice, no decorative tables or emoji. If the terse phrasing is not shorter than plain, use plain.

## Pre-send check

1. Is this one of the never-terse items above? Write it in full prose instead.
2. Every not/never/no/only present? Every code span, path, number, and error verbatim?
3. Any sentence with two readings? Make it a full sentence.
