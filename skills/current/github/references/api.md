# GitHub API through `gh api`



## Section index


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
- `--cache <duration>` may return cached data; disclose it when freshness matters
  Caching a read does not authorize a write.

## GraphQL

Invoke `gh api graphql` with a query and variables. Keep the query and selected fields
small, use cursor pagination, and filter returned `data`/errors explicitly:

```text
gh api graphql --method POST \
  -f query='query($endCursor:String) { viewer { repositories(first:100, after:$endCursor) { nodes { nameWithOwner } pageInfo { hasNextPage endCursor } } } }' \
  --paginate --slurp --jq '[.[].data.viewer.repositories.nodes[].nameWithOwner]'
```

Omit `endCursor` on the first request; `--paginate` supplies it for subsequent
pages. Do not seed it with `-f endCursor=null`: `--raw-field` sends the literal
string `null` as the cursor, and even a typed null is not the documented form.

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
