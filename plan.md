# skills validation / cleanup plan

## goals
- validate every skill under `assets/skills/` except `skill-creator`
- apply `skill-creator` guidance to improve skill structure, clarity, and trigger/use instructions
- move non-trivial inline scripts out of markdown into skill-local `scripts/` files
- keep tiny inline wrappers only when they are genuinely trivial (`agent-browser`-style and similar)
- preserve behavior while making skills easier to load, reuse, and maintain

## validation rubric
- frontmatter present and description clearly says when to trigger
- `SKILL.md` body stays workflow-oriented; large details pushed to refs/scripts/assets
- no large inline scripts in markdown; prefer `scripts/` + `source` / `bash` / `uv run`
- scripts use either strict POSIX `sh` or full `bash`, not mixed style
- refs/examples point to concrete script paths
- env/config handling documented where relevant
- synced layout assumptions avoided; prefer `SKILLS_DIR` / local relative discovery

## phases
1. inventory all skills + find inline script blocks / oversized skill bodies
2. patch direct-http/search/env skills already in flight
3. patch remaining skills with non-trivial inline scripts
4. audit each remaining skill for description / structure / references
5. run validation sweep, sync, and summarize remaining follow-ups

## tracking
- [x] inventory all skills
- [x] classify inline-script cases: keep-inline vs extract
- [x] patch extracted-script skills
- [x] per-skill structure/description audit complete
- [x] validation sweep complete
- [x] sync complete

## skill inventory
- [x] agent-browser
- [x] aoc
- [x] apple-shortcuts
- [x] ast-grep
- [x] brave-search
- [x] clojure
- [x] commit
- [x] context7
- [x] deepwiki
- [x] do
- [x] ecuabet
- [x] exa-search
- [x] gh-contrib
- [x] gh-discussions-answerer
- [x] gleam
- [x] go
- [x] golang
- [x] grep-app
- [x] java-oop-assignment
- [x] jupyter
- [x] mcporter
- [x] n8n
- [x] nix
- [x] nixpkgs-update
- [x] notebooklm
- [x] python
- [x] react-best-practices
- [x] readiness-report
- [x] reddit
- [x] research
- [x] rust-script
- [x] summarize
- [x] vercel-cli
- [x] web-design-guidelines
- [x] xml-surgeon
- [x] youtube

## progress notes
- ran automated frontmatter/description/size validation across every skill except `skill-creator`
- moved non-trivial inline helper scripts out of markdown for `brave-search`, `context7`, `exa-search`, `grep-app`, and `reddit`
- added/updated helper smoke tests and shell syntax sweep across all `*.sh` under `assets/skills`
- reduced `agent-browser/SKILL.md` below the 500-line guideline by moving advanced material into `references/advanced.md`
- strengthened `vercel-cli` trigger description and documented env templates for remaining env-aware skills
