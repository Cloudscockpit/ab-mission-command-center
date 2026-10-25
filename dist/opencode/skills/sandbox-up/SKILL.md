---
name: sandbox-up
description: Provision an OpenShell sandbox for a Agent or a usecase, wait for Ready, and hand back the exec prefix. Use when an agent needs an isolated environment to run in.
---

> Paths written `<skill-dir>/...` are relative to the directory that contains this SKILL.md. `<arguments>` means what the user asked for when invoking this skill.

# Provision a sandbox

Request: **<arguments>**

Read `<skill-dir>/../openshell-admin/references/agent-profiles.md` for the
profile table before choosing sizing or policy.

1. **Resolve the profile.** The first argument is the usecase
   (`orchestrator` `data` `analysis` `action` `defense` `train` `inference` `scratch`);
   the second, if present, is the sandbox name. If the usecase is missing or
   ambiguous, ask once — do not guess between `read-only` and `read-write`.

2. **Preflight.** Confirm an active gateway and the target workspace:

   ```bash
   openshell whoami --output json
   openshell workspace list
   ```

   Empty workspace rows mean the subject has no membership. Report the `subject`
   and stop; only a Platform Admin can fix it.

3. **Show the plan.** Run the wrapper with `--dry-run` and surface the resolved
   image, CPU, memory, GPU, policy file, and labels. Wait for the user to confirm.

   ```bash
   <skill-dir>/../openshell-admin/scripts/openshell-provision.sh \
     --usecase <usecase> --name <name> \
     --workspace "${OPENSHELL_WORKSPACE:-default}" \
     --tenant <tenant> --pod <pod> --mission <mission> \
     --dry-run
   ```

4. **Create.** Re-run without `--dry-run`. The wrapper blocks until the gateway
   reports phase `Ready`. Do not report success from the compute side alone.

5. **Hand off.** Return only: sandbox name, workspace, phase, policy source and
   revision, exposed URLs, attached providers, and the `openshell sandbox exec -n <name> --`
   prefix the agent should use.

If the policy template still contains `REPLACE_` placeholders, say so plainly —
the sandbox will reach nothing until real hosts are filled in.
