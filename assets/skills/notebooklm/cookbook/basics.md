# Basics Cookbook

Common NotebookLM CLI recipes.

## List and choose a notebook
Need a notebook ID:

```bash
nlm list
```

If multiple IDs appear, ask the user to choose one.

## Ask one headless question

```bash
nlm generate-chat <notebook-id> "What are the key takeaways?"
```

Prefer `generate-chat` for scripted/CI usage.

## Start an interactive chat

```bash
nlm chat <notebook-id>
```

If it fails due to sources, retry with `-skip-sources`.
