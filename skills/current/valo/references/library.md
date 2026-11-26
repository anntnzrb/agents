# The curation contract: vetting and maintaining library.json

## Contents

- What the library is
- Categories
- Machine readability values
- Vetting criteria
- Vet a new candidate
- Add or change an entry
- Domain matching and its limits
- Relationship to sources.json

## What the library is

`library.json` beside this file's skill root is the curated knowledge
registry: every Valorant resource that has been vetted, with a verdict.
Noiseless by construction means the library records judgments, never
popularity. An entity enters the library only after a human-grade vetting
pass, and it enters exactly once: adopted with the evidence that earned it,
or avoid with the noise documented. A third verdict, unclear, means vetted
but unproven: neither recommended nor noise, typically because evidence
stayed thin or the value proposition is real but narrow. Unclear entries are
memory exactly like the others: discovery skips them, and they are only
re-vetted when a category gap motivates a deeper pass, never by default.
Discovery never resurfaces a vetted entity, so no verdict is ever
re-litigated by accident.

```json
{
  "version": 1,
  "entries": [
    {
      "name": "valking.gg",
      "url": "https://valking.gg",
      "category": "stats-site",
      "status": "adopted",
      "machine_readable": "firecrawl-ok",
      "reason": "one line stating the evidence",
      "vetted_at": "2026-11-25"
    }
  ]
}
```

Every key is required. `vetted_at` is the ISO date of the vetting pass.
`reason` is one line stating the evidence behind the verdict, not a
description of what the entity is.

## Categories

- `stats-site`: aggregate match statistics: win rates, pick rates, tier
  lists, map balance.
- `creator`: a person or channel producing educational or analytical
  content: guides, VOD reviews, ranked commentary.
- `aim-tool`: aim trainers and mechanics practice software or routines.
- `vod-tool`: match replay and VOD review tooling, including stat overlays
  tied to the user's own games.
- `pro-meta`: professional play tracking: pro settings, crosshairs, agent
  pick rates in esports, roster and meta reporting.
- `community`: forums, subreddits, wikis, discords. Communities are noise by
  default; adoption requires exceptional signal density with active
  moderation.

## Machine readability values

- `firecrawl-ok`: the content survives the firecrawl scrape-to-markdown
  pipeline as parseable text.
- `server-rendered`: the data is in the plain HTML; curl suffices.
- `api`: a structured API exists and is usable.
- `no`: not machine-readable through available pipelines: JS walls the
  scraper cannot pass, data inside images or video.
- `unknown`: not yet tested.
- `n/a`: not applicable: a person, a community, anything whose value is not
  bulk machine extraction.

Machine readability decides whether an adopted stats site can also become a
fetch source in `sources.json`. It never decides adoption: a creator's value
is human consumption.

## Vetting criteria

Apply all four. Failure on any one is an avoid verdict with the failing
criterion in the reason.

1. Accuracy. Mechanics advice must reflect current mechanics: anything
   written before the mechanic changes of patches 9.10 and 11.08 is stale
   regardless of production quality, unless the author has updated it.
   Stats must be current-patch; a stats site showing last act's numbers as
   present truth is noise. Test one concrete claim against live data or the
   official patch notes before trusting anything else the entity says.
2. Currency. Stats and tier lists must update per patch. Creators must be
   active or their advice must be mechanics-independent. A resource frozen
   in a dead meta is noise for current questions.
3. Evidence over vibes. Claims must trace to data, demonstrable gameplay,
   or reproducible reasoning. Tier lists without published numbers, guides
   built on ranked anxiety, and content optimized for clicks over truth are
   vibes. High production quality is not evidence.
4. No bait-and-switch. Resources that exist to sell coaching, skins, or
   boosting, with content as the wrapper, are noise even when individual
   claims are accurate, because the incentives corrupt every verdict.

## Vet a new candidate

`discover` outputs `new_candidates`: registrable domains not yet vetted.
For each candidate:

1. Identify what the entity is and pick its category. One entity, one
   category: the primary value.
2. Check accuracy: find one concrete, checkable claim (a win rate, a
   mechanics explanation, a patch reference) and verify it against live
   data from this skill or the official patch notes.
3. Check currency: find the update cadence. For stats, look for the patch
   version displayed. For creators, the upload or update dates.
4. Judge evidence versus vibes across a sample of the content, not one
   page.
5. For stats sites, test machine readability: curl the page, then scrape it
   through the sibling firecrawl CLI. Record the outcome even when the
   verdict is avoid.
6. Write the verdict into `library.json` with the evidence in the reason,
   then re-run `discover` if useful: the entity no longer resurfaces.

Never vet a candidate from its own self-description. Never adopt on
reputation alone; the checkable-claim test is mandatory.

## Add or change an entry

1. Edit `library.json` directly. Run `library` after every edit: the CLI
   validates strictly on every `library` and `discover` run, and unknown
   categories, statuses, or machine-readability values fail the command
   with `LIBRARY_ERROR`.
2. Changing a verdict (adopted to avoid or the reverse) rewrites the entry
   in place: new status, new reason naming what changed, new `vetted_at`.
   Never delete an entry to silence it; the avoid registry is the memory
   that keeps noise out.
3. An adopted stats site that is machine-readable is a candidate for
   `sources.json`; follow the procedure in `references/sources.md` for
   that. Library adoption and fetch-source registration are separate
   decisions: the library judges trustworthiness, the registry wires a
   pipeline.

## Domain matching and its limits

Discovery cross-checks candidates by registrable domain: scheme, `www.`,
subdomains, and paths are stripped, and the last two labels of the host are
compared. `www.valking.gg`, `api.valking.gg`, and `valking.gg` are the same
entity. There is no public-suffix list, so a `co.uk` style entity would
collapse wrongly; do not vet entities whose identity lives on a multi-part
public suffix without adjusting the matcher.

Platform-hosted creators share a registrable domain with their platform:
a YouTube channel's domain is `youtube.com`. When the library holds any
entry on a platform domain, discovery filters every other candidate on that
platform too. This is accepted collateral for creators (discovery exists
primarily for stats sites), but when vetting a creator candidate, search
the library by name with `library --category creator` instead of relying on
domain memory.

## Relationship to sources.json

Two registries, two questions. `sources.json` answers "where does live data
come from": machine-parseable fetch sources with strict parsers and health
tracking. `library.json` answers "what should a human trust": curated
verdicts over sites, creators, and tools, machine-readable or not. An entity
can live in both (a trusted, parseable stats site) or only one (a trusted
creator, or a noise stats site that must never become a pipeline). Neither
registry references the other; the overlap is intentional.
