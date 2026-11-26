# React Best Practices

A packaged adaptation of Vercel Engineering's React and Next.js performance guidance for agents.

## Use

Start with `SKILL.md`. It routes a task to `rules/_sections.md`, the small set of matching rule files, and `references/upstream-updates.md`. Treat `references/upstream-updates.md` as corrections over the older rules and the compiled guide in `references/vercel-guide.md`.

## Package layout

- `rules/`: individual optimization rules, with `_sections.md` as the category index
- `references/vercel-guide.md`: adapted compiled upstream guidance
- `references/upstream-updates.md`: newer guidance and local corrections
- `metadata.json` and `NOTICE.md`: package metadata and upstream attribution
- `UPSTREAM.json`: pinned upstream repository, commit, and tree hash

## Maintenance

This package intentionally does not contain the upstream `package.json`, `src/`, or pnpm build workflow. Do not run `pnpm install`, `pnpm build`, or `pnpm validate` here; those commands operate on the upstream source repository, not this packaged skill.

To refresh the adaptation, compare upstream at the pin in `UPSTREAM.json`, port applicable rule changes, and update the commit and tree hash together. In the source repository, follow the upstream-drift workflow in `docs/skills.md`.

## Acknowledgments

Originally created by [@shuding](https://x.com/shuding) at [Vercel](https://vercel.com). See `NOTICE.md` for licensing and adaptation notes.
