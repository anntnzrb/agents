# Summarize Recipes

Copy/paste recipes for common operations.

## 1) Summarize a web page

```text
uv run --script <skill-dir>/scripts/cli.py "https://example.com"
```

## 2) Extract markdown from a website (no LLM summary)

```text
uv run --script <skill-dir>/scripts/cli.py "https://example.com" --extract --format md
```

## 3) Force LLM markdown conversion for extraction

```text
uv run --script <skill-dir>/scripts/cli.py "https://example.com" --extract --format md --markdown-mode llm
```

## 4) Summarize YouTube with transcript pipeline

```text
uv run --script <skill-dir>/scripts/cli.py "https://www.youtube.com/watch?v=I845O57ZSy4" --youtube auto
```

## 5) Full transcript with timestamps

```text
uv run --script <skill-dir>/scripts/cli.py "https://www.youtube.com/watch?v=I845O57ZSy4" --extract --timestamps
```

## 6) Summarize video with inline slides

```text
uv run --script <skill-dir>/scripts/cli.py "https://www.youtube.com/watch?v=I845O57ZSy4" --slides
```

## 7) Slides + OCR in summary narrative

```text
uv run --script <skill-dir>/scripts/cli.py "https://www.youtube.com/watch?v=I845O57ZSy4" --slides --slides-ocr
```

## 8) Slides-only extraction command

```text
uv run --script <skill-dir>/scripts/cli.py slides "https://www.youtube.com/watch?v=I845O57ZSy4" --render auto
```

## 9) Transcribe-first handling for direct media URL

```text
uv run --script <skill-dir>/scripts/cli.py "https://example.com/file.mp4" --video-mode transcript
```

## 10) Summarize local audio/video

```text
uv run --script <skill-dir>/scripts/cli.py "/path/to/audio.mp3"
uv run --script <skill-dir>/scripts/cli.py "/path/to/video.mp4"
```

## 11) Summarize stdin

Send text to stdin with the platform-native shell, then use `-` as the input:

```text
uv run --script <skill-dir>/scripts/cli.py -
```

## 12) Use explicit model

```text
uv run --script <skill-dir>/scripts/cli.py "https://example.com" --model openai/gpt-5-mini
```

## 13) Use CLI backend provider

```text
uv run --script <skill-dir>/scripts/cli.py "<temp-dir>/input.txt" --cli codex --timeout 2m
```

## 14) Tune output size + hard cap

```text
uv run --script <skill-dir>/scripts/cli.py "https://example.com" --length 20k --max-output-tokens 2k
```

## 15) Change output language

```text
uv run --script <skill-dir>/scripts/cli.py "https://example.com" --lang de
```

## 16) JSON output for automation

```text
uv run --script <skill-dir>/scripts/cli.py "https://example.com" --json --metrics detailed
```

## 17) Debug extraction/model routing

```text
uv run --script <skill-dir>/scripts/cli.py "https://example.com" --verbose --metrics detailed
```

## 18) Cache operations

```text
uv run --script <skill-dir>/scripts/cli.py --cache-stats
uv run --script <skill-dir>/scripts/cli.py --clear-cache
```

## 19) Local ONNX transcriber setup helper

```text
uv run --script <skill-dir>/scripts/cli.py transcriber setup
uv run --script <skill-dir>/scripts/cli.py transcriber setup --model canary
```

## 20) Refresh OpenRouter free preset

```text
uv run --script <skill-dir>/scripts/cli.py refresh-free
uv run --script <skill-dir>/scripts/cli.py refresh-free --set-default
```

## 21) OpenRouter forced model id

After setting `OPENROUTER_API_KEY` in the environment:

```text
uv run --script <skill-dir>/scripts/cli.py "https://example.com" --model openrouter/meta-llama/llama-3.3-70b-instruct:free
```

## 22) Firecrawl-first extraction fallback

After setting `FIRECRAWL_API_KEY` in the environment:

```text
uv run --script <skill-dir>/scripts/cli.py "https://example.com" --firecrawl always --extract --format md
```
