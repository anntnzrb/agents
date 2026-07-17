# Linear MCP Tool Catalog

> Snapshot: Linear MCP, MCPorter 0.12.3, 2026-07-16, 47 tools.

- Live discovery MUST remain authoritative.
- Agents MUST NOT load this outside broad selection or discovery failure.
- Discovery failure MUST include snapshot drift disclosure.
- Input schemas do not define response fields.
- NEVER invent unobserved response fields.

Exact tool descriptions and input schemas came from:

```text
nix run github:numtide/llm-agents.nix#mcporter -- --config <agent-config-root>/assets/mcporter.jsonc list linear --schema
```

## Contents

- [Attachments](#attachments)
  - [`get_attachment`](#get_attachment)
  - [`prepare_attachment_upload`](#prepare_attachment_upload)
  - [`create_attachment_from_upload`](#create_attachment_from_upload)
  - [`create_attachment`](#create_attachment)
  - [`delete_attachment`](#delete_attachment)
- [Agent skills](#agent-skills)
  - [`list_agent_skills`](#list_agent_skills)
  - [`get_agent_skill`](#get_agent_skill)
- [Comments](#comments)
  - [`list_comments`](#list_comments)
  - [`save_comment`](#save_comment)
  - [`delete_comment`](#delete_comment)
- [Cycles](#cycles)
  - [`list_cycles`](#list_cycles)
- [Documents](#documents)
  - [`get_document`](#get_document)
  - [`list_documents`](#list_documents)
  - [`save_document`](#save_document)
  - [`extract_images`](#extract_images)
- [Issues](#issues)
  - [`get_issue`](#get_issue)
  - [`list_issues`](#list_issues)
  - [`save_issue`](#save_issue)
  - [`list_issue_statuses`](#list_issue_statuses)
  - [`get_issue_status`](#get_issue_status)
  - [`list_issue_labels`](#list_issue_labels)
  - [`create_issue_label`](#create_issue_label)
- [Projects](#projects)
  - [`list_projects`](#list_projects)
  - [`get_project`](#get_project)
  - [`save_project`](#save_project)
  - [`list_project_labels`](#list_project_labels)
- [Releases](#releases)
  - [`list_release_pipelines`](#list_release_pipelines)
  - [`list_releases`](#list_releases)
  - [`get_release`](#get_release)
  - [`save_release`](#save_release)
  - [`list_release_notes`](#list_release_notes)
  - [`get_release_note`](#get_release_note)
  - [`save_release_note`](#save_release_note)
- [Diffs](#diffs)
  - [`get_diff`](#get_diff)
  - [`list_diffs`](#list_diffs)
  - [`get_diff_threads`](#get_diff_threads)
- [Milestones](#milestones)
  - [`list_milestones`](#list_milestones)
  - [`get_milestone`](#get_milestone)
  - [`save_milestone`](#save_milestone)
- [Teams and users](#teams-and-users)
  - [`list_teams`](#list_teams)
  - [`get_team`](#get_team)
  - [`list_users`](#list_users)
  - [`get_user`](#get_user)
- [Documentation](#documentation)
  - [`search_documentation`](#search_documentation)
- [Status updates](#status-updates)
  - [`get_status_updates`](#get_status_updates)
  - [`save_status_update`](#save_status_update)
  - [`delete_status_update`](#delete_status_update)

## Attachments

<a id="get_attachment"></a>

### `get_attachment`

```text
  /**
   * Retrieve an attachment's content by ID.
   *
   * @param id Attachment ID
   */
  function get_attachment(id: string);
      {
        "type": "object",
        "properties": {
          "id": {
            "type": "string",
            "description": "Attachment ID"
          }
        },
        "required": [
          "id"
        ],
        "$schema": "http://json-schema.org/draft-07/schema#",
        "additionalProperties": false
      }
```

<a id="prepare_attachment_upload"></a>

### `prepare_attachment_upload`

```text
  /**
   * Prepare a direct Linear file upload for an existing issue.
   * Workflow:
   * 1. Call this tool with issue, filename, contentType, and size.
   * 2. Upload raw bytes with PUT to uploadRequest.url outside MCP.
   * 3. All headers in uploadRequest.headers are part of the signed request, so send them verbatim.
   * 4. After PUT succeeds, call create_attachment_from_upload with assetUrl to link it to the issue.
   * Do not base64-encode or transform the file. Use curl --data-binary @path or fetch(url, { method:
   * 'PUT', body: blob }).
   * Omitting or modifying any signed header, including casing, will return HTTP 403.
   * The signed URL must be used within 60 seconds or it will expire.
   * Upload sequencing:
   * Prepare, PUT, and finalize one file before calling this tool for another file.
   * Do not batch multiple prepare_attachment_upload calls before starting the PUTs because earlier
   * signed URLs can expire while later files are prepared.
   * Example:
   * curl -X PUT --data-binary @file.png \
   * -H "content-type: image/png" \
   * -H "x-goog-content-length-range: N,N" \
   * -H "cache-control: public, max-age=31536000" \
   * -H 'Content-Disposition: attachment; filename="file.png"' \
   * "<uploadRequest.url>"
   *
   * @param issue Issue ID or identifier (e.g., LIN-123)
   * @param filename Filename for the upload, e.g. screenshot.png
   * @param contentType MIME type, e.g. image/png or application/pdf
   * @param size Exact file size in bytes. Must be smaller than 2 GB.
   * @param title? Suggested attachment title for the finalize step
   * @param subtitle? Suggested attachment subtitle for the finalize step
   */
  function prepare_attachment_upload(issue: string, filename: string, contentType: string, size: number, title?: string);
  // optional (1): subtitle
      {
        "type": "object",
        "properties": {
          "issue": {
            "type": "string",
            "description": "Issue ID or identifier (e.g., LIN-123)"
          },
          "filename": {
            "type": "string",
            "description": "Filename for the upload, e.g. screenshot.png"
          },
          "contentType": {
            "type": "string",
            "description": "MIME type, e.g. image/png or application/pdf"
          },
          "size": {
            "type": "integer",
            "exclusiveMinimum": 0,
            "maximum": 9007199254740991,
            "description": "Exact file size in bytes. Must be smaller than 2 GB."
          },
          "title": {
            "description": "Suggested attachment title for the finalize step",
            "type": "string"
          },
          "subtitle": {
            "description": "Suggested attachment subtitle for the finalize step",
            "type": "string"
          }
        },
        "required": [
          "issue",
          "filename",
          "contentType",
          "size"
        ],
        "$schema": "http://json-schema.org/draft-07/schema#",
        "additionalProperties": false
      }
```

<a id="create_attachment_from_upload"></a>

### `create_attachment_from_upload`

```text
  /**
   * Link an already-uploaded Linear assetUrl to an existing issue as an attachment.
   * Use this only after:
   * 1. prepare_attachment_upload returned an assetUrl and uploadRequest.
   * 2. The client successfully PUT raw file bytes to uploadRequest.url.
   * This tool does not upload file content. It only creates the Linear attachment row.
   * If the direct upload failed or the signed URL expired, rerun prepare_attachment_upload and upload
   * again.
   *
   * @param issue Issue ID or identifier (e.g., LIN-123)
   * @param assetUrl Linear upload assetUrl returned by prepare_attachment_upload
   * @param title? Attachment title. Defaults to filename or asset URL
   * @param subtitle? Optional attachment subtitle
   */
  function create_attachment_from_upload(issue: string, assetUrl: string /* Uri */, title?: string, subtitle?: string);
      {
        "type": "object",
        "properties": {
          "issue": {
            "type": "string",
            "description": "Issue ID or identifier (e.g., LIN-123)"
          },
          "assetUrl": {
            "type": "string",
            "format": "uri",
            "description": "Linear upload assetUrl returned by prepare_attachment_upload"
          },
          "title": {
            "description": "Attachment title. Defaults to filename or asset URL",
            "type": "string"
          },
          "subtitle": {
            "description": "Optional attachment subtitle",
            "type": "string"
          }
        },
        "required": [
          "issue",
          "assetUrl"
        ],
        "$schema": "http://json-schema.org/draft-07/schema#",
        "additionalProperties": false
      }
```

<a id="create_attachment"></a>

### `create_attachment`

```text
  /**
   * Deprecated fallback for tiny files only. Accepts base64 file content, verifies SHA-256 checksum, and
   * uploads it through the MCP worker.
   * Prefer `prepare_attachment_upload` plus direct PUT plus `create_attachment_from_upload`.
   * CRITICAL: Do not print base64Content and then copy it into this tool call.
   * Opaque base64 copied through model-visible text is easy to corrupt.
   * Generate base64Content mechanically from the source bytes and pass it through a programmatic
   * argument construction path whenever available. Before calling this tool, verify the values are
   * consistent:
   * Unix-like shells:
   * file="/path/to/file"
   * base64Content=$(base64 < "$file" | tr -d '\n\r')
   * sha256=$(shasum -a 256 "$file" | awk '{print $1}')
   * decodedSha256=$(printf '%s' "$base64Content" | base64 -d | shasum -a 256 | awk '{print $1}')
   * size=$(wc -c < "$file" | tr -d ' ') # optional; stat can also get file byte size
   * decodedSize=$(printf '%s' "$base64Content" | base64 -d | wc -c | tr -d ' ')
   * PowerShell:
   * $file = 'C:\path\to\file'
   * $bytes = [IO.File]::ReadAllBytes($file)
   * $base64Content = [Convert]::ToBase64String($bytes)
   * $sha256 = (Get-FileHash -Algorithm SHA256 -Path $file).Hash.ToLower()
   * $size = $bytes.Length # optional
   * $decoded = [Convert]::FromBase64String($base64Content)
   * $decodedStream = [IO.MemoryStream]::new($decoded)
   * $decodedSha256 = (Get-FileHash -Algorithm SHA256 -InputStream $decodedStream).Hash.ToLower()
   * $decodedSize = $decoded.Length
   * decodedSha256 must equal sha256. If you pass size, decodedSize must equal size.
   * Pass `sha256`. Passing `size` is optional, but recommended for clearer mismatch errors.
   *
   * @param issue Issue ID or identifier (e.g., LIN-123)
   * @param base64Content Deprecated base64-encoded file content to upload
   * @param filename Filename for the upload (e.g., 'screenshot.png')
   * @param contentType MIME type for the upload (e.g., 'image/png', 'application/pdf')
   * @param size? Optional expected decoded file size in bytes. Rejects the upload if it does not match.
   * @param sha256 Expected SHA-256 hex digest of the decoded file bytes.
   * @param title? Optional title for the attachment
   * @param subtitle? Optional subtitle for the attachment
   */
  function create_attachment(issue: string, base64Content: string, filename: string, contentType: string, sha256: string);
  // optional (3): size, title, subtitle
      {
        "type": "object",
        "properties": {
          "issue": {
            "type": "string",
            "description": "Issue ID or identifier (e.g., LIN-123)"
          },
          "base64Content": {
            "type": "string",
            "description": "Deprecated base64-encoded file content to upload"
          },
          "filename": {
            "type": "string",
            "description": "Filename for the upload (e.g., 'screenshot.png')"
          },
          "contentType": {
            "type": "string",
            "description": "MIME type for the upload (e.g., 'image/png', 'application/pdf')"
          },
          "size": {
            "description": "Optional expected decoded file size in bytes. Rejects the upload if it does not match.",
            "type": "integer",
            "exclusiveMinimum": 0,
            "maximum": 9007199254740991
          },
          "sha256": {
            "type": "string",
            "pattern": "^[a-fA-F0-9]{64}$",
            "description": "Expected SHA-256 hex digest of the decoded file bytes."
          },
          "title": {
            "description": "Optional title for the attachment",
            "type": "string"
          },
          "subtitle": {
            "description": "Optional subtitle for the attachment",
            "type": "string"
          }
        },
        "required": [
          "issue",
          "base64Content",
          "filename",
          "contentType",
          "sha256"
        ],
        "$schema": "http://json-schema.org/draft-07/schema#",
        "additionalProperties": false
      }
```

<a id="delete_attachment"></a>

### `delete_attachment`

```text
  /**
   * Delete an attachment by ID
   *
   * @param id Attachment ID
   */
  function delete_attachment(id: string);
      {
        "type": "object",
        "properties": {
          "id": {
            "type": "string",
            "description": "Attachment ID"
          }
        },
        "required": [
          "id"
        ],
        "$schema": "http://json-schema.org/draft-07/schema#",
        "additionalProperties": false
      }
```

## Agent skills

<a id="list_agent_skills"></a>

### `list_agent_skills`

```text
  /**
   * List Linear Agent skills available to the authenticated user.
   *
   * @param limit? Max results (default 50, max 250)
   * @param cursor? Next page cursor
   * @param orderBy? Sort: createdAt | updatedAt
   */
  function list_agent_skills(limit?: number, cursor?: string, orderBy?: "createdAt" | "updatedAt");
      {
        "type": "object",
        "properties": {
          "limit": {
            "default": 50,
            "description": "Max results (default 50, max 250)",
            "type": "number",
            "maximum": 250
          },
          "cursor": {
            "description": "Next page cursor",
            "type": "string"
          },
          "orderBy": {
            "default": "updatedAt",
            "description": "Sort: createdAt | updatedAt",
            "type": "string",
            "enum": [
              "createdAt",
              "updatedAt"
            ]
          }
        },
        "$schema": "http://json-schema.org/draft-07/schema#",
        "additionalProperties": false
      }
```

<a id="get_agent_skill"></a>

### `get_agent_skill`

```text
  /**
   * Retrieve a Linear Agent skill by ID, including its full markdown instructions.
   *
   * @param id Agent skill ID
   */
  function get_agent_skill(id: string);
      {
        "type": "object",
        "properties": {
          "id": {
            "type": "string",
            "description": "Agent skill ID"
          }
        },
        "required": [
          "id"
        ],
        "$schema": "http://json-schema.org/draft-07/schema#",
        "additionalProperties": false
      }
```

## Comments

<a id="list_comments"></a>

### `list_comments`

```text
  /**
   * List comments on a Linear issue, project, initiative, document, project milestone, or
   * project/initiative status update. Provide exactly one of `issueId`, `projectId`, `initiativeId`,
   * `documentId`, `milestoneId`, or `statusUpdateId`. For issues, projects, and initiatives this returns
   * both top-level discussion threads and inline description comments. Inline (anchored) comments carry
   * a non-null `quotedText` set to the snippet of description text they reference.
   *
   * @param limit? Max results (default 50, max 250)
   * @param cursor? Next page cursor
   * @param orderBy? Sort: createdAt | updatedAt
   * @param issueId? Issue ID or identifier (e.g., LIN-123) (provide exactly one parent)
   * @param projectId? Project name, ID, or slug (provide exactly one parent)
   * @param initiativeId? Initiative name or ID (provide exactly one parent)
   * @param documentId? Document ID or slug (provide exactly one parent)
   * @param milestoneId? Milestone UUID (provide exactly one parent). Resolve milestone names via
   *                     `list_milestones` first.
   * @param statusUpdateId? Status update UUID (provide exactly one parent). Resolve status updates via
   *                        `get_status_updates` first.
   * @param statusUpdateType? Type of status update named by `statusUpdateId`, as returned by
   *                          `get_status_updates`. Only valid together with `statusUpdateId`; omit to
   *                          check both project and initiative status updates.
   */
  function list_comments(limit?: number, cursor?: string, orderBy?: "createdAt" | "updatedAt", issueId?: string, projectId?: string);
  // optional (5): initiativeId, documentId, milestoneId, statusUpdateId, statusUpdateType
      {
        "type": "object",
        "properties": {
          "limit": {
            "default": 50,
            "description": "Max results (default 50, max 250)",
            "type": "number",
            "maximum": 250
          },
          "cursor": {
            "description": "Next page cursor",
            "type": "string"
          },
          "orderBy": {
            "default": "updatedAt",
            "description": "Sort: createdAt | updatedAt",
            "type": "string",
            "enum": [
              "createdAt",
              "updatedAt"
            ]
          },
          "issueId": {
            "description": "Issue ID or identifier (e.g., LIN-123) (provide exactly one parent)",
            "type": "string"
          },
          "projectId": {
            "description": "Project name, ID, or slug (provide exactly one parent)",
            "type": "string"
          },
          "initiativeId": {
            "description": "Initiative name or ID (provide exactly one parent)",
            "type": "string"
          },
          "documentId": {
            "description": "Document ID or slug (provide exactly one parent)",
            "type": "string"
          },
          "milestoneId": {
            "description": "Milestone UUID (provide exactly one parent). Resolve milestone names via `list_milestones` first.",
            "type": "string"
          },
          "statusUpdateId": {
            "description": "Status update UUID (provide exactly one parent). Resolve status updates via `get_status_updates` first.",
            "type": "string"
          },
          "statusUpdateType": {
            "description": "Type of status update named by `statusUpdateId`, as returned by `get_status_updates`. Only valid together with `statusUpdateId`; omit to check both project and initiative status updates.",
            "type": "string",
            "enum": [
              "project",
              "initiative"
            ]
          }
        },
        "$schema": "http://json-schema.org/draft-07/schema#",
        "additionalProperties": false
      }
```

<a id="save_comment"></a>

### `save_comment`

```text
  /**
   * Create or update a comment on a Linear issue, project, initiative, document, project milestone, or
   * project/initiative status update. If `id` is provided, updates the existing comment; otherwise
   * creates a new one. To start a new thread, pass `body` and exactly one of `issueId`, `projectId`,
   * `initiativeId`, `documentId`, `milestoneId`, or `statusUpdateId` — comments on
   * issues/projects/initiatives become top-level discussion threads; comments on documents/milestones
   * become description comments. A status update holds a single thread, so a comment on an update that
   * already has one is added to it as a reply. To reply to an existing thread, pass `parentId` and
   * `body`; the reply inherits the parent's thread type, so no entity reference is needed. Parent
   * reference fields are ignored when `id` or `parentId` is provided (`statusUpdateType` is rejected
   * instead).
   *
   * @param id? Comment ID. If provided, updates the existing comment
   * @param issueId? Issue ID or identifier (e.g., LIN-123) (provide exactly one parent)
   * @param projectId? Project name, ID, or slug (provide exactly one parent)
   * @param initiativeId? Initiative name or ID (provide exactly one parent)
   * @param documentId? Document ID or slug (provide exactly one parent)
   * @param milestoneId? Milestone UUID (provide exactly one parent). Resolve milestone names via
   *                     `list_milestones` first.
   * @param statusUpdateId? Status update UUID (provide exactly one parent). Resolve status updates via
   *                        `get_status_updates` first.
   * @param statusUpdateType? Type of status update named by `statusUpdateId`, as returned by
   *                          `get_status_updates`. Only valid together with `statusUpdateId`; omit to
   *                          check both project and initiative status updates.
   * @param parentId? Parent comment ID (for replies, only when creating)
   * @param body Content as Markdown. Do not escape the string — use literal newlines and special
   *             characters, not escape sequences. To mention a user, use @displayName (e.g., @johndoe)
   */
  function save_comment(id?: string, issueId?: string, projectId?: string, initiativeId?: string, body: string);
  // optional (5): documentId, milestoneId, statusUpdateId, statusUpdateType, parentId
      {
        "type": "object",
        "properties": {
          "id": {
            "description": "Comment ID. If provided, updates the existing comment",
            "type": "string"
          },
          "issueId": {
            "description": "Issue ID or identifier (e.g., LIN-123) (provide exactly one parent)",
            "type": "string"
          },
          "projectId": {
            "description": "Project name, ID, or slug (provide exactly one parent)",
            "type": "string"
          },
          "initiativeId": {
            "description": "Initiative name or ID (provide exactly one parent)",
            "type": "string"
          },
          "documentId": {
            "description": "Document ID or slug (provide exactly one parent)",
            "type": "string"
          },
          "milestoneId": {
            "description": "Milestone UUID (provide exactly one parent). Resolve milestone names via `list_milestones` first.",
            "type": "string"
          },
          "statusUpdateId": {
            "description": "Status update UUID (provide exactly one parent). Resolve status updates via `get_status_updates` first.",
            "type": "string"
          },
          "statusUpdateType": {
            "description": "Type of status update named by `statusUpdateId`, as returned by `get_status_updates`. Only valid together with `statusUpdateId`; omit to check both project and initiative status updates.",
            "type": "string",
            "enum": [
              "project",
              "initiative"
            ]
          },
          "parentId": {
            "description": "Parent comment ID (for replies, only when creating)",
            "type": "string"
          },
          "body": {
            "type": "string",
            "description": "Content as Markdown. Do not escape the string — use literal newlines and special characters, not escape sequences. To mention a user, use @displayName (e.g., @johndoe)"
          }
        },
        "required": [
          "body"
        ],
        "$schema": "http://json-schema.org/draft-07/schema#",
        "additionalProperties": false
      }
```

<a id="delete_comment"></a>

### `delete_comment`

```text
  /**
   * Delete a Linear comment. Inline description comments (those with non-null `quotedText`) anchor a
   * mark in the editor, so their root cannot be deleted — delete the replies individually or resolve the
   * thread instead.
   *
   * @param id Comment ID
   */
  function delete_comment(id: string);
      {
        "type": "object",
        "properties": {
          "id": {
            "type": "string",
            "description": "Comment ID"
          }
        },
        "required": [
          "id"
        ],
        "$schema": "http://json-schema.org/draft-07/schema#",
        "additionalProperties": false
      }
```

## Cycles

<a id="list_cycles"></a>

### `list_cycles`

```text
  /**
   * Retrieve cycles for a specific Linear team
   *
   * @param teamId Team ID
   * @param type? Filter: current, previous, next, or all
   */
  function list_cycles(teamId: string, type?: "current" | "previous" | "next");
      {
        "type": "object",
        "properties": {
          "teamId": {
            "type": "string",
            "description": "Team ID"
          },
          "type": {
            "description": "Filter: current, previous, next, or all",
            "type": "string",
            "enum": [
              "current",
              "previous",
              "next"
            ]
          }
        },
        "required": [
          "teamId"
        ],
        "$schema": "http://json-schema.org/draft-07/schema#",
        "additionalProperties": false
      }
```

## Documents

<a id="get_document"></a>

### `get_document`

```text
  /**
   * Retrieve a Linear document by ID or slug
   *
   * @param id Document ID or slug
   */
  function get_document(id: string);
      {
        "type": "object",
        "properties": {
          "id": {
            "type": "string",
            "description": "Document ID or slug"
          }
        },
        "required": [
          "id"
        ],
        "$schema": "http://json-schema.org/draft-07/schema#",
        "additionalProperties": false
      }
```

<a id="list_documents"></a>

### `list_documents`

```text
  /**
   * List documents in the user's Linear workspace
   *
   * @param limit? Max results (default 50, max 250)
   * @param cursor? Next page cursor
   * @param orderBy? Sort: createdAt | updatedAt
   * @param query? Search query
   * @param projectId? Filter by project ID
   * @param initiativeId? Filter by initiative ID
   * @param teamId? Filter by team ID
   * @param creatorId? Filter by creator ID
   * @param createdAt? Created after: ISO-8601 date/duration (e.g., -P1D)
   * @param updatedAt? Updated after: ISO-8601 date/duration (e.g., -P1D)
   * @param includeArchived? Include archived items
   */
  function list_documents(limit?: number, cursor?: string, orderBy?: "createdAt" | "updatedAt", query?: string, projectId?: string);
  // optional (6): initiativeId, teamId, creatorId, createdAt, updatedAt, ...
      {
        "type": "object",
        "properties": {
          "limit": {
            "default": 50,
            "description": "Max results (default 50, max 250)",
            "type": "number",
            "maximum": 250
          },
          "cursor": {
            "description": "Next page cursor",
            "type": "string"
          },
          "orderBy": {
            "default": "updatedAt",
            "description": "Sort: createdAt | updatedAt",
            "type": "string",
            "enum": [
              "createdAt",
              "updatedAt"
            ]
          },
          "query": {
            "description": "Search query",
            "type": "string"
          },
          "projectId": {
            "description": "Filter by project ID",
            "type": "string"
          },
          "initiativeId": {
            "description": "Filter by initiative ID",
            "type": "string"
          },
          "teamId": {
            "description": "Filter by team ID",
            "type": "string"
          },
          "creatorId": {
            "description": "Filter by creator ID",
            "type": "string"
          },
          "createdAt": {
            "description": "Created after: ISO-8601 date/duration (e.g., -P1D)",
            "type": "string"
          },
          "updatedAt": {
            "description": "Updated after: ISO-8601 date/duration (e.g., -P1D)",
            "type": "string"
          },
          "includeArchived": {
            "default": false,
            "description": "Include archived items",
            "type": "boolean"
          }
        },
        "$schema": "http://json-schema.org/draft-07/schema#",
        "additionalProperties": false
      }
```

<a id="save_document"></a>

### `save_document`

```text
  /**
   * Create or update a Linear document. If `id` is provided, updates the existing document; otherwise
   * creates a new one. When creating, `title` is required and exactly one parent (`project`, `issue`,
   * `initiative`, `cycle`, or `team`) must be specified. On update, passing a parent reparents the
   * document.
   *
   * @param id? Document ID or slug to update. Omit to create a new document.
   * @param title? Document title (required when creating)
   * @param content? Content as Markdown. Do not escape the string — use literal newlines and special
   *                 characters, not escape sequences. To mention a user, use @displayName (e.g.,
   *                 @johndoe)
   * @param project? Project name, ID, or slug
   * @param issue? Issue ID or identifier (e.g., LIN-123)
   * @param initiative? Initiative name or ID
   * @param cycle? Cycle name, number, or ID. When passing a name or number, also pass `team` to
   *               disambiguate.
   * @param team? Team name or ID. Attaches the document to the team, unless `cycle` is also passed, in
   *              which case it disambiguates the cycle.
   * @param icon? Icon name or emoji code (e.g. "Rocket" or ":eagle:"), not a raw Unicode emoji
   * @param color? Hex color
   */
  function save_document(id?: string, title?: string, content?: string, project?: string, issue?: string);
  // optional (5): initiative, cycle, team, icon, color
      {
        "type": "object",
        "properties": {
          "id": {
            "description": "Document ID or slug to update. Omit to create a new document.",
            "type": "string"
          },
          "title": {
            "description": "Document title (required when creating)",
            "type": "string"
          },
          "content": {
            "description": "Content as Markdown. Do not escape the string — use literal newlines and special characters, not escape sequences. To mention a user, use @displayName (e.g., @johndoe)",
            "type": "string"
          },
          "project": {
            "description": "Project name, ID, or slug",
            "type": "string"
          },
          "issue": {
            "description": "Issue ID or identifier (e.g., LIN-123)",
            "type": "string"
          },
          "initiative": {
            "description": "Initiative name or ID",
            "type": "string"
          },
          "cycle": {
            "description": "Cycle name, number, or ID. When passing a name or number, also pass `team` to disambiguate.",
            "type": "string"
          },
          "team": {
            "description": "Team name or ID. Attaches the document to the team, unless `cycle` is also passed, in which case it disambiguates the cycle.",
            "type": "string"
          },
          "icon": {
            "description": "Icon name or emoji code (e.g. \"Rocket\" or \":eagle:\"), not a raw Unicode emoji",
            "type": "string"
          },
          "color": {
            "description": "Hex color",
            "type": "string"
          }
        },
        "$schema": "http://json-schema.org/draft-07/schema#",
        "additionalProperties": false
      }
```

<a id="extract_images"></a>

### `extract_images`

```text
  /**
   * Extract and fetch images from markdown content. Use this to view screenshots, diagrams, or other
   * images embedded in Linear issues, comments, or documents. Pass the markdown content (e.g., issue
   * description) and receive the images as viewable data.
   *
   * @param markdown Markdown content containing image references (e.g., issue description, comment body)
   */
  function extract_images(markdown: string);
      {
        "type": "object",
        "properties": {
          "markdown": {
            "type": "string",
            "description": "Markdown content containing image references (e.g., issue description, comment body)"
          }
        },
        "required": [
          "markdown"
        ],
        "$schema": "http://json-schema.org/draft-07/schema#",
        "additionalProperties": false
      }
```

## Issues

<a id="get_issue"></a>

### `get_issue`

```text
  /**
   * Retrieve detailed information about an issue by ID, including attachments and git branch name
   *
   * @param id Issue ID or identifier (e.g., LIN-123)
   * @param includeRelations? Include blocking/related/duplicate relations
   * @param includeCustomerNeeds? Include associated customer needs
   * @param includeReleases? Include associated releases
   */
  function get_issue(id: string, includeRelations?: boolean, includeCustomerNeeds?: boolean, includeReleases?: boolean);
      {
        "type": "object",
        "properties": {
          "id": {
            "type": "string",
            "description": "Issue ID or identifier (e.g., LIN-123)"
          },
          "includeRelations": {
            "default": false,
            "description": "Include blocking/related/duplicate relations",
            "type": "boolean"
          },
          "includeCustomerNeeds": {
            "default": false,
            "description": "Include associated customer needs",
            "type": "boolean"
          },
          "includeReleases": {
            "default": false,
            "description": "Include associated releases",
            "type": "boolean"
          }
        },
        "required": [
          "id"
        ],
        "$schema": "http://json-schema.org/draft-07/schema#",
        "additionalProperties": false
      }
```

<a id="list_issues"></a>

### `list_issues`

```text
  /**
   * List issues in the user's Linear workspace. For my issues, use "me" as the assignee. Use "null" for
   * no assignee.
   *
   * @param limit? Max results (default 50, max 250)
   * @param cursor? Next page cursor
   * @param orderBy? Sort: createdAt | updatedAt
   * @param query? Search issue title or description
   * @param team? Team name or ID
   * @param state? State type, name, or ID
   * @param cycle? Cycle name, number, or ID
   * @param label? Label name or ID
   * @param assignee? User ID, name, email, or "me"
   * @param delegate? Agent name or ID. When the user asks to delegate to "Linear" or "the Linear agent",
   *                  this refers to the "Linear" app user specifically
   * @param project? Project name, ID, or slug
   * @param release? Release ID or slug
   * @param priority? 0=None, 1=Urgent, 2=High, 3=Medium, 4=Low
   * @param parentId? Parent issue ID or identifier (e.g., LIN-123)
   * @param createdAt? Created after: ISO-8601 date/duration (e.g., -P1D)
   * @param updatedAt? Updated after: ISO-8601 date/duration (e.g., -P1D)
   * @param includeArchived? Include archived items
   */
  function list_issues(limit?: number, cursor?: string, orderBy?: "createdAt" | "updatedAt", query?: string, team?: string);
  // optional (12): state, cycle, label, assignee, delegate, ...
      {
        "type": "object",
        "properties": {
          "limit": {
            "default": 50,
            "description": "Max results (default 50, max 250)",
            "type": "number",
            "maximum": 250
          },
          "cursor": {
            "description": "Next page cursor",
            "type": "string"
          },
          "orderBy": {
            "default": "updatedAt",
            "description": "Sort: createdAt | updatedAt",
            "type": "string",
            "enum": [
              "createdAt",
              "updatedAt"
            ]
          },
          "query": {
            "description": "Search issue title or description",
            "type": "string"
          },
          "team": {
            "description": "Team name or ID",
            "type": "string"
          },
          "state": {
            "description": "State type, name, or ID",
            "type": "string"
          },
          "cycle": {
            "description": "Cycle name, number, or ID",
            "type": "string"
          },
          "label": {
            "description": "Label name or ID",
            "type": "string"
          },
          "assignee": {
            "description": "User ID, name, email, or \"me\"",
            "anyOf": [
              {
                "type": "string"
              },
              {
                "type": "null"
              }
            ]
          },
          "delegate": {
            "description": "Agent name or ID. When the user asks to delegate to \"Linear\" or \"the Linear agent\", this refers to the \"Linear\" app user specifically",
            "type": "string"
          },
          "project": {
            "description": "Project name, ID, or slug",
            "type": "string"
          },
          "release": {
            "description": "Release ID or slug",
            "type": "string"
          },
          "priority": {
            "description": "0=None, 1=Urgent, 2=High, 3=Medium, 4=Low",
            "type": "number"
          },
          "parentId": {
            "description": "Parent issue ID or identifier (e.g., LIN-123)",
            "type": "string"
          },
          "createdAt": {
            "description": "Created after: ISO-8601 date/duration (e.g., -P1D)",
            "type": "string"
          },
          "updatedAt": {
            "description": "Updated after: ISO-8601 date/duration (e.g., -P1D)",
            "type": "string"
          },
          "includeArchived": {
            "default": true,
            "description": "Include archived items",
            "type": "boolean"
          }
        },
        "$schema": "http://json-schema.org/draft-07/schema#",
        "additionalProperties": false
      }
```

<a id="save_issue"></a>

### `save_issue`

```text
  /**
   * Create or update a Linear issue. If `id` is provided, updates the existing issue; otherwise creates
   * a new one. When creating, `title` and `team` are required. Note: use `assignee` (not `assigneeId`)
   * to set the assignee — it accepts a user ID, name, email, or "me".
   *
   * @param id? Only for updating an existing issue. Pass the issue ID or identifier (e.g., LIN-123). Do
   *            NOT pass this parameter when creating a new issue.
   * @param title? Issue title (required when creating)
   * @param description? Content as Markdown. Do not escape the string — use literal newlines and special
   *                     characters, not escape sequences. To mention a user, use @displayName (e.g.,
   *                     @johndoe)
   * @param team? Team name or ID (required when creating)
   * @param cycle? Cycle name, number, or ID. Null to remove
   * @param milestone? Milestone name or ID
   * @param priority? 0=None, 1=Urgent, 2=High, 3=Medium, 4=Low
   * @param project? Project name, ID, or slug. Null to remove
   * @param state? State type, name, or ID
   * @param assignee? User ID, name, email, or "me". Null to remove
   * @param delegate? Agent name or ID. When the user asks to delegate to "Linear" or "the Linear agent",
   *                  this refers to the "Linear" app user specifically. Null to remove
   * @param labels? Label names or IDs as a JSON array of strings (e.g. ["Bug", "Urgent"]). Replaces the
   *                full label set; existing labels not included are removed. Omit to leave labels
   *                unchanged
   * @param dueDate? Due date (ISO format)
   * @param parentId? Parent issue ID or identifier (e.g., LIN-123). Null to remove
   * @param estimate? Issue estimate value. On create, pass null or omit for no estimate. On update, pass
   *                  null to clear the estimate; omitting leaves it unchanged. 0 is a real estimate only
   *                  on teams that allow zero estimates.
   * @param links? Link attachments to add [{url, title}]. Append-only; existing links are never removed
   * @param setReleases? Replace all releases on the issue with these. Cannot be combined with
   *                     addReleases/removeReleases
   * @param addReleases? Release IDs or slugs to add. Append-only; existing releases are never removed
   * @param removeReleases? Release IDs or slugs to remove. Only valid when updating an existing issue
   * @param blocks? Issue IDs/identifiers this blocks. Append-only; existing relations are never removed
   * @param blockedBy? Issue IDs/identifiers blocking this. Append-only; existing relations are never
   *                   removed
   * @param relatedTo? Related issue IDs/identifiers. Append-only; existing relations are never removed
   * @param duplicateOf? Duplicate of issue ID/identifier. Null to remove
   * @param removeBlocks? Issue IDs/identifiers to stop blocking
   * @param removeBlockedBy? Issue IDs/identifiers to remove as blockers of this issue
   * @param removeRelatedTo? Related issue IDs/identifiers to remove
   */
  function save_issue(id?: string, title?: string, description?: string, team?: string, cycle?: unknown);
  // optional (21): milestone, priority, project, state, assignee, ...
      {
        "type": "object",
        "properties": {
          "id": {
            "description": "Only for updating an existing issue. Pass the issue ID or identifier (e.g., LIN-123). Do NOT pass this parameter when creating a new issue.",
            "type": "string"
          },
          "title": {
            "description": "Issue title (required when creating)",
            "type": "string"
          },
          "description": {
            "description": "Content as Markdown. Do not escape the string — use literal newlines and special characters, not escape sequences. To mention a user, use @displayName (e.g., @johndoe)",
            "type": "string"
          },
          "team": {
            "description": "Team name or ID (required when creating)",
            "type": "string"
          },
          "cycle": {
            "description": "Cycle name, number, or ID. Null to remove",
            "anyOf": [
              {
                "type": "string"
              },
              {
                "type": "null"
              }
            ]
          },
          "milestone": {
            "description": "Milestone name or ID",
            "type": "string"
          },
          "priority": {
            "description": "0=None, 1=Urgent, 2=High, 3=Medium, 4=Low",
            "type": "number"
          },
          "project": {
            "description": "Project name, ID, or slug. Null to remove",
            "anyOf": [
              {
                "type": "string"
              },
              {
                "type": "null"
              }
            ]
          },
          "state": {
            "description": "State type, name, or ID",
            "type": "string"
          },
          "assignee": {
            "description": "User ID, name, email, or \"me\". Null to remove",
            "anyOf": [
              {
                "type": "string"
              },
              {
                "type": "null"
              }
            ]
          },
          "delegate": {
            "description": "Agent name or ID. When the user asks to delegate to \"Linear\" or \"the Linear agent\", this refers to the \"Linear\" app user specifically. Null to remove",
            "anyOf": [
              {
                "type": "string"
              },
              {
                "type": "null"
              }
            ]
          },
          "labels": {
            "description": "Label names or IDs as a JSON array of strings (e.g. [\"Bug\", \"Urgent\"]). Replaces the full label set; existing labels not included are removed. Omit to leave labels unchanged",
            "type": "array",
            "items": {
              "type": "string"
            }
          },
          "dueDate": {
            "description": "Due date (ISO format)",
            "type": "string"
          },
          "parentId": {
            "description": "Parent issue ID or identifier (e.g., LIN-123). Null to remove",
            "anyOf": [
              {
                "type": "string"
              },
              {
                "type": "null"
              }
            ]
          },
          "estimate": {
            "description": "Issue estimate value. On create, pass null or omit for no estimate. On update, pass null to clear the estimate; omitting leaves it unchanged. 0 is a real estimate only on teams that allow zero estimates.",
            "anyOf": [
              {
                "type": "number"
              },
              {
                "type": "null"
              }
            ]
          },
          "links": {
            "description": "Link attachments to add [{url, title}]. Append-only; existing links are never removed",
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "url": {
                  "type": "string",
                  "format": "uri"
                },
                "title": {
                  "type": "string",
                  "minLength": 1
                }
              },
              "required": [
                "url",
                "title"
              ]
            }
          },
          "setReleases": {
            "description": "Replace all releases on the issue with these. Cannot be combined with addReleases/removeReleases",
            "type": "array",
            "items": {
              "type": "string"
            }
          },
          "addReleases": {
            "description": "Release IDs or slugs to add. Append-only; existing releases are never removed",
            "type": "array",
            "items": {
              "type": "string"
            }
          },
          "removeReleases": {
            "description": "Release IDs or slugs to remove. Only valid when updating an existing issue",
            "type": "array",
            "items": {
              "type": "string"
            }
          },
          "blocks": {
            "description": "Issue IDs/identifiers this blocks. Append-only; existing relations are never removed",
            "type": "array",
            "items": {
              "type": "string"
            }
          },
          "blockedBy": {
            "description": "Issue IDs/identifiers blocking this. Append-only; existing relations are never removed",
            "type": "array",
            "items": {
              "type": "string"
            }
          },
          "relatedTo": {
            "description": "Related issue IDs/identifiers. Append-only; existing relations are never removed",
            "type": "array",
            "items": {
              "type": "string"
            }
          },
          "duplicateOf": {
            "description": "Duplicate of issue ID/identifier. Null to remove",
            "anyOf": [
              {
                "type": "string"
              },
              {
                "type": "null"
              }
            ]
          },
          "removeBlocks": {
            "description": "Issue IDs/identifiers to stop blocking",
            "type": "array",
            "items": {
              "type": "string"
            }
          },
          "removeBlockedBy": {
            "description": "Issue IDs/identifiers to remove as blockers of this issue",
            "type": "array",
            "items": {
              "type": "string"
            }
          },
          "removeRelatedTo": {
            "description": "Related issue IDs/identifiers to remove",
            "type": "array",
            "items": {
              "type": "string"
            }
          }
        },
        "$schema": "http://json-schema.org/draft-07/schema#",
        "additionalProperties": false
      }
```

<a id="list_issue_statuses"></a>

### `list_issue_statuses`

```text
  /**
   * List available issue statuses in a Linear team
   *
   * @param team Team name or ID
   */
  function list_issue_statuses(team: string);
      {
        "type": "object",
        "properties": {
          "team": {
            "type": "string",
            "description": "Team name or ID"
          }
        },
        "required": [
          "team"
        ],
        "$schema": "http://json-schema.org/draft-07/schema#",
        "additionalProperties": false
      }
```

<a id="get_issue_status"></a>

### `get_issue_status`

```text
  /**
   * Retrieve detailed information about an issue status in Linear by name or ID
   *
   * @param id Status ID
   * @param name Status name
   * @param team Team name or ID
   */
  function get_issue_status(id: string, name: string, team: string);
      {
        "type": "object",
        "properties": {
          "id": {
            "type": "string",
            "description": "Status ID"
          },
          "name": {
            "type": "string",
            "description": "Status name"
          },
          "team": {
            "type": "string",
            "description": "Team name or ID"
          }
        },
        "required": [
          "id",
          "name",
          "team"
        ],
        "$schema": "http://json-schema.org/draft-07/schema#",
        "additionalProperties": false
      }
```

<a id="list_issue_labels"></a>

### `list_issue_labels`

```text
  /**
   * List available issue labels in a Linear workspace or team
   *
   * @param limit? Max results (default 50, max 250)
   * @param cursor? Next page cursor
   * @param orderBy? Sort: createdAt | updatedAt
   * @param name? Filter by name
   * @param team? Team name or ID
   */
  function list_issue_labels(limit?: number, cursor?: string, orderBy?: "createdAt" | "updatedAt", name?: string, team?: string);
      {
        "type": "object",
        "properties": {
          "limit": {
            "default": 50,
            "description": "Max results (default 50, max 250)",
            "type": "number",
            "maximum": 250
          },
          "cursor": {
            "description": "Next page cursor",
            "type": "string"
          },
          "orderBy": {
            "default": "updatedAt",
            "description": "Sort: createdAt | updatedAt",
            "type": "string",
            "enum": [
              "createdAt",
              "updatedAt"
            ]
          },
          "name": {
            "description": "Filter by name",
            "type": "string"
          },
          "team": {
            "description": "Team name or ID",
            "type": "string"
          }
        },
        "$schema": "http://json-schema.org/draft-07/schema#",
        "additionalProperties": false
      }
```

<a id="create_issue_label"></a>

### `create_issue_label`

```text
  /**
   * Create a new Linear issue label
   *
   * @param name Label name
   * @param description? Label description
   * @param color? Hex color code
   * @param teamId? Team UUID (omit for workspace label)
   * @param parent? Parent label group name
   * @param isGroup? Is label group (not directly applicable)
   */
  function create_issue_label(name: string, description?: string, color?: string, teamId?: string, parent?: string);
  // optional (1): isGroup
      {
        "type": "object",
        "properties": {
          "name": {
            "type": "string",
            "description": "Label name"
          },
          "description": {
            "description": "Label description",
            "type": "string"
          },
          "color": {
            "description": "Hex color code",
            "type": "string"
          },
          "teamId": {
            "description": "Team UUID (omit for workspace label)",
            "type": "string"
          },
          "parent": {
            "description": "Parent label group name",
            "type": "string"
          },
          "isGroup": {
            "default": false,
            "description": "Is label group (not directly applicable)",
            "type": "boolean"
          }
        },
        "required": [
          "name"
        ],
        "$schema": "http://json-schema.org/draft-07/schema#",
        "additionalProperties": false
      }
```

## Projects

<a id="list_projects"></a>

### `list_projects`

```text
  /**
   * List projects in the user's Linear workspace
   *
   * @param limit? Max results (default 50, max 50)
   * @param cursor? Next page cursor
   * @param orderBy? Sort: createdAt | updatedAt
   * @param query? Search project name
   * @param state? State type, name, or ID
   * @param initiative? Initiative name or ID
   * @param team? Team name or ID
   * @param member? User ID, name, email, or "me"
   * @param label? Label name or ID
   * @param createdAt? Created after: ISO-8601 date/duration (e.g., -P1D)
   * @param updatedAt? Updated after: ISO-8601 date/duration (e.g., -P1D)
   * @param includeMilestones? Include milestones
   * @param includeMembers? Include project members
   * @param includeArchived? Include archived items
   */
  function list_projects(limit?: number, cursor?: string, orderBy?: "createdAt" | "updatedAt", query?: string, state?: string);
  // optional (9): initiative, team, member, label, createdAt, ...
      {
        "type": "object",
        "properties": {
          "limit": {
            "default": 50,
            "description": "Max results (default 50, max 50)",
            "type": "number",
            "maximum": 50
          },
          "cursor": {
            "description": "Next page cursor",
            "type": "string"
          },
          "orderBy": {
            "default": "updatedAt",
            "description": "Sort: createdAt | updatedAt",
            "type": "string",
            "enum": [
              "createdAt",
              "updatedAt"
            ]
          },
          "query": {
            "description": "Search project name",
            "type": "string"
          },
          "state": {
            "description": "State type, name, or ID",
            "type": "string"
          },
          "initiative": {
            "description": "Initiative name or ID",
            "type": "string"
          },
          "team": {
            "description": "Team name or ID",
            "type": "string"
          },
          "member": {
            "description": "User ID, name, email, or \"me\"",
            "type": "string"
          },
          "label": {
            "description": "Label name or ID",
            "type": "string"
          },
          "createdAt": {
            "description": "Created after: ISO-8601 date/duration (e.g., -P1D)",
            "type": "string"
          },
          "updatedAt": {
            "description": "Updated after: ISO-8601 date/duration (e.g., -P1D)",
            "type": "string"
          },
          "includeMilestones": {
            "default": false,
            "description": "Include milestones",
            "type": "boolean"
          },
          "includeMembers": {
            "default": false,
            "description": "Include project members",
            "type": "boolean"
          },
          "includeArchived": {
            "default": false,
            "description": "Include archived items",
            "type": "boolean"
          }
        },
        "$schema": "http://json-schema.org/draft-07/schema#",
        "additionalProperties": false
      }
```

<a id="get_project"></a>

### `get_project`

```text
  /**
   * Retrieve details of a specific project in Linear
   *
   * @param query Project name, ID, or slug
   * @param includeMilestones? Include milestones
   * @param includeMembers? Include project members
   * @param includeResources? Include resources (documents, links, attachments)
   */
  function get_project(query: string, includeMilestones?: boolean, includeMembers?: boolean, includeResources?: boolean);
      {
        "type": "object",
        "properties": {
          "query": {
            "type": "string",
            "description": "Project name, ID, or slug"
          },
          "includeMilestones": {
            "default": false,
            "description": "Include milestones",
            "type": "boolean"
          },
          "includeMembers": {
            "default": false,
            "description": "Include project members",
            "type": "boolean"
          },
          "includeResources": {
            "default": false,
            "description": "Include resources (documents, links, attachments)",
            "type": "boolean"
          }
        },
        "required": [
          "query"
        ],
        "$schema": "http://json-schema.org/draft-07/schema#",
        "additionalProperties": false
      }
```

<a id="save_project"></a>

### `save_project`

```text
  /**
   * Create or update a Linear project. If `id` is provided, updates the existing project; otherwise
   * creates a new one. When creating, `name` and at least one team (via `addTeams` or `setTeams`) are
   * required.
   *
   * @param id? Project ID. If provided, updates the existing project
   * @param name? Project name (required when creating)
   * @param icon? Icon name or emoji code (e.g. "Rocket" or ":eagle:"), not a raw Unicode emoji
   * @param color? Hex color
   * @param summary? Short summary (max 255 chars)
   * @param description? Content as Markdown. Do not escape the string — use literal newlines and special
   *                     characters, not escape sequences. To mention a user, use @displayName (e.g.,
   *                     @johndoe)
   * @param state? Project state
   * @param startDate? Start date (ISO format). Pair with startDateResolution to indicate precision (e.g.
   *                   month, quarter)
   * @param startDateResolution? Start date resolution
   * @param targetDate? Target date (ISO format). Pair with targetDateResolution to indicate precision
   *                    (e.g. month, quarter)
   * @param targetDateResolution? Target date resolution
   * @param priority? 0=None, 1=Urgent, 2=High, 3=Medium, 4=Low
   * @param addTeams? Team name or ID to add
   * @param removeTeams? Team name or ID to remove
   * @param setTeams? Replace all teams with these. Cannot combine with addTeams/removeTeams
   * @param labels? Label names or IDs as a JSON array of strings (e.g. ["Bug", "Urgent"]). Replaces the
   *                full label set; existing labels not included are removed. Omit to leave labels
   *                unchanged
   * @param lead? User ID, name, email, or "me". Null to remove
   * @param addInitiatives? Initiative names/IDs to add
   * @param removeInitiatives? Initiative names/IDs to remove
   * @param setInitiatives? Replace all initiatives with these. Cannot combine with
   *                        addInitiatives/removeInitiatives
   */
  function save_project(id?: string, name?: string, icon?: string, color?: string, summary?: string);
  // optional (15): description, state, startDate, startDateResolution, targetDate, ...
      {
        "type": "object",
        "properties": {
          "id": {
            "description": "Project ID. If provided, updates the existing project",
            "type": "string"
          },
          "name": {
            "description": "Project name (required when creating)",
            "type": "string"
          },
          "icon": {
            "description": "Icon name or emoji code (e.g. \"Rocket\" or \":eagle:\"), not a raw Unicode emoji",
            "type": "string"
          },
          "color": {
            "description": "Hex color",
            "type": "string"
          },
          "summary": {
            "description": "Short summary (max 255 chars)",
            "type": "string"
          },
          "description": {
            "description": "Content as Markdown. Do not escape the string — use literal newlines and special characters, not escape sequences. To mention a user, use @displayName (e.g., @johndoe)",
            "type": "string"
          },
          "state": {
            "description": "Project state",
            "type": "string"
          },
          "startDate": {
            "description": "Start date (ISO format). Pair with startDateResolution to indicate precision (e.g. month, quarter)",
            "type": "string"
          },
          "startDateResolution": {
            "description": "Start date resolution",
            "type": "string",
            "enum": [
              "halfYear",
              "month",
              "quarter",
              "year"
            ]
          },
          "targetDate": {
            "description": "Target date (ISO format). Pair with targetDateResolution to indicate precision (e.g. month, quarter)",
            "type": "string"
          },
          "targetDateResolution": {
            "description": "Target date resolution",
            "type": "string",
            "enum": [
              "halfYear",
              "month",
              "quarter",
              "year"
            ]
          },
          "priority": {
            "description": "0=None, 1=Urgent, 2=High, 3=Medium, 4=Low",
            "type": "integer",
            "minimum": 0,
            "maximum": 4
          },
          "addTeams": {
            "description": "Team name or ID to add",
            "type": "array",
            "items": {
              "type": "string"
            }
          },
          "removeTeams": {
            "description": "Team name or ID to remove",
            "type": "array",
            "items": {
              "type": "string"
            }
          },
          "setTeams": {
            "description": "Replace all teams with these. Cannot combine with addTeams/removeTeams",
            "type": "array",
            "items": {
              "type": "string"
            }
          },
          "labels": {
            "description": "Label names or IDs as a JSON array of strings (e.g. [\"Bug\", \"Urgent\"]). Replaces the full label set; existing labels not included are removed. Omit to leave labels unchanged",
            "type": "array",
            "items": {
              "type": "string"
            }
          },
          "lead": {
            "description": "User ID, name, email, or \"me\". Null to remove",
            "anyOf": [
              {
                "type": "string"
              },
              {
                "type": "null"
              }
            ]
          },
          "addInitiatives": {
            "description": "Initiative names/IDs to add",
            "type": "array",
            "items": {
              "type": "string"
            }
          },
          "removeInitiatives": {
            "description": "Initiative names/IDs to remove",
            "type": "array",
            "items": {
              "type": "string"
            }
          },
          "setInitiatives": {
            "description": "Replace all initiatives with these. Cannot combine with addInitiatives/removeInitiatives",
            "type": "array",
            "items": {
              "type": "string"
            }
          }
        },
        "$schema": "http://json-schema.org/draft-07/schema#",
        "additionalProperties": false
      }
```

<a id="list_project_labels"></a>

### `list_project_labels`

```text
  /**
   * List available project labels in the Linear workspace
   *
   * @param limit? Max results (default 50, max 250)
   * @param cursor? Next page cursor
   * @param orderBy? Sort: createdAt | updatedAt
   * @param name? Filter by name
   */
  function list_project_labels(limit?: number, cursor?: string, orderBy?: "createdAt" | "updatedAt", name?: string);
      {
        "type": "object",
        "properties": {
          "limit": {
            "default": 50,
            "description": "Max results (default 50, max 250)",
            "type": "number",
            "maximum": 250
          },
          "cursor": {
            "description": "Next page cursor",
            "type": "string"
          },
          "orderBy": {
            "default": "updatedAt",
            "description": "Sort: createdAt | updatedAt",
            "type": "string",
            "enum": [
              "createdAt",
              "updatedAt"
            ]
          },
          "name": {
            "description": "Filter by name",
            "type": "string"
          }
        },
        "$schema": "http://json-schema.org/draft-07/schema#",
        "additionalProperties": false
      }
```

## Releases

<a id="list_release_pipelines"></a>

### `list_release_pipelines`

```text
  /**
   * List release pipelines in the workspace.
   *
   * @param limit? Max results (default 50, max 250)
   * @param cursor? Next page cursor
   * @param orderBy? Sort: createdAt | updatedAt
   * @param query? Search pipeline name
   * @param team? Team name or ID
   * @param type? Pipeline type: continuous | scheduled
   * @param isProduction? Filter by production pipeline flag
   * @param includeStages? Include each pipeline's stages
   * @param includeTeams? Include each pipeline's teams
   * @param createdAt? Created after: ISO-8601 date/duration (e.g., -P1D)
   * @param updatedAt? Updated after: ISO-8601 date/duration (e.g., -P1D)
   * @param includeArchived? Include archived items
   */
  function list_release_pipelines(limit?: number, cursor?: string, orderBy?: "createdAt" | "updatedAt", query?: string, team?: string);
  // optional (7): type, isProduction, includeStages, includeTeams, createdAt, ...
      {
        "type": "object",
        "properties": {
          "limit": {
            "default": 50,
            "description": "Max results (default 50, max 250)",
            "type": "number",
            "maximum": 250
          },
          "cursor": {
            "description": "Next page cursor",
            "type": "string"
          },
          "orderBy": {
            "default": "updatedAt",
            "description": "Sort: createdAt | updatedAt",
            "type": "string",
            "enum": [
              "createdAt",
              "updatedAt"
            ]
          },
          "query": {
            "description": "Search pipeline name",
            "type": "string"
          },
          "team": {
            "description": "Team name or ID",
            "type": "string"
          },
          "type": {
            "description": "Pipeline type: continuous | scheduled",
            "type": "string",
            "enum": [
              "continuous",
              "scheduled"
            ]
          },
          "isProduction": {
            "description": "Filter by production pipeline flag",
            "type": "boolean"
          },
          "includeStages": {
            "default": false,
            "description": "Include each pipeline's stages",
            "type": "boolean"
          },
          "includeTeams": {
            "default": false,
            "description": "Include each pipeline's teams",
            "type": "boolean"
          },
          "createdAt": {
            "description": "Created after: ISO-8601 date/duration (e.g., -P1D)",
            "type": "string"
          },
          "updatedAt": {
            "description": "Updated after: ISO-8601 date/duration (e.g., -P1D)",
            "type": "string"
          },
          "includeArchived": {
            "default": false,
            "description": "Include archived items",
            "type": "boolean"
          }
        },
        "$schema": "http://json-schema.org/draft-07/schema#",
        "additionalProperties": false
      }
```

<a id="list_releases"></a>

### `list_releases`

```text
  /**
   * List releases in the workspace, with optional filtering by pipeline, stage, version, and text.
   *
   * @param limit? Max results (default 50, max 250)
   * @param cursor? Next page cursor
   * @param orderBy? Sort: createdAt | updatedAt
   * @param query? Search release name or version
   * @param pipeline? Release pipeline ID, slug, or exact name
   * @param stage? Release stage ID or exact name
   * @param stageType? Filter by stage lifecycle type
   * @param version? Exact version match
   * @param hasReleaseNotes? Filter to releases that do (true) or do not (false) have release notes
   * @param includeReleaseNotes? Include associated release notes
   * @param createdAt? Created after: ISO-8601 date/duration (e.g., -P1D)
   * @param updatedAt? Updated after: ISO-8601 date/duration (e.g., -P1D)
   * @param includeArchived? Include archived items
   */
  function list_releases(limit?: number, cursor?: string, orderBy?: "createdAt" | "updatedAt", query?: string, pipeline?: string);
  // optional (8): stage, stageType, version, hasReleaseNotes, includeReleaseNotes, ...
      {
        "type": "object",
        "properties": {
          "limit": {
            "default": 50,
            "description": "Max results (default 50, max 250)",
            "type": "number",
            "maximum": 250
          },
          "cursor": {
            "description": "Next page cursor",
            "type": "string"
          },
          "orderBy": {
            "default": "updatedAt",
            "description": "Sort: createdAt | updatedAt",
            "type": "string",
            "enum": [
              "createdAt",
              "updatedAt"
            ]
          },
          "query": {
            "description": "Search release name or version",
            "type": "string"
          },
          "pipeline": {
            "description": "Release pipeline ID, slug, or exact name",
            "type": "string"
          },
          "stage": {
            "description": "Release stage ID or exact name",
            "type": "string"
          },
          "stageType": {
            "description": "Filter by stage lifecycle type",
            "type": "string",
            "enum": [
              "planned",
              "started",
              "completed",
              "canceled"
            ]
          },
          "version": {
            "description": "Exact version match",
            "type": "string"
          },
          "hasReleaseNotes": {
            "description": "Filter to releases that do (true) or do not (false) have release notes",
            "type": "boolean"
          },
          "includeReleaseNotes": {
            "default": false,
            "description": "Include associated release notes",
            "type": "boolean"
          },
          "createdAt": {
            "description": "Created after: ISO-8601 date/duration (e.g., -P1D)",
            "type": "string"
          },
          "updatedAt": {
            "description": "Updated after: ISO-8601 date/duration (e.g., -P1D)",
            "type": "string"
          },
          "includeArchived": {
            "default": false,
            "description": "Include archived items",
            "type": "boolean"
          }
        },
        "$schema": "http://json-schema.org/draft-07/schema#",
        "additionalProperties": false
      }
```

<a id="get_release"></a>

### `get_release`

```text
  /**
   * Retrieve details of a release by ID or slug.
   *
   * @param id Release ID or slug
   * @param includeReleaseNotes? Include associated release notes
   */
  function get_release(id: string, includeReleaseNotes?: boolean);
      {
        "type": "object",
        "properties": {
          "id": {
            "type": "string",
            "description": "Release ID or slug"
          },
          "includeReleaseNotes": {
            "default": false,
            "description": "Include associated release notes",
            "type": "boolean"
          }
        },
        "required": [
          "id"
        ],
        "$schema": "http://json-schema.org/draft-07/schema#",
        "additionalProperties": false
      }
```

<a id="save_release"></a>

### `save_release`

```text
  /**
   * Create or update a release. If `id` is provided, updates the existing release; otherwise creates a
   * new one. When creating, `name` and `pipeline` are required. Release status is modeled as the release
   * pipeline stage.
   *
   * @param id? Release ID or slug to update. Omit to create a new release.
   * @param name? Release name (required when creating)
   * @param description? Release description
   * @param version? Version identifier
   * @param pipeline? Release pipeline ID, slug, or exact name (required when creating)
   * @param stage? Release stage ID, exact name, or lifecycle type within the release pipeline
   * @param startDate? Estimated start date (ISO YYYY-MM-DD, null to remove)
   * @param targetDate? Estimated completion date (ISO YYYY-MM-DD, null to remove)
   * @param createdAt? Import/create timestamp (ISO DateTime)
   * @param startedAt? Started timestamp (ISO DateTime, null to remove)
   * @param completedAt? Completed timestamp (ISO DateTime, null to remove)
   * @param commitSha? Commit SHA associated with the release
   */
  function save_release(id?: string, name?: string, description?: string, version?: string, pipeline?: string);
  // optional (7): stage, startDate, targetDate, createdAt, startedAt, ...
      {
        "type": "object",
        "properties": {
          "id": {
            "description": "Release ID or slug to update. Omit to create a new release.",
            "type": "string"
          },
          "name": {
            "description": "Release name (required when creating)",
            "type": "string"
          },
          "description": {
            "description": "Release description",
            "type": "string"
          },
          "version": {
            "description": "Version identifier",
            "type": "string"
          },
          "pipeline": {
            "description": "Release pipeline ID, slug, or exact name (required when creating)",
            "type": "string"
          },
          "stage": {
            "description": "Release stage ID, exact name, or lifecycle type within the release pipeline",
            "type": "string"
          },
          "startDate": {
            "description": "Estimated start date (ISO YYYY-MM-DD, null to remove)",
            "anyOf": [
              {
                "type": "string"
              },
              {
                "type": "null"
              }
            ]
          },
          "targetDate": {
            "description": "Estimated completion date (ISO YYYY-MM-DD, null to remove)",
            "anyOf": [
              {
                "type": "string"
              },
              {
                "type": "null"
              }
            ]
          },
          "createdAt": {
            "description": "Import/create timestamp (ISO DateTime)",
            "type": "string"
          },
          "startedAt": {
            "description": "Started timestamp (ISO DateTime, null to remove)",
            "anyOf": [
              {
                "type": "string"
              },
              {
                "type": "null"
              }
            ]
          },
          "completedAt": {
            "description": "Completed timestamp (ISO DateTime, null to remove)",
            "anyOf": [
              {
                "type": "string"
              },
              {
                "type": "null"
              }
            ]
          },
          "commitSha": {
            "description": "Commit SHA associated with the release",
            "type": "string"
          }
        },
        "$schema": "http://json-schema.org/draft-07/schema#",
        "additionalProperties": false
      }
```

<a id="list_release_notes"></a>

### `list_release_notes`

```text
  /**
   * List release notes in the workspace, optionally filtered by pipeline or covered release.
   *
   * @param limit? Max results (default 50, max 250)
   * @param cursor? Next page cursor
   * @param orderBy? Sort: createdAt | updatedAt
   * @param query? Search release notes title
   * @param pipeline? Release pipeline ID, slug, or exact name
   * @param release? Release ID or slug
   * @param includeContent? Include markdown release notes content
   * @param includeReleases? Include associated releases
   * @param createdAt? Created after: ISO-8601 date/duration (e.g., -P1D)
   * @param updatedAt? Updated after: ISO-8601 date/duration (e.g., -P1D)
   * @param includeArchived? Include archived items
   */
  function list_release_notes(limit?: number, cursor?: string, orderBy?: "createdAt" | "updatedAt", query?: string, pipeline?: string);
  // optional (6): release, includeContent, includeReleases, createdAt, updatedAt, ...
      {
        "type": "object",
        "properties": {
          "limit": {
            "default": 50,
            "description": "Max results (default 50, max 250)",
            "type": "number",
            "maximum": 250
          },
          "cursor": {
            "description": "Next page cursor",
            "type": "string"
          },
          "orderBy": {
            "default": "updatedAt",
            "description": "Sort: createdAt | updatedAt",
            "type": "string",
            "enum": [
              "createdAt",
              "updatedAt"
            ]
          },
          "query": {
            "description": "Search release notes title",
            "type": "string"
          },
          "pipeline": {
            "description": "Release pipeline ID, slug, or exact name",
            "type": "string"
          },
          "release": {
            "description": "Release ID or slug",
            "type": "string"
          },
          "includeContent": {
            "default": false,
            "description": "Include markdown release notes content",
            "type": "boolean"
          },
          "includeReleases": {
            "default": false,
            "description": "Include associated releases",
            "type": "boolean"
          },
          "createdAt": {
            "description": "Created after: ISO-8601 date/duration (e.g., -P1D)",
            "type": "string"
          },
          "updatedAt": {
            "description": "Updated after: ISO-8601 date/duration (e.g., -P1D)",
            "type": "string"
          },
          "includeArchived": {
            "default": false,
            "description": "Include archived items",
            "type": "boolean"
          }
        },
        "$schema": "http://json-schema.org/draft-07/schema#",
        "additionalProperties": false
      }
```

<a id="get_release_note"></a>

### `get_release_note`

```text
  /**
   * Retrieve release notes by ID or slug, including markdown content.
   *
   * @param id Release notes ID or slug
   * @param includeReleases? Include associated releases
   */
  function get_release_note(id: string, includeReleases?: boolean);
      {
        "type": "object",
        "properties": {
          "id": {
            "type": "string",
            "description": "Release notes ID or slug"
          },
          "includeReleases": {
            "default": false,
            "description": "Include associated releases",
            "type": "boolean"
          }
        },
        "required": [
          "id"
        ],
        "$schema": "http://json-schema.org/draft-07/schema#",
        "additionalProperties": false
      }
```

<a id="save_release_note"></a>

### `save_release_note`

```text
  /**
   * Create or update release notes. If `id` is provided, updates the existing release notes; otherwise
   * creates a new one. When creating, `pipeline` and either `releases` or a release range are required.
   *
   * @param id? Release notes ID or slug to update. Omit to create new release notes.
   * @param pipeline? Release pipeline ID, slug, or exact name (required when creating)
   * @param title? Release notes title
   * @param content? Content as Markdown. Do not escape the string — use literal newlines and special
   *                 characters, not escape sequences. To mention a user, use @displayName (e.g.,
   *                 @johndoe)
   * @param releases? Release IDs or slugs to include in the note
   * @param rangeFromRelease? Oldest release ID or slug in the note range
   * @param rangeToRelease? Newest release ID or slug in the note range
   */
  function save_release_note(id?: string, pipeline?: string, title?: string, content?: string, releases?: string[]);
  // optional (2): rangeFromRelease, rangeToRelease
      {
        "type": "object",
        "properties": {
          "id": {
            "description": "Release notes ID or slug to update. Omit to create new release notes.",
            "type": "string"
          },
          "pipeline": {
            "description": "Release pipeline ID, slug, or exact name (required when creating)",
            "type": "string"
          },
          "title": {
            "description": "Release notes title",
            "type": "string"
          },
          "content": {
            "description": "Content as Markdown. Do not escape the string — use literal newlines and special characters, not escape sequences. To mention a user, use @displayName (e.g., @johndoe)",
            "type": "string"
          },
          "releases": {
            "description": "Release IDs or slugs to include in the note",
            "type": "array",
            "items": {
              "type": "string"
            }
          },
          "rangeFromRelease": {
            "description": "Oldest release ID or slug in the note range",
            "type": "string"
          },
          "rangeToRelease": {
            "description": "Newest release ID or slug in the note range",
            "type": "string"
          }
        },
        "$schema": "http://json-schema.org/draft-07/schema#",
        "additionalProperties": false
      }
```

## Diffs

<a id="get_diff"></a>

### `get_diff`

```text
  /**
   * Exact lookup for a Linear diff. Use with review URLs, GitHub PR URLs, Linear full identifiers,
   * UUIDs, or slugs.
   *
   * @param urlOrId Linear review URL, diff slug, pull request ID, Linear full identifier, or GitHub PR
   *                URL
   */
  function get_diff(urlOrId: string);
      {
        "type": "object",
        "properties": {
          "urlOrId": {
            "type": "string",
            "minLength": 1,
            "description": "Linear review URL, diff slug, pull request ID, Linear full identifier, or GitHub PR URL"
          }
        },
        "required": [
          "urlOrId"
        ],
        "$schema": "http://json-schema.org/draft-07/schema#",
        "additionalProperties": false
      }
```

<a id="list_diffs"></a>

### `list_diffs`

```text
  /**
   * List Linear diff pull requests visible to the authenticated user
   *
   * @param limit? Max results (default 50, max 250)
   * @param cursor? Next page cursor
   * @param orderBy? Sort: createdAt | updatedAt
   * @param query? Broad search by title, branch, PR number, or bare slug
   * @param owner? Filter returned diffs by repository owner
   * @param repo? Filter returned diffs by repository name
   * @param status? Filter returned diffs by pull request status
   */
  function list_diffs(limit?: number, cursor?: string, orderBy?: "createdAt" | "updatedAt", query?: string, owner?: string);
  // optional (2): repo, status
      {
        "type": "object",
        "properties": {
          "limit": {
            "default": 50,
            "description": "Max results (default 50, max 250)",
            "type": "number",
            "maximum": 250
          },
          "cursor": {
            "description": "Next page cursor",
            "type": "string"
          },
          "orderBy": {
            "default": "updatedAt",
            "description": "Sort: createdAt | updatedAt",
            "type": "string",
            "enum": [
              "createdAt",
              "updatedAt"
            ]
          },
          "query": {
            "description": "Broad search by title, branch, PR number, or bare slug",
            "type": "string"
          },
          "owner": {
            "description": "Filter returned diffs by repository owner",
            "type": "string"
          },
          "repo": {
            "description": "Filter returned diffs by repository name",
            "type": "string"
          },
          "status": {
            "description": "Filter returned diffs by pull request status",
            "type": "string"
          }
        },
        "$schema": "http://json-schema.org/draft-07/schema#",
        "additionalProperties": false
      }
```

<a id="get_diff_threads"></a>

### `get_diff_threads`

```text
  /**
   * Exact lookup for diff threads. Use with review URLs, GitHub PR URLs, Linear full identifiers, UUIDs,
   * or slugs.
   *
   * @param urlOrId Linear review URL, diff slug, pull request ID, Linear full identifier, or GitHub PR
   *                URL
   * @param threadId? Optional top-level thread/comment ID to return
   * @param resolved? Filter returned threads by resolved state
   * @param orderBy? Sort: createdAt | updatedAt
   */
  function get_diff_threads(urlOrId: string, threadId?: string, resolved?: boolean, orderBy?: "createdAt" | "updatedAt");
      {
        "type": "object",
        "properties": {
          "urlOrId": {
            "type": "string",
            "minLength": 1,
            "description": "Linear review URL, diff slug, pull request ID, Linear full identifier, or GitHub PR URL"
          },
          "threadId": {
            "description": "Optional top-level thread/comment ID to return",
            "type": "string"
          },
          "resolved": {
            "description": "Filter returned threads by resolved state",
            "type": "boolean"
          },
          "orderBy": {
            "default": "updatedAt",
            "description": "Sort: createdAt | updatedAt",
            "type": "string",
            "enum": [
              "createdAt",
              "updatedAt"
            ]
          }
        },
        "required": [
          "urlOrId"
        ],
        "$schema": "http://json-schema.org/draft-07/schema#",
        "additionalProperties": false
      }
```

## Milestones

<a id="list_milestones"></a>

### `list_milestones`

```text
  /**
   * List all milestones in a Linear project
   *
   * @param project Project name, ID, or slug
   */
  function list_milestones(project: string);
      {
        "type": "object",
        "properties": {
          "project": {
            "type": "string",
            "description": "Project name, ID, or slug"
          }
        },
        "required": [
          "project"
        ],
        "$schema": "http://json-schema.org/draft-07/schema#",
        "additionalProperties": false
      }
```

<a id="get_milestone"></a>

### `get_milestone`

```text
  /**
   * Retrieve details of a specific milestone by ID or name
   *
   * @param project Project name, ID, or slug
   * @param query Milestone name or ID
   */
  function get_milestone(project: string, query: string);
      {
        "type": "object",
        "properties": {
          "project": {
            "type": "string",
            "description": "Project name, ID, or slug"
          },
          "query": {
            "type": "string",
            "description": "Milestone name or ID"
          }
        },
        "required": [
          "project",
          "query"
        ],
        "$schema": "http://json-schema.org/draft-07/schema#",
        "additionalProperties": false
      }
```

<a id="save_milestone"></a>

### `save_milestone`

```text
  /**
   * Create or update a milestone in a Linear project. If `id` is provided, updates the existing
   * milestone; otherwise creates a new one. When creating, `name` is required.
   *
   * @param project Project name, ID, or slug
   * @param id? Milestone name or ID
   * @param name? Milestone name (required when creating)
   * @param description? Milestone description
   * @param targetDate? Target completion date (ISO format, null to remove)
   */
  function save_milestone(project: string, id?: string, name?: string, description?: string, targetDate?: unknown);
      {
        "type": "object",
        "properties": {
          "project": {
            "type": "string",
            "description": "Project name, ID, or slug"
          },
          "id": {
            "description": "Milestone name or ID",
            "type": "string"
          },
          "name": {
            "description": "Milestone name (required when creating)",
            "type": "string"
          },
          "description": {
            "description": "Milestone description",
            "type": "string"
          },
          "targetDate": {
            "anyOf": [
              {
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "description": "Target completion date (ISO format, null to remove)"
          }
        },
        "required": [
          "project"
        ],
        "$schema": "http://json-schema.org/draft-07/schema#",
        "additionalProperties": false
      }
```

## Teams and users

<a id="list_teams"></a>

### `list_teams`

```text
  /**
   * List teams in the user's Linear workspace
   *
   * @param limit? Max results (default 50, max 250)
   * @param cursor? Next page cursor
   * @param orderBy? Sort: createdAt | updatedAt
   * @param query? Search query
   * @param includeArchived? Include archived items
   * @param createdAt? Created after: ISO-8601 date/duration (e.g., -P1D)
   * @param updatedAt? Updated after: ISO-8601 date/duration (e.g., -P1D)
   */
  function list_teams(limit?: number, cursor?: string, orderBy?: "createdAt" | "updatedAt", query?: string, includeArchived?: boolean);
  // optional (2): createdAt, updatedAt
      {
        "type": "object",
        "properties": {
          "limit": {
            "default": 50,
            "description": "Max results (default 50, max 250)",
            "type": "number",
            "maximum": 250
          },
          "cursor": {
            "description": "Next page cursor",
            "type": "string"
          },
          "orderBy": {
            "default": "updatedAt",
            "description": "Sort: createdAt | updatedAt",
            "type": "string",
            "enum": [
              "createdAt",
              "updatedAt"
            ]
          },
          "query": {
            "description": "Search query",
            "type": "string"
          },
          "includeArchived": {
            "default": false,
            "description": "Include archived items",
            "type": "boolean"
          },
          "createdAt": {
            "description": "Created after: ISO-8601 date/duration (e.g., -P1D)",
            "type": "string"
          },
          "updatedAt": {
            "description": "Updated after: ISO-8601 date/duration (e.g., -P1D)",
            "type": "string"
          }
        },
        "$schema": "http://json-schema.org/draft-07/schema#",
        "additionalProperties": false
      }
```

<a id="get_team"></a>

### `get_team`

```text
  /**
   * Retrieve details of a specific Linear team
   *
   * @param query Team UUID, key, or name
   */
  function get_team(query: string);
      {
        "type": "object",
        "properties": {
          "query": {
            "type": "string",
            "description": "Team UUID, key, or name"
          }
        },
        "required": [
          "query"
        ],
        "$schema": "http://json-schema.org/draft-07/schema#",
        "additionalProperties": false
      }
```

<a id="list_users"></a>

### `list_users`

```text
  /**
   * Retrieve users in the Linear workspace
   *
   * @param limit? Max results (default 50, max 250)
   * @param cursor? Next page cursor
   * @param orderBy? Sort: createdAt | updatedAt
   * @param query? Filter by name or email
   * @param team? Team name or ID
   */
  function list_users(limit?: number, cursor?: string, orderBy?: "createdAt" | "updatedAt", query?: string, team?: string);
      {
        "type": "object",
        "properties": {
          "limit": {
            "default": 50,
            "description": "Max results (default 50, max 250)",
            "type": "number",
            "maximum": 250
          },
          "cursor": {
            "description": "Next page cursor",
            "type": "string"
          },
          "orderBy": {
            "default": "updatedAt",
            "description": "Sort: createdAt | updatedAt",
            "type": "string",
            "enum": [
              "createdAt",
              "updatedAt"
            ]
          },
          "query": {
            "description": "Filter by name or email",
            "type": "string"
          },
          "team": {
            "description": "Team name or ID",
            "type": "string"
          }
        },
        "$schema": "http://json-schema.org/draft-07/schema#",
        "additionalProperties": false
      }
```

<a id="get_user"></a>

### `get_user`

```text
  /**
   * Retrieve details of a specific Linear user
   *
   * @param query User ID, name, email, or "me"
   */
  function get_user(query: string);
      {
        "type": "object",
        "properties": {
          "query": {
            "type": "string",
            "description": "User ID, name, email, or \"me\""
          }
        },
        "required": [
          "query"
        ],
        "$schema": "http://json-schema.org/draft-07/schema#",
        "additionalProperties": false
      }
```

## Documentation

<a id="search_documentation"></a>

### `search_documentation`

```text
  /**
   * Search Linear's documentation to learn about features and usage
   *
   * @param query Search query
   * @param page? Page number
   */
  function search_documentation(query: string, page?: number);
      {
        "type": "object",
        "properties": {
          "query": {
            "type": "string",
            "description": "Search query"
          },
          "page": {
            "default": 0,
            "description": "Page number",
            "type": "number"
          }
        },
        "required": [
          "query"
        ],
        "$schema": "http://json-schema.org/draft-07/schema#",
        "additionalProperties": false
      }
```

## Status updates

<a id="get_status_updates"></a>

### `get_status_updates`

```text
  /**
   * List or get project/initiative status updates. Pass `id` to get a specific update, or filter to
   * list.
   *
   * @param limit? Max results (default 50, max 250)
   * @param cursor? Next page cursor
   * @param orderBy? Sort: createdAt | updatedAt
   * @param type Type of status update
   * @param id? Status update ID - if provided, returns this specific update
   * @param project? Project name, ID, or slug
   * @param initiative? Initiative name or ID
   * @param user? User ID, name, email, or "me"
   * @param createdAt? Created after: ISO-8601 date/duration (e.g., -P1D)
   * @param updatedAt? Updated after: ISO-8601 date/duration (e.g., -P1D)
   * @param includeArchived? Include archived items
   */
  function get_status_updates(limit?: number, cursor?: string, orderBy?: "createdAt" | "updatedAt", type: "project" | "initiative", id?: string);
  // optional (6): project, initiative, user, createdAt, updatedAt, ...
      {
        "type": "object",
        "properties": {
          "limit": {
            "default": 50,
            "description": "Max results (default 50, max 250)",
            "type": "number",
            "maximum": 250
          },
          "cursor": {
            "description": "Next page cursor",
            "type": "string"
          },
          "orderBy": {
            "default": "updatedAt",
            "description": "Sort: createdAt | updatedAt",
            "type": "string",
            "enum": [
              "createdAt",
              "updatedAt"
            ]
          },
          "type": {
            "type": "string",
            "enum": [
              "project",
              "initiative"
            ],
            "description": "Type of status update"
          },
          "id": {
            "description": "Status update ID - if provided, returns this specific update",
            "type": "string"
          },
          "project": {
            "description": "Project name, ID, or slug",
            "type": "string"
          },
          "initiative": {
            "description": "Initiative name or ID",
            "type": "string"
          },
          "user": {
            "description": "User ID, name, email, or \"me\"",
            "type": "string"
          },
          "createdAt": {
            "description": "Created after: ISO-8601 date/duration (e.g., -P1D)",
            "type": "string"
          },
          "updatedAt": {
            "description": "Updated after: ISO-8601 date/duration (e.g., -P1D)",
            "type": "string"
          },
          "includeArchived": {
            "default": false,
            "description": "Include archived items",
            "type": "boolean"
          }
        },
        "required": [
          "type"
        ],
        "$schema": "http://json-schema.org/draft-07/schema#",
        "additionalProperties": false
      }
```

<a id="save_status_update"></a>

### `save_status_update`

```text
  /**
   * Create or update a project/initiative status update. Omit `id` to create, provide `id` to update.
   *
   * @param type Type of status update
   * @param id? Status update ID - if provided, updates this existing update
   * @param project? Project name, ID, or slug
   * @param initiative? Initiative name or ID
   * @param body? Content as Markdown. Do not escape the string — use literal newlines and special
   *              characters, not escape sequences. To mention a user, use @displayName (e.g., @johndoe)
   * @param health? onTrack | atRisk | offTrack
   * @param isDiffHidden? Deprecated. Hide diff with previous update (create only)
   */
  function save_status_update(type: "project" | "initiative", id?: string, project?: string, initiative?: string, body?: string);
  // optional (2): health, isDiffHidden
      {
        "type": "object",
        "properties": {
          "type": {
            "type": "string",
            "enum": [
              "project",
              "initiative"
            ],
            "description": "Type of status update"
          },
          "id": {
            "description": "Status update ID - if provided, updates this existing update",
            "type": "string"
          },
          "project": {
            "description": "Project name, ID, or slug",
            "type": "string"
          },
          "initiative": {
            "description": "Initiative name or ID",
            "type": "string"
          },
          "body": {
            "description": "Content as Markdown. Do not escape the string — use literal newlines and special characters, not escape sequences. To mention a user, use @displayName (e.g., @johndoe)",
            "type": "string"
          },
          "health": {
            "description": "onTrack | atRisk | offTrack",
            "type": "string",
            "enum": [
              "onTrack",
              "atRisk",
              "offTrack"
            ]
          },
          "isDiffHidden": {
            "description": "Deprecated. Hide diff with previous update (create only)",
            "type": "boolean"
          }
        },
        "required": [
          "type"
        ],
        "$schema": "http://json-schema.org/draft-07/schema#",
        "additionalProperties": false
      }
```

<a id="delete_status_update"></a>

### `delete_status_update`

```text
  /**
   * Delete (archive) a project or initiative status update.
   *
   * @param type Type of status update
   * @param id Status update ID
   */
  function delete_status_update(type: "project" | "initiative", id: string);
      {
        "type": "object",
        "properties": {
          "type": {
            "type": "string",
            "enum": [
              "project",
              "initiative"
            ],
            "description": "Type of status update"
          },
          "id": {
            "type": "string",
            "description": "Status update ID"
          }
        },
        "required": [
          "type",
          "id"
        ],
        "$schema": "http://json-schema.org/draft-07/schema#",
        "additionalProperties": false
      }
```
