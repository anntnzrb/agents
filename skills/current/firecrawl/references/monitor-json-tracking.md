# JSON-Mode Change Tracking Reference

Configure monitors to produce structured, per-field key-value diffs (`diff.json`) and data snapshots rather than plain-text markdown diffs.

## Overview

By default, monitors compute unified Markdown diffs (`diff.text`). When downstream consumers (such as Slack bots, databases, or automation pipelines) require structured per-field delta events (e.g. `plans[0].price: "$20" -> "$25"`), configure `changeTracking` with a JSON schema.

## Specification Payload

Pass a JSON configuration file to `firecrawl monitor create`:

```json
{
  "name": "SaaS Plan Tracker",
  "goal": "Alert when plan prices or included quota limits change.",
  "schedule": { "text": "every 6 hours", "timezone": "UTC" },
  "targets": [{
    "type": "scrape",
    "urls": ["https://example.com/pricing"],
    "scrapeOptions": {
      "formats": [{
        "type": "changeTracking",
        "modes": ["json"],
        "prompt": "Extract pricing tiers, monthly prices, and included storage quotas.",
        "schema": {
          "type": "object",
          "properties": {
            "tiers": {
              "type": "array",
              "items": {
                "type": "object",
                "properties": {
                  "name": { "type": "string" },
                  "price": { "type": "string" },
                  "storage_gb": { "type": "number" }
                },
                "required": ["name", "price"]
              }
            }
          }
        }
      }]
    }
  }]
}
```

```bash
# Create monitor from JSON spec
firecrawl monitor create monitor-spec.json
```

## Structure of Changed Events

When changes occur, check inspection responses include the exact field diff and snapshot:

```json
{
  "url": "https://example.com/pricing",
  "status": "changed",
  "diff": {
    "json": {
      "tiers[1].price": {
        "previous": "$29/mo",
        "current": "$35/mo"
      },
      "tiers[1].storage_gb": {
        "previous": 50,
        "current": 100
      }
    }
  },
  "snapshot": {
    "json": {
      "tiers": [
        { "name": "Starter", "price": "$10/mo", "storage_gb": 10 },
        { "name": "Pro", "price": "$35/mo", "storage_gb": 100 }
      ]
    }
  }
}
```

## Dual Mode Tracking

To receive both structured per-field JSON diffs and markdown unified diffs side-by-side, specify both modes:

```json
"modes": ["json", "git-diff"]
```
