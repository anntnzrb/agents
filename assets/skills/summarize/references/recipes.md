# Summarize Recipes

Copy/paste recipes for common operations.

## 1) Summarize a web page

```bash
bun x @steipete/summarize "https://example.com"
```

## 2) Extract markdown from a website (no LLM summary)

```bash
bun x @steipete/summarize "https://example.com" --extract --format md
```

## 3) Force LLM markdown conversion for extraction

```bash
bun x @steipete/summarize "https://example.com" --extract --format md --markdown-mode llm
```

## 4) Summarize YouTube with transcript pipeline

```bash
bun x @steipete/summarize "https://www.youtube.com/watch?v=I845O57ZSy4" --youtube auto
```

## 5) Full transcript with timestamps

```bash
bun x @steipete/summarize "https://www.youtube.com/watch?v=I845O57ZSy4" --extract --timestamps
```

## 6) Summarize video with inline slides

```bash
bun x @steipete/summarize "https://www.youtube.com/watch?v=I845O57ZSy4" --slides
```

## 7) Slides + OCR in summary narrative

```bash
bun x @steipete/summarize "https://www.youtube.com/watch?v=I845O57ZSy4" --slides --slides-ocr
```

## 8) Slides-only extraction command

```bash
bun x @steipete/summarize slides "https://www.youtube.com/watch?v=I845O57ZSy4" --render auto
```

## 9) Transcribe-first handling for direct media URL

```bash
bun x @steipete/summarize "https://example.com/file.mp4" --video-mode transcript
```

## 10) Summarize local audio/video

```bash
bun x @steipete/summarize "/path/to/audio.mp3"
bun x @steipete/summarize "/path/to/video.mp4"
```

## 11) Summarize stdin

```bash
echo "content" | bun x @steipete/summarize -
pbpaste | bun x @steipete/summarize -
```

## 12) Use explicit model

```bash
bun x @steipete/summarize "https://example.com" --model openai/gpt-5-mini
```

## 13) Use CLI backend provider

```bash
bun x @steipete/summarize "/tmp/input.txt" --cli codex --timeout 2m
```

## 14) Tune output size + hard cap

```bash
bun x @steipete/summarize "https://example.com" --length 20k --max-output-tokens 2k
```

## 15) Change output language

```bash
bun x @steipete/summarize "https://example.com" --lang de
```

## 16) JSON output for automation

```bash
bun x @steipete/summarize "https://example.com" --json --metrics detailed
```

## 17) Debug extraction/model routing

```bash
bun x @steipete/summarize "https://example.com" --verbose --metrics detailed
```

## 18) Cache operations

```bash
bun x @steipete/summarize --cache-stats
bun x @steipete/summarize --clear-cache
```

## 19) Local ONNX transcriber setup helper

```bash
bun x @steipete/summarize transcriber setup
bun x @steipete/summarize transcriber setup --model canary
```

## 20) Refresh OpenRouter free preset

```bash
bun x @steipete/summarize refresh-free
bun x @steipete/summarize refresh-free --set-default
```

## 21) OpenRouter forced model id

```bash
OPENROUTER_API_KEY=sk-or-... bun x @steipete/summarize "https://example.com" --model openrouter/meta-llama/llama-3.3-70b-instruct:free
```

## 22) Firecrawl-first extraction fallback

```bash
FIRECRAWL_API_KEY=... bun x @steipete/summarize "https://example.com" --firecrawl always --extract --format md
```
