# Developer Integration (Local Corpus Only)

Use this reference for App Intents and App Shortcuts guidance without web fetches.

## Rule
- Use only content already present in `shortcuts-docs-corpus`.
- Do not call external documentation URLs from this skill.

## Where to Search in Corpus
- Developer docs text: `expert-pack/text/developer/`
- WWDC session text/transcripts: `expert-pack/text/wwdc/`
- Developer/source manifest metadata: `expert-pack/manifests/source_catalog.tsv`

## Useful Search Queries
```bash
uv run scripts/search_expert_chunks.py --group developer --query "AppShortcutsProvider appShortcuts"
uv run scripts/search_expert_chunks.py --group developer --query "creating your first app intent"
uv run scripts/search_expert_chunks.py --group developer --query "ShortcutsLink ShortcutsUIButton"
uv run scripts/search_expert_chunks.py --group wwdc --query "Develop for Shortcuts and Spotlight with App Intents"
uv run scripts/search_expert_chunks.py --group wwdc --query "Implement App Shortcuts with App Intents"
```

## Integration Checklist
1. Confirm intent boundaries and parameters.
2. Verify phrase/discoverability guidance for App Shortcuts.
3. Check Spotlight + Shortcuts surface behavior notes.
4. Identify migration implications if SiriKit is involved.
5. Produce an implementation + validation plan.
