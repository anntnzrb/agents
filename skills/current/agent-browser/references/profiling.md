# Profiling

Chrome DevTools performance profiles during browser automation for performance analysis. Read before recording or diagnosing performance traces.

Related: [commands.md](commands.md) for full command reference; [SKILL.md](../SKILL.md) for quick start.

## Basic Profiling

```bash
# Start profiling
agent-browser profiler start

# Perform actions
agent-browser navigate https://example.com
agent-browser click "#button"
agent-browser wait 1000

# Stop and save
agent-browser profiler stop ./trace.json
```

## Profiler Commands

```bash
# Start profiling with default categories
agent-browser profiler start

# Start with custom trace categories
agent-browser profiler start --categories "devtools.timeline,v8.execute,blink.user_timing"

# Stop profiling and save to file
agent-browser profiler stop ./trace.json
```

## Categories

`--categories`: comma-separated Chrome trace categories. Default categories include:

- `devtools.timeline` — standard DevTools performance traces
- `v8.execute` — JavaScript execution time
- `blink` — renderer events
- `blink.user_timing` — `performance.mark()` / `performance.measure()` calls
- `latencyInfo` — input-to-latency tracking
- `renderer.scheduler` — task scheduling and execution
- `toplevel` — broad-spectrum basic events

`disabled-by-default-*` categories also included for detailed timeline, call stack, and V8 CPU profiling data.

## Use Cases

### Diagnosing Slow Page Loads

```bash
agent-browser profiler start
agent-browser navigate https://app.example.com
agent-browser wait --load networkidle
agent-browser profiler stop ./page-load-profile.json
```

### Profiling User Interactions

```bash
agent-browser navigate https://app.example.com
agent-browser profiler start
agent-browser click "#submit"
agent-browser wait 2000
agent-browser profiler stop ./interaction-profile.json
```

### CI Performance Regression Checks

```bash
agent-browser profiler start
agent-browser navigate https://app.example.com
agent-browser wait --load networkidle
agent-browser profiler stop "./profiles/build-${BUILD_ID}.json"
```

## Output Format

Output: JSON file in Chrome Trace Event format.

```json
{
  "traceEvents": [
    { "cat": "devtools.timeline", "name": "RunTask", "ph": "X", "ts": 12345, "dur": 100, ... },
    ...
  ],
  "metadata": {
    "clock-domain": "LINUX_CLOCK_MONOTONIC"
  }
}
```

`metadata.clock-domain`: host-platform-based; set on Linux or macOS, omitted on Windows.

## Viewing Profiles

Load the output JSON in:

- **Chrome DevTools**: Performance panel > Load profile (Ctrl+Shift+I > Performance)
- **Perfetto UI**: https://ui.perfetto.dev/ — drag and drop the JSON file
- **Trace Viewer**: `chrome://tracing` in any Chromium browser

## Limitations

- Chromium-based browsers only (Chrome, Edge); Firefox and WebKit unsupported.
- Trace data accumulates in memory while profiling is active, capped at 5 million events. Stop promptly after the area of interest.
- Stop data collection timeout: 30 seconds; if the browser is unresponsive, the stop command may fail.
