# Exa HTTP Reference

## Base URL

- `https://api.exa.ai`
- Auth header: `x-api-key: <EXA_API_KEY>`

## Credentials

Keep `.env` beside this skill and populate it from `.env.example`.

Supported lookup order in the shell helper:
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

```bash
exa-search search "observability stack for small startups" 5
```

### Contents
- `POST /contents`
- Retrieve page contents for one or more known URLs

Example:

```bash
exa-search contents https://example.com/article
exa-search contents https://example.com/a https://example.com/b
```

### Find Similar
- `POST /findSimilar`
- Find pages similar to a known URL

Example:

```bash
exa-search find-similar https://example.com/article
```

### Answer
- `POST /answer`
- Get a grounded answer informed by Exa search results

Example:

```bash
exa-search answer "What is OpenTelemetry?"
```

### Research
- `POST /research/v1`
- Higher-effort synthesis mode

Example:

```bash
exa-search research "Compare modern web search APIs for agent use" exa-research
```

## Raw requests

Use `post` when you need payload control beyond the convenience wrappers.

```bash
exa-search post /search '{"query":"rust","numResults":5}'
exa-search post /contents '{"urls":["https://example.com"]}'
exa-search post /answer '{"query":"What is Bun?"}'
```

## Notes

- `search` is usually enough for primary discovery.
- `contents` is the direct replacement for a known-URL fetch workflow.
- `research/v1` is the direct HTTP path for Exa's deeper synthesis mode.
- For public OSS code-pattern lookup, `grep-app` is usually a better first tool than Exa.

## Validation

```bash
./scripts/test-exa-http.sh
```
