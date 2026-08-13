# Upstream Status (Cargo Script)

## Canonical status URLs

- Tracking issue: `https://github.com/rust-lang/cargo/issues/12207`
- Cargo unstable docs: `https://doc.rust-lang.org/nightly/cargo/reference/unstable.html#script`
- RFC 3502 (cargo script): `https://github.com/rust-lang/rfcs/blob/master/text/3502-cargo-script.md`
- RFC 3503 (frontmatter): `https://github.com/rust-lang/rfcs/blob/master/text/3503-frontmatter.md`

## Current stabilization posture

As of latest checked state:

- tracking issue remains open
- label includes `S-waiting-on-feedback`
- feature remains nightly-gated (`-Zscript`)

## Open items worth checking before promises

- edition warning behavior without explicit frontmatter edition
- output-noise improvements for no-change builds
- rust-analyzer end-to-end support status
- command surface gaps (`clippy`, publish/package/install-path constraints)

## Quick live verification commands

```sh
gh issue view 12207 --repo rust-lang/cargo --json number,title,state,labels,updatedAt,url
gh issue view 16598 --repo rust-lang/cargo --json number,title,state,labels,updatedAt,url
gh issue view 16388 --repo rust-lang/cargo --json number,title,state,labels,updatedAt,url
gh issue view 15318 --repo rust-lang/rust-analyzer --json number,title,state,updatedAt,url
gh issue view 20558 --repo rust-lang/rust-analyzer --json number,title,state,updatedAt,url
```

## Guidance for agent output

- Never claim stabilization date unless issue/PR explicitly sets one
- Phrase as: "available on nightly behind `-Zscript`"
- Include constraints in same answer (publish/package/install-path/dependency limits)
