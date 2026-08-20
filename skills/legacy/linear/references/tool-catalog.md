# Linear MCP tool catalog

Snapshot: Linear MCP / MCPorter 0.12.3, 2026-07-16; 47 tools. Live schemas override this snapshot when inspected. Search only the relevant entity section or tool signature; NEVER load the whole catalog. Use it when the tool or exact recipe is unknown, or live discovery fails. A discovery failure MUST disclose possible snapshot drift. Input schemas do not define response fields; NEVER invent unobserved response fields.

Refresh command:
```text
mcporter list linear --schema
```

## Schema conventions

Signatures below encode the complete input schemas; `?` means optional. Every tool uses JSON Schema draft-07 (`$schema: http://json-schema.org/draft-07/schema#`) and rejects undeclared fields (`additionalProperties: false`). `string|null` means either type; `string[]` and `object[]` are arrays. `URI` means URI-formatted string. `ISO date/duration` and `ISO DateTime` retain those formats. Unless overridden below, list pagination is `limit?:number` (default 50, max 250), `cursor?:string`, and `orderBy?:createdAt|updatedAt` (default `updatedAt`). List filters are optional. Markdown inputs use literal newlines and special characters, not escape sequences; mentions use `@displayName` (for example `@johndoe`).

## Attachments

`get_attachment(id:string)`; retrieve attachment content by ID.

`prepare_attachment_upload(issue:string, filename:string, contentType:string, size:number, title?:string, subtitle?:string)`; prepare a direct upload for an existing issue. `issue`: ID or identifier such as `LIN-123`; `size`: exact positive byte count, smaller than 2 GB, schema maximum `9007199254740991`. Workflow MUST be: call prepare; PUT untransformed raw bytes outside MCP to `uploadRequest.url`; send every `uploadRequest.headers` value verbatim, including casing; after successful PUT call `create_attachment_from_upload` with `assetUrl`. Do not base64-encode or transform bytes; use `curl --data-binary @path` or `fetch(url, { method: 'PUT', body: blob })`. Omitting/modifying any signed header returns HTTP 403. Signed URL expires after 60 seconds. Prepare, PUT, and finalize one file before preparing another; NEVER batch prepare calls because earlier signed URLs can expire. `title` and `subtitle` are suggested finalize metadata.

Exact upload example:
```text
curl -X PUT --data-binary @file.png \
-H "content-type: image/png" \
-H "x-goog-content-length-range: N,N" \
-H "cache-control: public, max-age=31536000" \
-H 'Content-Disposition: attachment; filename="file.png"' \
"<uploadRequest.url>"
```

`create_attachment_from_upload(issue:string, assetUrl:URI, title?:string, subtitle?:string)`; link an already-uploaded asset to an existing issue; does not upload content. Use only after prepare returned `assetUrl` and `uploadRequest` and the raw PUT succeeded. If upload failed or URL expired, rerun prepare and upload. `title` defaults to filename or asset URL.

`create_attachment(issue:string, base64Content:string, filename:string, contentType:string, sha256:string, size?:number, title?:string, subtitle?:string)`; deprecated fallback for tiny files. Uploads base64 through the MCP worker and verifies SHA-256. Prefer prepare → direct PUT → create_attachment_from_upload. NEVER print/copy opaque `base64Content` through model-visible text; generate it mechanically from source bytes through programmatic argument construction. `sha256` must be a 64-character hex digest (`^[a-fA-F0-9]{64}$`); optional positive `size` (schema max `9007199254740991`) must equal decoded byte count when supplied and is recommended for clearer mismatch errors. Before calling, decoded SHA-256 MUST equal `sha256`.

Unix-like verification:
```sh
file="/path/to/file"
base64Content=$(base64 < "$file" | tr -d '\n\r')
sha256=$(shasum -a 256 "$file" | awk '{print $1}')
decodedSha256=$(printf '%s' "$base64Content" | base64 -d | shasum -a 256 | awk '{print $1}')
size=$(wc -c < "$file" | tr -d ' ')
decodedSize=$(printf '%s' "$base64Content" | base64 -d | wc -c | tr -d ' ')
```
`size` is optional; `decodedSize` MUST equal it if passed. `stat` can also obtain byte size.

PowerShell verification:
```powershell
$file = 'C:\path\to\file'
$bytes = [IO.File]::ReadAllBytes($file)
$base64Content = [Convert]::ToBase64String($bytes)
$sha256 = (Get-FileHash -Algorithm SHA256 -Path $file).Hash.ToLower()
$size = $bytes.Length
$decoded = [Convert]::FromBase64String($base64Content)
$decodedStream = [IO.MemoryStream]::new($decoded)
$decodedSha256 = (Get-FileHash -Algorithm SHA256 -InputStream $decodedStream).Hash.ToLower()
$decodedSize = $decoded.Length
```

`delete_attachment(id:string)`; delete attachment by ID.

## Agent skills

`list_agent_skills(limit?:number=50, cursor?:string, orderBy?:createdAt|updatedAt=updatedAt)`; list Linear Agent skills available to the authenticated user; limit max 250.

`get_agent_skill(id:string)`; retrieve an Agent skill, including its full Markdown instructions, by ID.

## Comments

Comment parent fields: `issueId` (ID/identifier), `projectId` (name/ID/slug), `initiativeId` (name/ID), `documentId` (ID/slug), `milestoneId` (UUID), and `statusUpdateId` (UUID). Where stated “exactly one parent,” pass exactly one. Resolve milestone names with `list_milestones`; resolve status updates with `get_status_updates`.

`list_comments(limit?:number=50, cursor?:string, orderBy?:createdAt|updatedAt=updatedAt, issueId?:string, projectId?:string, initiativeId?:string, documentId?:string, milestoneId?:string, statusUpdateId?:string, statusUpdateType?:project|initiative)`; exactly one parent is required. For issues, projects, and initiatives, returns top-level discussion threads plus inline description comments; inline comments have non-null `quotedText` containing referenced description text. `statusUpdateType` is valid only with `statusUpdateId`; omit it to check both project and initiative updates.

`save_comment(body:string, id?:string, issueId?:string, projectId?:string, initiativeId?:string, documentId?:string, milestoneId?:string, statusUpdateId?:string, statusUpdateType?:project|initiative, parentId?:string)`; create/update a comment. With `id`, update that comment. To create a new thread, pass `body` and exactly one parent: issue/project/initiative comments become top-level discussion threads; document/milestone comments become description comments. A status update has one thread; commenting on an update that already has one adds a reply. To reply to an existing thread, pass `parentId` and `body` while creating; the reply inherits the parent thread type and needs no entity reference. Parent reference fields are ignored with `id` or `parentId`; `statusUpdateType` is rejected in those cases. `body` is Markdown and MUST use literal newlines/special characters.

`delete_comment(id:string)`; delete a comment. An inline description comment with non-null `quotedText` anchors an editor mark, so its root MUST NOT be deleted; delete replies individually or resolve the thread.

## Cycles

`list_cycles(teamId:string, type?:current|previous|next)`; retrieve a team’s cycles. The prose says type may be “current, previous, next, or all,” but the input schema permits only `current`, `previous`, or `next`; use only schema-permitted values.

## Documents

`get_document(id:string)`; retrieve document by ID or slug.

`list_documents(limit?:number=50, cursor?:string, orderBy?:createdAt|updatedAt=updatedAt, query?:string, projectId?:string, initiativeId?:string, teamId?:string, creatorId?:string, createdAt?:ISO date/duration, updatedAt?:ISO date/duration, includeArchived?:boolean=false)`; list workspace documents; `query` searches; date filters mean created/updated after.

`save_document(id?:string, title?:string, content?:string, project?:string, issue?:string, initiative?:string, cycle?:string, team?:string, icon?:string, color?:string)`; create/update document. Omit `id` to create; provide it to update. On create, `title` and exactly one parent among `project`, `issue`, `initiative`, `cycle`, `team` are required. On update, a parent reparents the document. `project`: name/ID/slug; `issue`: ID/identifier such as `LIN-123`; `cycle`: name/number/ID, and when name/number is used `team` is also required to disambiguate; `team` attaches to team unless `cycle` is also supplied, when it disambiguates the cycle. `icon` is icon name or emoji code such as `Rocket` or `:eagle:`, not raw Unicode emoji. `color` is hex. `content` is Markdown.

`extract_images(markdown:string)`; extract/fetch images from Markdown, for viewing screenshots, diagrams, or other images embedded in Linear issues, comments, or documents; pass content containing image references.

## Issues

`get_issue(id:string, includeRelations?:boolean=false, includeCustomerNeeds?:boolean=false, includeReleases?:boolean=false)`; retrieve issue details including attachments and git branch name. Optional flags include blocking/related/duplicate relations, associated customer needs, and associated releases.

`list_issues(limit?:number=50, cursor?:string, orderBy?:createdAt|updatedAt=updatedAt, query?:string, team?:string, state?:string, cycle?:string, label?:string, assignee?:string|null, delegate?:string, project?:string, release?:string, priority?:number, parentId?:string, createdAt?:ISO date/duration, updatedAt?:ISO date/duration, includeArchived?:boolean=true)`; list workspace issues. `query` searches title/description; team/state/cycle/label/project/release accept name, ID, or slug as described by the field; `assignee` accepts user ID/name/email/`me`, or `null` for no assignee; `delegate` accepts agent name/ID. When user requests delegation to “Linear” or “the Linear agent,” `delegate` means the `Linear` app user specifically. `priority`: `0=None, 1=Urgent, 2=High, 3=Medium, 4=Low`.

`save_issue(id?:string, title?:string, description?:string, team?:string, cycle?:string|null, milestone?:string, priority?:number, project?:string|null, state?:string, assignee?:string|null, delegate?:string|null, labels?:string[], dueDate?:string, parentId?:string|null, estimate?:number|null, links?:{url:URI,title:string}[], setReleases?:string[], addReleases?:string[], removeReleases?:string[], blocks?:string[], blockedBy?:string[], relatedTo?:string[], duplicateOf?:string|null, removeBlocks?:string[], removeBlockedBy?:string[], removeRelatedTo?:string[])`; create/update issue. With `id`, update; without it, create. On create, `title` and `team` are required; do NOT pass `id` when creating. `assignee` (not `assigneeId`) accepts user ID/name/email/`me`; null removes it. The same `Linear` app-user rule applies to `delegate`; null removes it. `cycle`, `project`, and `parentId` null-remove. `milestone`: name/ID. Priority values as above. `labels` is a JSON array of names/IDs and replaces the full label set; omitted leaves labels unchanged. `dueDate` is ISO. On create, `estimate` null or omitted means no estimate; on update null clears and omission leaves unchanged; `0` is real only for teams allowing zero estimates. Each `links` item requires URI `url` and nonempty `title`; links append and are never removed. `setReleases` replaces all releases and cannot combine with `addReleases`/`removeReleases`; add is append-only; remove is update-only. `blocks`, `blockedBy`, and `relatedTo` append relations and never remove existing relations. The three `remove*` relation fields remove their respective relations. `duplicateOf` null removes.

`list_issue_statuses(team:string)`; list statuses available in a team (team name/ID).

`get_issue_status(id:string, name:string, team:string)`; retrieve status details by name or ID; all three inputs are schema-required.

`list_issue_labels(limit?:number=50, cursor?:string, orderBy?:createdAt|updatedAt=updatedAt, name?:string, team?:string)`; list issue labels in workspace/team; `name` filters and `team` accepts name/ID; max 250.

`create_issue_label(name:string, description?:string, color?:string, teamId?:string, parent?:string, isGroup?:boolean=false)`; create label. `color`: hex; `teamId`: team UUID, omit for workspace label; `parent`: parent label-group name; `isGroup` is not directly applicable.

## Projects

`list_projects(limit?:number=50, cursor?:string, orderBy?:createdAt|updatedAt=updatedAt, query?:string, state?:string, initiative?:string, team?:string, member?:string, label?:string, createdAt?:ISO date/duration, updatedAt?:ISO date/duration, includeMilestones?:boolean=false, includeMembers?:boolean=false, includeArchived?:boolean=false)`; list workspace projects; limit max 50. Query searches project name. State accepts type/name/ID; initiative/team accept name/ID; member accepts user ID/name/email/`me`; label accepts name/ID; date filters mean created/updated after.

`get_project(query:string, includeMilestones?:boolean=false, includeMembers?:boolean=false, includeResources?:boolean=false)`; retrieve project by name, ID, or slug; optional resources include documents, links, and attachments.

`save_project(id?:string, name?:string, icon?:string, color?:string, summary?:string, description?:string, state?:string, startDate?:string, startDateResolution?:halfYear|month|quarter|year, targetDate?:string, targetDateResolution?:halfYear|month|quarter|year, priority?:integer, addTeams?:string[], removeTeams?:string[], setTeams?:string[], labels?:string[], lead?:string|null, addInitiatives?:string[], removeInitiatives?:string[], setInitiatives?:string[])`; create/update project. Without `id`, create; with `id`, update. On create `name` and at least one team via `addTeams` or `setTeams` are required. `icon` is icon name/emoji code such as `Rocket` or `:eagle:`, not raw Unicode; color is hex; summary max 255 chars; description Markdown. Date values are ISO and pair with their resolution. Priority is an integer 0-4 with `0=None, 1=Urgent, 2=High, 3=Medium, 4=Low`. `setTeams` replaces all teams and cannot combine with add/remove; labels replaces the full set (omission leaves unchanged); lead accepts user ID/name/email/`me`, null removes. Initiative add/remove are incremental; set replaces all and cannot combine with add/remove.

`list_project_labels(limit?:number=50, cursor?:string, orderBy?:createdAt|updatedAt=updatedAt, name?:string)`; list workspace project labels; name filter; max 250.

## Releases

`list_release_pipelines(limit?:number=50, cursor?:string, orderBy?:createdAt|updatedAt=updatedAt, query?:string, team?:string, type?:continuous|scheduled, isProduction?:boolean, includeStages?:boolean=false, includeTeams?:boolean=false, createdAt?:ISO date/duration, updatedAt?:ISO date/duration, includeArchived?:boolean=false)`; list workspace pipelines; query searches pipeline name; team is name/ID; date filters mean created/updated after.

`list_releases(limit?:number=50, cursor?:string, orderBy?:createdAt|updatedAt=updatedAt, query?:string, pipeline?:string, stage?:string, stageType?:planned|started|completed|canceled, version?:string, hasReleaseNotes?:boolean, includeReleaseNotes?:boolean=false, createdAt?:ISO date/duration, updatedAt?:ISO date/duration, includeArchived?:boolean=false)`; list releases. Query searches name/version; pipeline accepts ID/slug/exact name; stage accepts ID/exact name; version is exact; `hasReleaseNotes` selects true/false presence.

`get_release(id:string, includeReleaseNotes?:boolean=false)`; retrieve release by ID/slug; optional associated notes.

`save_release(id?:string, name?:string, description?:string, version?:string, pipeline?:string, stage?:string, startDate?:string|null, targetDate?:string|null, createdAt?:ISO DateTime, startedAt?:string|null, completedAt?:string|null, commitSha?:string)`; create/update release. Omit `id` to create, provide to update. Create requires `name` and `pipeline`; pipeline accepts ID/slug/exact name. Release status is its pipeline stage; stage accepts stage ID, exact name, or lifecycle type. Dates are estimated ISO `YYYY-MM-DD` and null removes; `createdAt` is import/create ISO DateTime; started/completed are ISO timestamps and null removes; `commitSha` associates a commit.

`list_release_notes(limit?:number=50, cursor?:string, orderBy?:createdAt|updatedAt=updatedAt, query?:string, pipeline?:string, release?:string, includeContent?:boolean=false, includeReleases?:boolean=false, createdAt?:ISO date/duration, updatedAt?:ISO date/duration, includeArchived?:boolean=false)`; list notes; query searches title; pipeline accepts ID/slug/exact name; release accepts ID/slug; optional Markdown content and associated releases.

`get_release_note(id:string, includeReleases?:boolean=false)`; retrieve notes by ID/slug, including Markdown content; optionally associated releases.

`save_release_note(id?:string, pipeline?:string, title?:string, content?:string, releases?:string[], rangeFromRelease?:string, rangeToRelease?:string)`; create/update notes. Omit `id` to create; create requires `pipeline` and either `releases` or a release range. Pipeline accepts ID/slug/exact name. Range fields identify oldest and newest release IDs/slugs. Content is Markdown.

## Diffs

Diff lookup identifiers may be Linear review URLs, GitHub PR URLs, Linear full identifiers, UUIDs, or slugs.

`get_diff(urlOrId:string)`; exact diff lookup; nonempty input.

`list_diffs(limit?:number=50, cursor?:string, orderBy?:createdAt|updatedAt=updatedAt, query?:string, owner?:string, repo?:string, status?:string)`; list visible diff pull requests; query broadly searches title, branch, PR number, or bare slug; owner/repo/status filter repository owner/name/PR status.

`get_diff_threads(urlOrId:string, threadId?:string, resolved?:boolean, orderBy?:createdAt|updatedAt=updatedAt)`; exact thread lookup. Optional top-level thread/comment ID, resolved-state filter, and sort.

## Milestones

`list_milestones(project:string)`; list all milestones in project; project name/ID/slug.

`get_milestone(project:string, query:string)`; retrieve milestone by name/ID within project.

`save_milestone(project:string, id?:string, name?:string, description?:string, targetDate?:string|null)`; create/update milestone. `id` is name/ID; omit to create, when `name` is required. Target date is ISO; null removes.

## Teams and users

`list_teams(limit?:number=50, cursor?:string, orderBy?:createdAt|updatedAt=updatedAt, query?:string, includeArchived?:boolean=false, createdAt?:ISO date/duration, updatedAt?:ISO date/duration)`; list workspace teams; max 250.

`get_team(query:string)`; retrieve team by UUID, key, or name.

`list_users(limit?:number=50, cursor?:string, orderBy?:createdAt|updatedAt=updatedAt, query?:string, team?:string)`; list workspace users; query filters name/email; team accepts name/ID; max 250.

`get_user(query:string)`; retrieve user by ID, name, email, or `me`.

## Documentation

`search_documentation(query:string, page?:number=0)`; search Linear documentation; `page` is page number.

## Status updates

Status update `type` is required and is `project|initiative`.

`get_status_updates(type:project|initiative, limit?:number=50, cursor?:string, orderBy?:createdAt|updatedAt=updatedAt, id?:string, project?:string, initiative?:string, user?:string, createdAt?:ISO date/duration, updatedAt?:ISO date/duration, includeArchived?:boolean=false)`; list or retrieve project/initiative updates. With `id`, return that specific update; otherwise filters list. Project accepts name/ID/slug; initiative accepts name/ID; user accepts ID/name/email/`me`; date filters mean created/updated after.

`save_status_update(type:project|initiative, id?:string, project?:string, initiative?:string, body?:string, health?:onTrack|atRisk|offTrack, isDiffHidden?:boolean)`; omit `id` to create, provide to update. Project/initiative identify the target; body is Markdown. `isDiffHidden` is deprecated and hides the diff with the previous update on create only.

`delete_status_update(type:project|initiative, id:string)`; delete/archive a project or initiative status update.
