# Releases and repository security

**Covers:** `release`, `attestation`, `ruleset`, `ssh-key`, `gpg-key`, and
`licenses`.

**Safe default:** inspect the explicit repository/tag/asset/security scope with
structured output; use installed help for preview or version-sensitive flags.

**Write boundary:** release create/edit/delete/upload/delete-asset, attestation
policy or verification changes, ruleset create/update/delete, SSH/GPG key add/delete,
and any repository security setting are sensitive external or account writes. Require
explicit authorization. Never display key material, private signatures, tokens, or
secret file contents. Re-read public metadata after a write.

**Adjacent handoff:** use `core.md` for auth/output/exit controls, `api.md` for
custom rules/security endpoints, `automation.md` for Actions runs/secrets, and
`collaboration.md` for PR/review state.

## Releases and assets

Read before acting:

```text
gh release list --repo OWNER/REPO --json tagName,name,isDraft,isPrerelease,publishedAt,url

gh release view TAG --repo OWNER/REPO --json tagName,name,body,assets,isDraft,isPrerelease,url
```

- `gh release list/view/download` are reads/downloads. Downloads write local files;
  choose a destination explicitly and do not overwrite user files without approval.
- `gh release create TAG --repo OWNER/REPO` publishes a release and may create or
  point at a tag. Confirm target commit, title, notes, prerelease/draft state, and
  assets before authorization.
- `gh release edit`, `upload`, `delete-asset`, `delete`, and `verify` have different
  scopes. A release edit is not a tag rewrite; deleting a release/asset is
  destructive and may not remove the Git tag.
- `--generate-notes`, `--notes-file`, and editor/browser flags can derive or open
  content. Inspect generated text and use noninteractive input when authorized.
- Attestation verification may depend on repository visibility, artifact digest,
  Actions permissions, and CLI/server rollout. Report an unavailable verifier
  rather than weakening verification or treating a signature as trusted by default.

## Attestations

`gh attestation verify` is a read/verification operation when pointed at an artifact
and owner/repository. Capture the digest, signer/source repository, certificate or
predicate fields relevant to the question, and verification exit code. Do not claim
provenance from a filename or release title alone. Use `gh help attestation` because
subcommands and permission requirements are version-sensitive.

Attestation generation/policy changes, if exposed by the installed CLI, are sensitive
writes. Confirm the exact command and authorization; do not invent a fallback API.

## Rulesets and policy

`gh ruleset list`, `view`, and `check` inspect repository/organization rulesets and
branch/tag applicability. Use explicit owner/repository and include enforcement,
target, conditions, bypass actors, and rules in JSON where supported.

`gh ruleset create`, `edit`, and `delete` change enforcement. Before an authorized
write, record the current ruleset ID and effective scope; after it, re-read the
ruleset and run a read-only applicability check. A 403 can mean missing administration
scope, not an invalid ruleset. Preview/API availability varies by host.

## SSH and GPG keys

`gh ssh-key list` and `gh gpg-key list` expose public metadata only. Key add/delete
operations change account authentication/signing configuration:

- Confirm account and host, key fingerprint, title, and intended use
- Never paste private keys, passphrases, recovery codes, or full credential blobs into
  commands or reports.
- Require authorization immediately before `add` or `delete`; re-read the public
  fingerprint/status afterward.
- If a command emits more material than needed, stop and redact before storing any
  output. Do not use a key command to diagnose unrelated Git authentication.

## Licenses

`gh repo license view OWNER/REPO` reads the detected license and source text/metadata.
Treat license text as repository content, not as permission to change the repository.
If a license endpoint or subcommand is absent, use `api.md` only for the documented
read endpoint and report detection uncertainty. Adding or replacing a repository
license is a repository content/policy write; route the actual contribution through
`gh-contrib` after authorization.

## Preview and permission caveats

GitHub security surfaces may require preview headers, fine-grained permissions,
organization policy, or a newer server/CLI. Use `gh help <command>` and the official
manual for the installed version. A 404, 403, or unknown subcommand is evidence of
rollout/permission mismatch; do not retry with guessed preview names or downgrade
verification requirements.

## Official references

- [gh release](https://cli.github.com/manual/gh_release)
- [gh attestation](https://cli.github.com/manual/gh_attestation)
- [gh ruleset](https://cli.github.com/manual/gh_ruleset)
- [gh ssh-key](https://cli.github.com/manual/gh_ssh-key)
- [gh gpg-key](https://cli.github.com/manual/gh_gpg-key)
- [gh repo license](https://cli.github.com/manual/gh_repo_license)
