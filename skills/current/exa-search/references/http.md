# Exa HTTP Reference

## Base URL

- `https://api.exa.ai`
- Auth header: `x-api-key: <EXA_API_KEY>`

## Credentials

Keep `.env` beside this skill and populate it from `.env.example`.

Supported lookup order in `scripts/cli.py`:

- `EXA_SEARCH_ENV_FILE`
- `$SKILLS_DIR/exa-search/.env`
- nearest ancestor `skills/exa-search/.env`

Direct env vars still win:

- `EXA_API_KEY`
- legacy alias: `EXA_APIKEY`

## Direct endpoints

### Search

- `POST /search`
- Best default path for Exa search

Example:

```text
uv run --script <skill-dir>/scripts/cli.py search "observability stack for small startups" 5
```

### Contents

- `POST /contents`
- Retrieve page contents for one or more known URLs

Example:

```text
uv run --script <skill-dir>/scripts/cli.py contents https://example.com/article
uv run --script <skill-dir>/scripts/cli.py contents https://example.com/a https://example.com/b
```

### Find Similar

- `POST /findSimilar`
- Find pages similar to a known URL

Example:

```text
uv run --script <skill-dir>/scripts/cli.py find-similar https://example.com/article
```

### Answer

- `POST /answer`
- Get a grounded answer informed by Exa search results

Example:

```text
uv run --script <skill-dir>/scripts/cli.py answer "What is OpenTelemetry?"
```

### Research

- `POST /research/v1`
- Higher-effort synthesis mode

Example:

```text
uv run --script <skill-dir>/scripts/cli.py research "Compare modern web search APIs for agent use" exa-research
```

## Raw requests

Use `post` when you need payload control beyond the convenience wrappers.

```text
uv run --script <skill-dir>/scripts/cli.py post /search '{"query":"rust","numResults":5}'
uv run --script <skill-dir>/scripts/cli.py post /contents '{"urls":["https://example.com"]}'
uv run --script <skill-dir>/scripts/cli.py post /answer '{"query":"What is Bun?"}'
```

## Notes

- `search` is usually enough for primary discovery
- `contents` is the direct replacement for a known-URL fetch workflow
- `research/v1` is the direct HTTP path for Exa's deeper synthesis mode
- For public OSS code-pattern lookup, `grep-app` is usually a better first tool than Exa

## Validation

```text
uv run --script <skill-dir>/scripts/cli.py --help
```
