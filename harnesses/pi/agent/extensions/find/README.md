# Pi semantic find

`find` is a semantic code search tool. The model describes a behavior in plain language and gets back the file line ranges that implement it. A classifier model checks each range. For known strings or symbols, use `grep` or `rg`.

The tool registers with `codemode` exposure. It is never declared to the model directly: scripts call it as `await tools.find({ query, path? })`, and the `codemode` description lists its declaration. It requires the `codemode` tool to be active (`"defaultTools": ["+codemode"]`). The registration replaces Pi's built-in glob `find`, which is not active by default.

The design is a smaller port of [oh-my-pi's `find`](https://github.com/can1357/oh-my-pi/tree/main/packages/coding-agent/src/tools/jfind) (MIT, see [LICENSE](LICENSE)). It drops oh-my-pi's sketch-routing wave, internal URL scopes, and custom rendering.

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

- The first system message's `toolsAdded` lists `codemode` but not `find`.
- A `tool_execution_start` event for `find` follows the `codemode` call.
- In the `find` `tool_execution_end` event, `result.details.model` names the classifier that answered.
