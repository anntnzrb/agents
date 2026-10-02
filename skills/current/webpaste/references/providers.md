# Anonymous upload providers

Read before relying on retention or size limits, or when an upload fails. Policies change. Recheck the linked sources rather than treating these notes as guarantees.

## Pastes.dev

Checked on 2026-10-02: the landing page responds, but its static HTML does not expose the retention policy. The 90-day retention and missing UTF-8 charset are observations recorded in [issue #11](https://github.com/anntnzrb/agents/issues/11), not a fresh retention guarantee. Recheck the rendered site and the raw response headers before depending on them. No current maximum upload size was confirmed.

The API accepts text at `https://api.pastes.dev/post`, optionally gzipped, and returns a JSON key. Raw content is at `https://api.pastes.dev/<key>`. Text bytes can round-trip correctly while a browser displays mojibake because the response omits `charset=utf-8`. `--ascii-check` detects this risk without rewriting the report.

```bash
curl -fsSL --max-time 20 https://pastes.dev
curl -fsSL --max-time 20 https://api.pastes.dev/<existing-key> -D <temp-dir>/headers -o <temp-dir>/report
```

## Catbox

Checked on 2026-10-02: [API documentation](https://catbox.moe/tools.php) confirms multipart `reqtype=fileupload`, `fileToUpload`, and anonymous uploads without `userhash`. The [FAQ](https://catbox.moe/faq.php) confirms removal after two years without access. The [idle-upload announcement](https://blog.catbox.moe/post/821058172332769280/removing-idle-uploads) dates that policy to July 6, 2026. Downloads reset the inactivity clock. The homepage advertises a 200 MB upload limit.

The [operator's incident report](https://blog.catbox.moe/post/809324731954266112/missing-files-blank-uploads-commercial) documents unavailable files from August through October 2025, storage trouble, and blank uploads that return a link serving an empty page or 404. An upload response alone does not establish success. This CLI verifies the returned direct URL.

The same report describes filtering commercial or bulk low-quality AI uploads from non-residential IPs. Use a user machine; do not treat Catbox as a bulk CDN. Catbox is community-funded and run by one operator. Retention is not an availability promise. Point-in-time uptime percentages are not a service guarantee.

Upload one file per request with a timeout. Issue #11 records a two-file request hanging for over 120 seconds. Multipart encoding supplies an explicit filename, so spaces and U+202F do not need ad-hoc shell form escaping. Anonymous files cannot be deleted through the authenticated deletion API.

```bash
curl -fsSL --max-time 20 https://catbox.moe/
curl -fsSL --max-time 20 https://catbox.moe/tools.php
curl -fsSL --max-time 20 https://catbox.moe/faq.php
curl -fsSL --max-time 20 https://blog.catbox.moe/post/809324731954266112/missing-files-blank-uploads-commercial
curl -fsSL --max-time 20 https://status.catbox.moe/
```

## Litterbox

Checked on 2026-10-02: the [homepage](https://litterbox.catbox.moe/) advertises 1 GB uploads and expiry choices of 1, 12, 24, or 72 hours. The [API documentation](https://litterbox.catbox.moe/tools.php) confirms `resources/internals/api.php`, `reqtype=fileupload`, `fileToUpload`, and `time`. This CLI selects 72 hours. The tools page initially timed out, then responded on recheck.

Litterbox returns direct `litter.catbox.moe` links. Use it only for throwaway mirrors, not long-term evidence.

```bash
curl -fsSL --max-time 20 https://litterbox.catbox.moe/
curl -fsSL --max-time 20 https://litterbox.catbox.moe/tools.php
curl -fsSL --max-time 20 https://litterbox.catbox.moe/faq.php
```

## Other hosts

Issue #11 evaluated alternatives but did not request their implementation. Hosts requiring keys, accounts, or storage setup are outside the anonymous default. GitHub Gist ties uploads to an identity. A chat or issue attachment remains the primary human-facing copy when durability matters; an anonymous host supplies the direct-download mirror.
