# Model upgrade guidance

Bundled routing fallback ONLY if live migration guide fetch fails.

Latest/current/default/unspecified-model upgrade:
1. Run `uv run --script <skill-dir>/scripts/cli.py latest-model`.
2. Fetch returned `migrationGuideUrl` and `promptingGuideUrl` exactly.
3. Live guides canonical.
4. Remote retrieval failure → disclose bundled fallback in use.

Explicit GPT-5.6 Sol or GPT-5.6-family migration:
1. Preserve user's explicit target; NEVER run latest-model resolver.
2. Fetch live GPT-5.6 guidance:
   https://developers.openai.com/api/docs/guides/model-guidance?model=gpt-5.6
3. Read `references/upgrading-to-gpt-5p6-sol.md` for skill-specific migration judgment.
4. Read `references/prompting-guide.md` only when prompt changes are needed.

Other explicit model target:
- Preserve target; fetch its current official guidance.
- NEVER reuse GPT-5.6-specific defaults, API shapes, or compatibility rules for a different model.
