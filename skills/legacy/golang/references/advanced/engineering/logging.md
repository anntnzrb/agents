# Logging: Cross-Language Methodology

Two legitimate readers: operator reconstructing an incident; developer reproducing a bug. A line serving neither costs storage, noise, and attention. Stack-agnostic: use destination-skill guidance only for greenfield defaults; existing project practice overrides it.

## Rule 0: discover practice first

**BEFORE adding one log line, determine how the project logs.** Inspect logger initialization, wrapper modules, sibling call sites, and `AGENTS.md` / `CLAUDE.md`.

- Designated logger/wrapper → use it exactly: levels, field conventions, error-passing shape. Copy the nearest good call site, not personal habit.
- Preferred logging library → irrelevant. NEVER add a second framework where one exists.
- Raw `console.*` / `print` culture → follow it for user-facing CLI output; for diagnostics, propose structured logging rather than converting the project unilaterally.
- No logging (library, small CLI, script) → preserve the absence. A new library log changes consumer-visible behavior; a 40-line script needs no framework. Suggest logging, but add it only when requested or when observability is the task.

Never bypass the designated logger with bare `console.log` / `print`: that escapes stage routing, formatting, redaction, and shipping. Treat reserved field names, argument order, and the key required for an Error as project knowledge. Discover them in configuration and call sites; if agent docs omit the contract, record the discovered contract in the change.

## Greenfield setup

A new service gets exactly:

1. One init module exporting a ready logger; only it knows the stage. Call sites never inspect `NODE_ENV`-style variables.
2. Environment split: dev human-readable, pretty, colorized; prod structured, machine-parseable JSON to stdout. Same API; stage changes sink/format, never call sites.
3. Threshold: dev `debug`; prod `info`; `LOG_LEVEL`-style environment override.
4. The stack’s standard structured logger: repository choice or destination-skill greenfield guidance; never a hand-rolled logger.
5. Error-serialization proof: pass a real Error/exception through the PROD formatter and assert preserved type, message, and stack. Structured stacks have reserved-key contracts; violating one can yield `error: {}` instead of a stack trace. Write this one-line setup test.

## Levels: consumer, not severity

Choose a level by naming the consumer and its action. No named consumer → no line.

- `error`: alerting wakes a human NOW; service failed at a user-visible operation and cannot recover itself.
- `warn`: batch review through dashboards or weekly triage; request succeeded through an abnormal path such as retry, fallback, degraded mode, or suspicious data.
- `info`: incident timeline; a necessary state transition such as session/job/connection creation, completion, or destruction.
- `debug`: developer reproduces locally; detailed tracing; **does not exist in prod**.

`error` describes service failure, not request failure. A correctly handled 4xx is `warn` at most, or `info` for routine misses; reserve `error` for 5xx-class outcomes where the service could not do its job. A failure at `info` is invisible: messages saying “failed” require `warn` or `error`, never `info`.

## Placement: decisions, not work

Log at:

- boundaries: request in/response out, external calls and failures;
- state transitions: session, job, connection create/complete/destroy;
- decision points: retry, fallback, cache bypass, degraded mode;
- the one place an error is finally handled.

Never log inside pure functions, utilities, or private helpers; callers with context log outcomes.

- One event, one line. Log where an error is handled; propagation-only layers stay silent. Log-and-rethrow at every layer duplicates one incident.
- Returning an answer is not logging. Every path converting failure into a caller-facing signal; HTTP 5xx body, SSE error event, error string returned to an LLM as a tool result, or non-zero exit code; logs exactly once at its handling layer. With stacked conversion layers, mark the error logged using a symbol/flag on the error object so outer catch-alls skip it.
- Expected validation feedback returned normally: including LLM-consumed tool output such as “string not found”, lint findings, or a sandbox-boundary notice; is response content, not an event. Log only underlying genuine I/O/subprocess failures and security rejections.
- Put mechanical request/response logging in middleware once, never per handler. Exclude high-volume zero-signal paths such as health probes and metrics scrapes there as an exclusion set, not scattered `if` statements.

No speculative logs. “Might need it later” is not a consumer. Evidence may be a debugging session slowed by invisible state, an incident postmortem, or an alert needing a field.

## Line contract

- Stable, grep-able constant message; data in fields. Example `logger.warn({orderId, attempt}, "payment retry")`; never `` `retrying payment for ${orderId}` ``. Interpolated messages cannot be counted, aggregated, or alerted on.
- Correlation required: request-scoped lines carry trace/request id; entity-scoped lines carry entity id. Unjoinable lines are noise when logs matter.
- Name events semantically, e.g. `session.destroy` or `payment.fallback`; never positional names such as “Step 3”.
- No secrets: tokens, credentials, session cookies, and PII never enter logs. Sanitize URLs by stripping or redacting query parameters such as `token` and `key`.
- In LLM/agent systems, payload content belongs in tracing, not logs. Capture user messages, model responses, and tool outputs with the tracing product, such as a turn recorder or trace exporter. Logs carry a hash, length, and at most a short correlation excerpt.
- Logging must not break the program. If serialization or logging-wrapper I/O can fail, catch it, downgrade it to `warn` through a channel that cannot fail, and continue the operation. An empty catch around logging remains an empty catch.

## Debugging bridge

If a `debugging`-skill session takes extra rounds because no line showed the branch, value, or fallback, that invisibility is a defect adjacent to the bug. Ship the line that would have made diagnosis take one round: decision-point placement, consumer-chosen level, fields rather than interpolation, designated logger.

Temporary `print`, `dbg!`, or `console.log` added during diagnosis is a debug artifact; scrub it during cleanup. Keep a line only when its ongoing consumer is identifiable; otherwise it served only that session and is an artifact.
