# Artifacts Cookbook

## List artifacts

```bash
nlm artifacts <notebook-id>
```

Alias: `nlm list-artifacts <notebook-id>`.

## Create an artifact

```bash
nlm create-artifact <notebook-id> note
```

Valid types: `note`, `audio`, `report`, `app`.

## Delete an artifact (destructive)

```bash
nlm delete-artifact <artifact-id>
```

MUST confirm with the user first.
