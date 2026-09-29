# Create a verification skill

Generate a project-local skill at `<repo>/.agents/skills/verify-<app>/` that drives the real app and proves behavior: launch it, exercise a feature the way a user would, and capture evidence. Write it for the next agent, not for a human. That agent reads it cold, mid-task, and has never seen the app.

## 1. Interview the repo, not the user

Answer these from the codebase. Ask the user only for what you cannot observe.

- **Surface:** what does a user actually touch? A web UI, a CLI or TUI, a desktop app, an API, a mobile app, or a library. A repo can have several. Pick the primary one and note the rest.
- **Run:** how does the app start locally? Prefer the repo's own documented dev command (package scripts, Makefile, README quickstart). Note ports, environment variables, seed data, and auth.
- **Drive:** how can an agent interact with it programmatically? Use existing harnesses first: Playwright or Cypress specs, expect scripts, PTY helpers, endpoints you can call with curl, a debug port. Only then pick a generic recipe: browser or CDP for web and Electron, a tmux or PTY harness for CLI and TUI, plain HTTP for services.
- **Observe:** what evidence can be captured? Screenshots, terminal transcripts, response bodies, logs, exit codes, database state.
- **Isolate:** can two instances run side by side (ports, data directories, profiles)? If not, say so in the generated skill. Refusing to drive a shared instance twice beats corrupting the user's session.

If the checkout does not build or start as-is, fix that first or report it precisely before you generate. A skill written against a broken base teaches wrong steps. When an irrelevant missing asset blocks startup (a static directory the API never serves, a sample config), the generated skill may create it. Mark it as verification scaffolding and remove it in cleanup.

## 2. Generate the skill

Write `.agents/skills/verify-<app>/SKILL.md` with YAML frontmatter: `name: verify-<app>` and a `description` that names the app, the surface, and when to reach for it. Without frontmatter the skill never registers. Link it into `.claude/skills/` as described in the parent `SKILL.md`.

Include these sections. Ground each one in what the interview found. Leave no placeholders.

- **Launch:** the exact command that starts the app for verification, how to tell it is ready (a log line, a port answering, a prompt), and teardown. A short-lived CLI or TUI has no server to keep alive. There, launch means build the binary or install dependencies once, then start each drive in its own isolated PTY or tmux session.
- **Doctor:** one read-only check that answers "is this instance worth driving?" Check that the process is up, the version or build is right, the port is ours, and auth is valid. An agent runs this first whenever anything looks off.
- **Drive:** the harness recipe with real selectors and commands from this repo, not examples. Prefer stable handles (ARIA labels, data attributes, prompt strings, route paths) over coordinates and tab order.
- **Evidence:** what to capture for a proof and where it goes. State the proof standards:
  - Exercise the real user path, not internal setters or test-only endpoints.
  - Capture the action and the resulting state, not only the final screen.
  - Verify side effects (files written, rows inserted, messages sent) alongside what is visible.
  - Use mocks only where a production boundary already isolates the external system.
  - When the safe path is a dry run or test mode, observe what it actually skips (files, network, git refs). Do not trust its name. Some dry runs still touch the network or open a browser.
- **Cleanup:** how to tear down instances the run created. Kill what you started, never by process name. Cleanup removes instances and scratch state, never the evidence. Proof artifacts survive teardown in a location the skill names.
- **Helpers:** every script the skill ships is executable, and the skill body shows its invocation. A helper the reader has to reverse-engineer is not a helper.

### Helper CLI design

When the drive needs more than one-off commands, ship a small CLI inside the skill directory so agents run a command instead of writing a throwaway script. Group commands by job, for example inspection (`info`, `snapshot`, `screenshot`), navigation, interaction (`click`, `type`, `press`), performance (`trace`, `perf-metrics`, `wait-settle`), streaming (`console`, `network-log`), and health (`doctor`, `cleanup`).

- Keep the interface deep: a few commands that each do real work and compose.
- Give every command with destructive side effects a `--dry-run` option.
- Use subcommands so an agent discovers features one layer at a time.
- Make error messages say what went wrong and what to do instead.
- Write complete `--help` text.
- Return machine-readable output such as JSON.

## 3. Seed the feature map

Create `.agents/skills/verify-<app>/features/README.md` and one file per user-facing feature you can identify. Start with the top 3 to 5, found from routes, commands, menus, or docs. Follow the shape in [feature-map-example/](feature-map-example/README.md): a README index and one file per feature.

Each feature file answers, from the user's point of view, what the feature is, how to reach it, how to drive it with the harness, and what observable end state proves it works. Use exactly these four H2 sections, in order:

1. `Sub-features`
2. `How to get to it (user POV)`
3. `Driving it with <harness>`
4. `Gotchas`

The map is the repo's maintained verification source. A proof that drives one convenient entry point is incomplete when the map lists others.

## 4. Prove the generated skill before handing it over

Run its own instructions end to end once: launch, doctor, drive one mapped feature, capture evidence, clean up. One feature is enough, because the map exists so later runs can cover the rest. After cleanup, confirm the evidence still exists at the named location. A cleanup that deletes the proof fails this step.

Fix what fails. Run the generated cleanup after every failed iteration too, so broken attempts do not leave processes and ports behind.

## 5. Offer the maintenance loop

Point the user at `maintain` mode to keep the map accurate as the app changes. Suggest a cadence only if they ask.
