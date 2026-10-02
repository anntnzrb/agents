# Pi semantic find

`find` searches for semantic evidence in code, documentation, logs, and transcripts. A classifier checks each returned passage against the query. For known strings or symbols, use `grep` or `rg`.

The tool registers with `direct` exposure: the model can call it directly, and active codemode scripts can also call `await tools.find({ query, path? })`. The registration replaces Pi's built-in glob `find`. Codemode receives structured `{ model, results, coverage, artifact }`, not formatted text. Each result identifies its query and optional scope; its hits include path, line range, probability, snippet, and the classified passage text.

## Search several questions

Use either `query` with optional `path`, or a nonempty `searches` list. Do not mix them. Codemode can generate query-by-directory combinations:

```js
const queries = ["exponential retry backoff", "removal of expired sessions"];
const paths = ["src", "docs"];
const result = await tools.find({
  searches: paths.flatMap(path => queries.map(query => ({ query, path }))),
});
return result.results.map(({ query, path, hits }) => ({ query, path, hits }));
```

Within an invocation, searches reuse directory listings, identical keyword scans, and file reads. Queries for the same resolved directory share classifier requests: each candidate passage is judged independently against every query in that scope. Verified evidence discovered by any of those queries is available to all of them. Different scopes remain separate. One classifier work pool serves the entire batch; no cache survives the invocation.

Results preserve input order and retain all verified passages without a retrieval cap. `coverage.exhaustive` means every eligible passage in the requested scope was classified, not that ignored files, excluded formats, or secrets were inspected. Classification can still be wrong: probabilities are model judgments, not calibrated confidence.

The temporary JSONL `artifact` retains every judgment, including scores below the display threshold, with query index, query text, path, line range, and passage text. Use `jq` through Bash to filter or page it without loading the entire score record into codemode. Its last record reports whether classification completed. Failed or cancelled searches reject instead of returning success; completed scores remain in the temporary artifact. No persistent index or service is created. Text reports show only the strongest passages and identify omissions; structured results are not capped.

The design is a smaller port of [oh-my-pi's `find`](https://github.com/can1357/oh-my-pi/tree/main/packages/coding-agent/src/tools/jfind) (MIT, see [LICENSE](LICENSE)). It drops oh-my-pi's sketch-routing wave and internal URL scopes.

## Compact display

Direct calls keep the query and optional search scope visible during composition, execution, and completion. The pending label changes from `composing` to `searching`. Completed searches show unique-file and range counts, accented paths, muted line ranges, and classifier scores as percentages. Scores are model judgments, not guarantees of correctness. Compact mode omits snippets; expansion adds snippets and the classifier model.

Multi-search calls show their queries and scopes in the call label and use an indexed text report rather than merging differently attributed hits into the single-search grid. Expand the report to see all searches.

Compact results group by directory, relative to the explicit search scope when provided. Each row keeps `filename:lines · score` together. Groups are ordered by their strongest score, and ranges within each group by score. Long directory headings elide middle components with `…` when space requires it, unless that would create duplicate headings. Expansion shows full working-directory-relative paths. Scores of 90% or higher use green, 75–89% use normal text, and lower scores use yellow; these are visual bands, not calibrated confidence thresholds.

Compact mode shows the four strongest directories and at most three result ranges per directory. Directory headings include their best score. Header totals cover all returned results. A muted footer separately counts omitted directories and omitted ranges within shown directories, without counting ranges inside omitted directories twice. Expansion displays all returned results.

Compact groups use one to four columns, choosing the largest column count whose complete blocks fit the available pane width, measured in visible terminal columns with a small gutter. Remaining groups continue in another grid row. Layout is recalculated on resize; expansion stays stacked for readable snippets. Query, totals, and omission footer remain outside the columns.

No verified hits use a warning label, not an error. Failures retain the query and show a short diagnostic preview; expansion shows the full returned diagnostic. Codemode owns the surrounding UI for nested calls, so direct-call rendering does not replace codemode's display.

## Configure the classifier

The classifier is any Pi classifier model, named in Pi settings as `"<provider>/<model id>"`. Model IDs may contain `/`:

```json
{ "find": { "classifier": "cliproxy/typesafe/jev-1.13" } }
```

The value lives in [`../../settings.json`](../../settings.json). To swap models, change that value and run `/reload`. The `codemode` script `models.getAvailableOfType("classifier")` lists the classifier models that have credentials. Project `.pi/settings.json` can override the value only in trusted projects.

There is no fallback model. The call fails with the reason when the setting is missing, the model is unknown or has no credentials, or any classifier request fails. A partial result would hide lost coverage.

## How a search runs

1. `rg` lists the files that are not ignored. It skips lockfiles, build output, binaries, and credential files. It also counts query keywords per file to build an IDF-weighted lexical rank.
2. Lexical rank determines processing order only. There is no path-judgment gate or file shortlist.
3. Bounded workers read files and classify every window. Long lines are split without discarding their suffixes; split passages retain the original line number. Raw transcript JSON is searched as text, not parsed into conversation messages. Memory retains a bounded number of file buffers plus verified results, rather than all corpus contents; a single large file still needs memory for its contents and windows.

The tool returns passages with probability at least 0.5, strongest first. Classifier token usage is counted once per actual request and returned as the tool result's `usage`, so it counts toward session cost. Cancellation follows the calling turn's signal. Errors reject the batch rather than presenting partial coverage as success; in-flight workers settle before the search returns.

## Validate

Pi's host packages are installed only in the synced home. Run the tests from a copy that links them:

```sh
T=$(mktemp -d); cp -R harnesses/pi/agent/extensions/find "$T/find"
ln -s ~/.pi/agent/extensions/node_modules "$T/node_modules"
(cd "$T" && bun test find/)
git diff --check
```

For a live check, use a trusted temporary project whose `.pi/settings.json` sets `find.classifier` and `"defaultTools": ["+codemode"]`:

```sh
pi --approve --no-extensions -e builtin:codemode -e "$T/find/index.ts" --no-session --mode json -p \
	"Use codemode to run: return await tools.find({ query: 'where stale files are pruned' })"
```

In the JSONL output, check three things:

- The first system message's `toolsAdded` lists both `codemode` and `find`.
- A `tool_execution_start` event for `find` follows the `codemode` call.
- In the `find` `tool_execution_end` event, `result.details.model` names the classifier that answered.
