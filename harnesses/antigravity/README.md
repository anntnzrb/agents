# Antigravity CLI harness source

Sync installs Google's Antigravity CLI and publishes the `agy` wrapper. It publishes the children of this directory into `~/.gemini/config/`, `HARNESS.md` as `~/.gemini/config/AGENTS.md`, and `skills/current/` as `~/.gemini/config/skills/`.

No runtime configuration is managed yet. The CLI keeps its own `settings.json` in `~/.gemini/antigravity-cli/`, which sync does not touch.

## Generated home

`~/.gemini/config/` is the global customization root that the CLI shares with Antigravity 2.0 and the IDE. As of CLI 1.2.14, observed by capturing model requests, the CLI loads global rules from `~/.gemini/AGENTS.md` and `~/.gemini/config/AGENTS.md`, and global skills only from `~/.gemini/config/skills/`. It does not load `~/.gemini/antigravity-cli/AGENTS.md` or `~/.gemini/antigravity-cli/skills/`, despite the published docs.

To re-check after an upgrade, point a scratch `HOME` at the CLI with `modelProvider: "gemini"` in `~/.gemini/antigravity-cli/settings.json`, export `GEMINI_API_KEY` and `GOOGLE_GEMINI_BASE_URL` (a local HTTP listener), run `agy -p hi`, and search the captured request body for marker text placed in each candidate file.

## Install source

The adapter uses the per-platform manifests that `https://antigravity.google/cli/install.sh` queries (`<updater>/manifests/<os>_<arch>.json`, shape `{"version", "url", "sha512"}`). Each archive contains a single `antigravity` binary. Sync installs it under `~/.local/share/antigravity/cli/_versions/<version>/` and skips the installer's `agy install` step, which edits shell profiles.

The musl Linux build (`linux_<arch>_musl`) is not mapped; sync targets glibc hosts.

The CLI self-updates in the background. Sync still resolves the manifest on each launch and pins the wrapper to the version it installed.
