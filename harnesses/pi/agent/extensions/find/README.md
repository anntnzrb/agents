# Pi semantic find

`find` is a semantic code search tool. The model describes a behavior in plain language and gets back the file line ranges that implement it. A classifier model checks each range. For known strings or symbols, use `grep` or `rg`.

The tool registers with `direct` exposure: the model can call it directly, and active codemode scripts can also call `await tools.find({ query, path? })`. The registration replaces Pi's built-in glob `find`.

The design is a smaller port of [oh-my-pi's `find`](https://github.com/can1357/oh-my-pi/tree/main/packages/coding-agent/src/tools/jfind) (MIT, see [LICENSE](LICENSE)). It drops oh-my-pi's sketch-routing wave and internal URL scopes.

## Compact display

Direct calls keep the query and optional search scope visible during composition, execution, and completion. The pending label changes from `composing` to `searching`. Completed searches show unique-file and range counts, accented paths, muted line ranges, and classifier scores as percentages. Scores are model judgments, not guarantees of correctness. Compact mode omits snippets; expansion adds snippets and the classifier model.

Compact results group by directory, relative to the explicit search scope when provided. Each row keeps `filename:lines · score` together. Groups are ordered by their strongest score, and ranges within each group by score. Long directory headings elide middle components with `…` when space requires it, unless that would create duplicate headings. Expansion shows full working-directory-relative paths. Scores of 90% or higher use green, 75–89% use normal text, and lower scores use yellow; these are visual bands, not calibrated confidence thresholds.

Compact mode shows the four strongest directories and at most three result ranges per directory. Directory headings include their best score. Header totals cover all returned results. A muted footer separately counts omitted directories and omitted ranges within shown directories, without counting ranges inside omitted directories twice. Expansion displays all returned results.

Compact groups use one to four columns, choosing the largest column count whose complete blocks fit the available pane width, measured in visible terminal columns with a small gutter. Remaining groups continue in another grid row. Layout is recalculated on resize; expansion stays stacked for readable snippets. Query, totals, and omission footer remain outside the columns.

No verified hits use a warning label, not an error. Failures retain the query and show a short diagnostic preview; expansion shows the full returned diagnostic. Codemode owns the surrounding UI for nested calls, so direct-call rendering does not replace codemode's display.

## Configure the classifier

The classifier is any Pi classifier model, named in Pi settings as `"<provider>/<model id>"`. Model IDs may contain `/`:

```json
{ "find": { "classifier": "opencode/jev-1.13-free" } }
```

The value lives in [`../../settings.json`](../../settings.json). To swap models, change that value and run `/reload`. The `codemode` script `models.getAvailableOfType("classifier")` lists the classifier models that have credentials. Project `.pi/settings.json` can override the value only in trusted projects.

There is no fallback model. The call fails with the reason when the setting is missing, the model is unknown or has no credentials, or any classifier request fails. A partial result would hide lost coverage.

## How a search runs

1. `rg` lists the files that are not ignored. It skips lockfiles, build output, binaries, and credential files. It also counts query keywords per file to build an IDF-weighted lexical rank.
2. The classifier judges the top 96 lexical candidates by path, in batches of `bool` questions.
3. The tool cuts the 12 strongest files into windows of about 2.5 KB. It sends the 8 strongest windows of each file to the classifier, which checks whether each window implements part of the query.

The result lists ranges with probability at least 0.5, strongest file first, with at most 2 ranges for each of 8 files. Classifier token usage is returned as the tool result's `usage`, so it counts toward session cost. Cancellation follows the calling turn's signal.

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
