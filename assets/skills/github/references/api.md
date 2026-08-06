# GitHub API through `gh api`

**Covers:** REST endpoints, GraphQL, placeholders, typed/raw fields, input bodies,
methods, pagination, slurp, previews, host selection, output filters, and errors.

**Safe default:** use a read-only explicit endpoint, explicit host/repository, an
explicit HTTP method, minimal fields, and `--jq`/`--template` at the boundary.

**Write boundary:** `gh api` is an external mutation surface. Require explicit user
authorization before any non-GET request or request whose parameters/body can change
state; re-read the affected resource afterward. Never put tokens or secrets in an
endpoint, field, input file, example, transcript, or output.

**Adjacent handoff:** use `core.md` for target/auth/output/exit behavior,
`collaboration.md` or `automation.md` for a known object family, and
`stack-commands.md` for stack REST/GraphQL boundaries.

## Invocation and method safety

```text
gh api <endpoint> [flags]
```

- REST endpoints use paths such as `repos/{owner}/{repo}/releases` or
  `repos/{owner}/{repo}/issues/{number}/comments`.
- `{owner}`, `{repo}`, and `{branch}` placeholders resolve from the selected local
  repository context. Prefer an explicit `--repo OWNER/REPO` where supported, and
  use `--hostname <host>` for the target host. If context is not verified, replace
  placeholders with an explicit target rather than guessing.
- The default request is GET **only when no parameters/body are supplied**.
  `--field`, `--raw-field`, and `--input` can switch the request to POST. Whenever
  fields, input, or mutation intent is present, pass an explicit `--method GET` for a
  read or the exact mutation method for a write.
- `--field key=value` performs typed conversion for booleans, numbers, `null`,
  placeholders, and `@file`; `--raw-field key=value` always sends a string. Choose
  deliberately; neither is a harmless annotation.
- `--input <file>` sends a request body. Inspect the file and exact endpoint/method;
  stdin is `--input -` and must not carry secrets into logs.
- `--header` changes request semantics and can expose sensitive material. Use only
  for a documented header/preview and never for an auth token.

## Read example

List every release title without requesting a browser or printing the full objects:

```text
gh api --method GET --hostname github.com \
  repos/OWNER/REPO/releases --paginate --slurp \
  --jq '[.[].[] | .name]'
```

For a single page, omit `--paginate --slurp` and select `.[].name`. With pagination,
`--paginate` follows API page links. `--slurp` wraps page results in an outer array;
shape the filter for the endpoint's page type and verify it against a small read.

Use `--jq` for selected values or `--template` for stable text. Keep response body
parsing separate from stderr. `--include` adds status/headers; `--verbose` is a
diagnostic that may expose request details and should not be used in normal output.

## Deliberately gated mutation example

This would comment on an issue and MUST NOT run without target verification and explicit
authorization:

```text
# Plan only until OWNER/REPO, issue number, body, and authorization are confirmed.
gh api --method POST --hostname github.com \
  repos/OWNER/REPO/issues/ISSUE_NUMBER/comments \
  --raw-field body='APPROVED COMMENT TEXT'
```

Before the call, read the issue and current comments, confirm the exact repository,
issue, body, host, and user authorization. After a successful call, re-read the issue
or comment list with a stable ID/URL. If it times out or returns an error, inspect
whether the comment landed before retrying; never blindly repeat a POST.

Use `--raw-field` for literal comment text. Use `--field` only when typed values are
intended; a string that looks like `true`, a number, or `null` can change type.

## Pagination and response shape

- REST `--paginate` follows `Link` headers. GraphQL pagination requires a query that
  accepts `$endCursor`, passes it to `after`, and returns `pageInfo { hasNextPage
  endCursor }`.
- `--slurp` is meaningful with `--paginate`; it combines page arrays/objects into an
  outer array. Document the resulting shape before writing jq filters.
- Use `--jq` for narrow extraction and avoid shell parsing of pretty JSON. Use
  `--template` when the consumer needs a text record per object.
- `--cache <duration>` may return cached data; disclose it when freshness matters.
  Caching a read does not authorize a write.

## GraphQL

Invoke `gh api graphql` with a query and variables. Keep the query and selected fields
small, use cursor pagination, and filter returned `data`/errors explicitly:

```text
gh api graphql --method POST \
  -f query='query($endCursor:String) { viewer { repositories(first:100, after:$endCursor) { nodes { nameWithOwner } pageInfo { hasNextPage endCursor } } } }' \
  -f endCursor=null --paginate --slurp --jq '[.[].data.viewer.repositories.nodes[].nameWithOwner]'
```

GraphQL uses POST for the query; it is still a read when the query has no mutation
field. Do not call a GraphQL mutation without explicit authorization. Handle a 200
response containing a nonempty `errors` array as a failure even if `gh` exits zero.

## Previews, errors, and host drift

- Use `--preview <name>` only when the official endpoint/manual requires it; preview
  names are version-sensitive and should not be guessed.
- Check response status with `--include` for a deliberate diagnostic. 401/403 means
  auth/permission or policy; 404 can mean wrong host, repository, endpoint, or rollout;
  409/422 can mean state/concurrency/validation. Report the body and exit code without
  exposing secrets.
- A successful HTTP response is not proof that the requested fields exist. Verify
  response shape, selected values, and any `errors` array before claiming success.
- If a known `gh <family>` command exists, prefer its stable contract over recreating
  it with `gh api`; use API for uncovered fields/endpoints or a documented need.

## Official references

- [gh api](https://cli.github.com/manual/gh_api)
- [REST API](https://docs.github.com/en/rest)
- [GraphQL API](https://docs.github.com/en/graphql)
