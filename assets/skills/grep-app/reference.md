# Grep.app HTTP Reference

## Base URL

- `https://grep.app/api/search`
- No auth required for public searches

## Parameters

### Required
- `q`: literal or regex pattern

### Search modifiers
- `regexp=true`: treat `q` as a regex
- `case=true`: match case
- `words=true`: whole-word-ish matching

### Filters
- `f.repo=owner/repo`
- `f.path=src/`
- `f.lang=TypeScript`

## Examples

Literal search:

```bash
grep-app search "useState(" f.lang=TypeScript
```

Regex search:

```bash
grep-app regex "useState\\(" f.lang=TypeScript
```

Scoped search:

```bash
grep-app search "errgroup.WithContext(" f.repo=golang/sync
```

## Response shape

The API returns JSON with:

- `time`
- `facets`
- `hits.total`
- `hits.hits[]`

Each hit includes fields like:

- `repo`
- `branch`
- `path`
- `content.snippet`
- `total_matches`

## Notes

- The response snippets are HTML, not plain text.
- Facets are useful for narrowing a broad first pass before repeating the query with `f.repo`, `f.path`, or `f.lang`.
