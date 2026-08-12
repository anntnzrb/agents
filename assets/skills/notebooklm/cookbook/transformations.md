# Transformations Cookbook

## Summarize sources
Summarize specific notebook sources:

```bash
nlm summarize <notebook-id> <source-id-1> <source-id-2>
```

Ask the user which sources to include.

## Explain concepts from sources
Ask for explanations based on selected sources:

```bash
nlm explain <notebook-id> <source-id-1> <source-id-2>
```

Fetch source IDs with `nlm sources <notebook-id>`.

## Generate a study guide
Turn sources into a study guide:

```bash
nlm study-guide <notebook-id> <source-id-1> <source-id-2>
```

For structured outputs, also try `outline`, `faq`, `briefing-doc`, `timeline`, or `toc`.
