# Media Cookbook

## Audio overview

Create:

```bash
nlm audio-create <notebook-id> "Summarize the key points in a professional tone."
```

Check status: `nlm audio-list <notebook-id>`.

Download locally:

```bash
nlm audio-download <notebook-id> overview.mp3 --direct-rpc
```

Requires `--direct-rpc`.

## Video overview

Create:

```bash
nlm video-create <notebook-id> "Create a short overview video."
```

Check status: `nlm video-list <notebook-id>`.
