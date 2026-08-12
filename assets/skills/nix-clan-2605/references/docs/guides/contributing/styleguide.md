# Styleguide

Scope: internal/external documentation, blog posts, and Clan communication. Consistent style improves usability.

## Framework features

### Admonitions

Basic syntax:

```md
:::admonition[Title]{type=info collapsible open}
Collapsiple Info
:::
```

Types: `info` | `important` | `tip` | `example`.

```md
:::admonition{type=info}
Content
:::

:::admonition{type=important}
Content
:::

:::admonition{type=tip}
Content
:::

:::admonition{type=example}
Content
:::
```

Collapsible state:

```md
:::admonition{type=info collapsible open}
Default open
:::

:::admonition{type=info collapsible}
Default closed
:::
```

Custom title:

```md
:::admonition[Custom Title]{type=info}
Content
:::
```

### Code examples

```nix
let
  is = nix: nix;
in
{
  this = is "valid";
}
```

Highlight lines with a fence annotation:

```nix {2,4-6}
{
  this line is highlighted
  this line is NOT highlighted
  this line is highlighted
  this line is highlighted
  this line is highlighted
  this line is NOT highlighted
}
```

## Writing principles

### Audience and knowledge

Assume competence, not familiarity. Write for readers who know much about computing, up to but not including Clan. Assume:

- Basic computer operation
- Command-line familiarity
- General interest in systems configuration

Do not assume:

- Clan-specific concepts
- NixOS ecosystem details or grammar
- Deployment workflows

State required knowledge at the page start.

### Show, don't tell

A working example is the fastest route to understanding. Recommended order:

1. Minimal working code or command.
2. Brief explanation.
3. Edge cases and variations.
4. Relevant further links instead of inlined detail.

### Grammar and style

Use simple, direct sentences; split complex ideas into short sentences; avoid nested clauses. Describe the user-visible goal, not leaked implementation details.

### Content organization

Lead with the outcome. Use progressive disclosure:

1. State the goal in one sentence.
2. Show the simplest working example.
3. Explain concepts as needed.
4. Put advanced options separately or link to reference material.

Example:

Create a new webserver machine in your Clan:

```bash
clan machines create --name webserver
```

### Code examples

- Show one concept at a time.
- Use realistic, simple scenarios.
- Avoid dependencies on other examples.
- Use minimal comments; let code speak for itself.
- Paste examples directly, without alteration.

```nix
{
  clan.networking.targetHost = "192.168.XXX.XXX";
  services.openssh.enable = true;
}
```

### Hide Nix where possible

Nix knowledge is a barrier, not a feature:

- Prefer `clan` CLI commands.
- Show configuration as what the reader wants, not how Nix works.
- Explain Nix only in Clan context.

Add a machine:

```bash
clan machines create webserver
```

This creates `machines/webserver/default.nix`, configurable via NixOS.

### Teach Nix through examples

After hiding Nix where possible, teach the NixOS module system through patterns:

- Working example first; explanation after code.
- Link deeper concepts instead of inlining them.
- Link to `nix.dev` for optional learning.

### General rules

- Abbreviate keys, e.g. `ssh-ed25519 AAAAC3NzaC…`.
- Abbreviate IP addresses, e.g. `192.168.XXX.XXX`.
- Capitalize variables and prefix them with `$`, e.g. `$YOUR-CLAN-NAME`.
- Make variables directly usable in copy-paste.
- Do not describe missing code (`#elided`, `#omitted`).
- `machine`: Clan identity; `device`: hardware.

### Capitalization and terms

Use exactly:

- Clan
- GB / RAM / HDD
- bootable USB drive
- Wi-Fi / DHCP / DNS
- macOS / NixOS / Nix / Linux
- Flakes
- WireGuard
- ZeroTier
- git
- direnv
- Setup Device / Target Devices

### Mood, voice, person, tense

- Instructions: imperative mood; address the reader as “you”, not “the user”.
- Voice: active; make the subject perform the action.
- Descriptions: present tense, not tentative future tense.

### Word choice

- Avoid nominalizations; use the hidden verb directly (`Select`, not `Make a selection`; `Explain`, not `Provide an explanation`).
- Delete filler: `simply`, `just`, `easily`, `basically`, `obviously`.
- Replace `in order to` with `to`.
- Replace `allows you to` with the direct verb.
- Delete `it's worth noting that` and state the fact.
- Every word earns its place.

### Procedures and limitations

- One instruction per sentence; do not pack actions together.
- Keep key negatives prominent; do not bury limitations after positive claims.
- State unsupported behavior directly, e.g. `This service does not support multiple instances.`

### Terminology

Choose one term and use it consistently. Repetition improves technical clarity; do not swap synonyms (`machine`, not alternately `host` or `node`).

### Links

- Use descriptive link text; never `click here` or `this link`.
- Link only destinations directly relevant to the task.
- Do not send readers to generic background pages when a task-specific reference is needed.

### UI language

Match UI labels exactly, including wording, casing, and spacing. Example labels:

- Click **Generate a Key**.
- Click **Save Changes**.

UI words are part of the interface and documentation/interface consistency builds confidence. UI changes are difficult; no policy currently covers them. Comments and suggestions are welcome.

:::admonition{type=tip}
UI changes are difficult; no policy currently covers them. Comments and suggestions are welcome.
:::

### Clean system discipline

Local systems may contain cached credentials, installed tools, environment variables, and existing configuration. Do not write steps from memory on a development machine and assume they work everywhere.

- Start on a clean system: fresh VM or new user account.
- Take notes while performing the steps.
- Document every warning, prompt, and unexpected output.
- Consider WSL versus native Linux and existing versus absent keys.
- You need not test every matrix combination; identify which combinations diverge.

### Never type code; always copy-paste

- Copy commands and code from a terminal where you just ran them successfully.
- Never retype from memory.
- Paste directly from the shell or IDE.
- Replace sensitive values with `<YOUR-KEY>`, `<YOUR-HOST>`, and `<YOUR-TOKEN>`.

Memory-retyped commands introduce subtle errors, even for experienced developers.
