---
name: amp
description: "Use when working with Amp CLI modes, plugins, model routing, runners, orbs, or sync-managed Amp settings."
license: AGPL-3.0-or-later
---

# Amp

Identify which Amp state the task changes before choosing a command or checkout:

- Amp user-plugin modes live in the personal plugins repository. Read [mode authoring](references/modes.md) before changing one.
- Account model-provider routers live in Amp configuration. Read [model routing](references/routing.md) before changing a mapping.
- Runner processes live on their hosts. Read [runners](references/runners.md) before restarting one.
- Project orb lifecycle lives in the project settings and the repository's `.agents/`. Read [orbs](references/orbs.md) before changing setup or running threads in orbs.
- Sync-managed settings, instructions, and shared skills live in this configuration repository. Read its `AGENTS.md` and `harnesses/amp/README.md`; edit the source, not the generated Amp home.

Inspect the installed Amp CLI and the current target state. Use [Amp's documentation index](https://ampcode.com/llms.txt) to find the relevant current reference; treat saved procedures and model IDs as leads, not live inventory. Use authorization already given in the request or session; seek approval for unrequested account writes, plugin pushes, and process restarts. A restart can interrupt active threads. After a change, read the resulting state at the boundary that owns it.

## Required follow-up reads

| Need | Read | When |
| --- | --- | --- |
| User-plugin agent modes and tool policy | `references/modes.md` | Creating, changing, or verifying a mode |
| Custom model providers and mappings | `references/routing.md` | Adding or changing a routed model |
| Runner reloads and service checks | `references/runners.md` | Restarting or diagnosing a runner |
| Orb setup, snapshots, and orb threads | `references/orbs.md` | Changing orb setup or running work in orbs |
