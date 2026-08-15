# Agent configuration

This repository is the source of truth for shared agent instructions, skills, harness configuration, launch wrappers, and managed tools.

The sync application copies committed configuration into tool homes and keeps generated launchers current. Edit this repository, not `~/.pi`, `~/.omp`, `~/.codex`, or other generated targets.

## Quick start

```bash
git clone https://github.com/anntnzrb/agents.git ~/.config/agents
cd ~/.config/agents
cp secrets.local.example.json secrets.local.json
$EDITOR secrets.local.json
bun ./sync/src/cli.ts
```

The first sync installs the pinned CLIProxyAPI release and verifies its committed SHA-256 checksum. Each harness package installs on its first launch.

See [Quickstart](docs/quickstart.md) for prerequisites, authentication, and first-run checks.

## Documentation

- [Documentation index](docs/index.md)
- [Repository layout](docs/repository-layout.md)
- [Sync](docs/sync.md)
- [Harnesses](docs/harnesses.md)
- [Skills](docs/skills.md)
- [CLIProxyAPI](docs/cliproxyapi.md)
- [Development](docs/development.md)

## License

AGPL-3.0. See [COPYING](COPYING).
