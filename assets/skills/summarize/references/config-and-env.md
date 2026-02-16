# Summarize Config and Environment

Configuration center: `~/.summarize/config.json`

## Precedence

- Model: `--model` > `SUMMARIZE_MODEL` > config `model` > built-in default (`auto`)
- Language: `--language|--lang` > config `output.language` > built-in (`auto`)
- Prompt: `--prompt|--prompt-file` > config `prompt` > built-in prompt
- Env vars: process env > config `env` > config `apiKeys` (legacy mapping)
- Theme: `--theme` > `SUMMARIZE_THEME` > config `ui.theme` > built-in (`aurora`)

## Minimal config examples

### Model default

```json
{
  "model": "openai/gpt-5-mini"
}
```

### Full config skeleton

```json
{
  "model": { "mode": "auto" },
  "models": {
    "fast": { "id": "openai/gpt-5-mini" }
  },
  "env": {
    "OPENAI_API_KEY": "sk-...",
    "OPENROUTER_API_KEY": "sk-or-..."
  },
  "output": { "language": "auto" },
  "prompt": "Explain like I am five.",
  "ui": { "theme": "ember" },
  "cache": {
    "enabled": true,
    "ttlDays": 30,
    "maxMb": 512,
    "media": {
      "enabled": true,
      "ttlDays": 7,
      "maxMb": 2048,
      "verify": "size"
    }
  },
  "slides": {
    "enabled": false,
    "ocr": false,
    "dir": "slides",
    "sceneThreshold": 0.3,
    "max": 6,
    "minDuration": 2
  },
  "cli": {
    "enabled": ["claude", "gemini", "codex", "agent"],
    "autoFallback": {
      "enabled": true,
      "onlyWhenNoApiKeys": true,
      "order": ["claude", "gemini", "codex", "agent"]
    }
  }
}
```

## Common environment variables

### Model/provider keys

- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`
- `GEMINI_API_KEY` (or `GOOGLE_GENERATIVE_AI_API_KEY`, `GOOGLE_API_KEY`)
- `XAI_API_KEY`
- `Z_AI_API_KEY` (or `ZAI_API_KEY`)
- `NVIDIA_API_KEY`
- `OPENROUTER_API_KEY`

### API endpoint overrides

- `OPENAI_BASE_URL`
- `OPENAI_WHISPER_BASE_URL`
- `ANTHROPIC_BASE_URL`
- `GOOGLE_BASE_URL` (alias: `GEMINI_BASE_URL`)
- `XAI_BASE_URL`
- `Z_AI_BASE_URL`

### CLI backend binaries

- `CLAUDE_PATH`
- `CODEX_PATH`
- `GEMINI_PATH`
- `AGENT_PATH`

### Extraction/transcription helpers

- `FIRECRAWL_API_KEY`
- `APIFY_API_TOKEN`
- `YT_DLP_PATH`
- `SUMMARIZE_YT_DLP_COOKIES_FROM_BROWSER`
- `SUMMARIZE_TRANSCRIBER`
- `SUMMARIZE_ONNX_PARAKEET_CMD`
- `SUMMARIZE_ONNX_CANARY_CMD`
- `FAL_KEY`
- `GROQ_API_KEY`

### UI/behavior toggles

- `SUMMARIZE_MODEL`
- `SUMMARIZE_THEME`
- `SUMMARIZE_TRUECOLOR`
- `SUMMARIZE_NO_TRUECOLOR`
- `OPENAI_USE_CHAT_COMPLETIONS`

## Operational notes

- Config parsing is lenient JSON5-style, but comments are not allowed.
- Unknown keys are ignored.
- `--no-cache` bypasses summary cache only.
- Use `--no-media-cache` to bypass media file cache.
- `free` preset can be regenerated with `refresh-free`.
