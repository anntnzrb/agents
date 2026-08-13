---
name: gh-discussions-answerer
description: Find and answer unanswered GitHub Discussions for open-source contribution.
license: AGPL-3.0-or-later
metadata:
  author: anntnzrb

---

# GitHub Discussions Answerer

Find code-verifiable answers. Keep discovery and analysis read-only.

## Constraints

- Target 10 posted answers; discover roughly 15 candidates
- Answers MUST be verified against repository code or docs
- Discard uncertain candidates. Keep every verified candidate
- External posting requires explicit user authorization
- NEVER post during discovery or analysis
- Use the runtime's actual agent tools; NEVER invent wrappers

## Phase 1: Discover

Calculate date boundaries from today. Query GitHub Discussions read-only:

```text
gh api graphql -f query='{
  search(query: "is:open comments:0 created:>YYYY-MM-DD category:Q&A NOT author:bot", type: DISCUSSION, first: 100) {
    nodes { ... on Discussion { title number url bodyText repository { nameWithOwner } category { name } } }
  }
}'
```

Run complementary searches for:

- repositories with `stars:>100`
- Help or Support categories from the last 14 days
- General discussions that ask actionable questions

Merge and deduplicate by `owner/repo#number`.

Prioritize Q&A, Questions, Help, Support, Troubleshooting, Technical, Development, and Usage.

Skip:

- feature requests, RFCs, proposals, or announcements
- roadmap, ETA, or maintainer-priority questions
- bot-created discussions
- bodies shorter than 20 characters
- discussions with existing comments
- questions lacking a code-verifiable answer

Return roughly 15 candidates as `[owner/repo#number] title - category`.

## Phase 2: Analyze

Fan out independent candidates through available read-only agents. Each assignment MUST include the
repository, discussion number, title, constraints, and acceptance criteria.

Read-only commands:

```text
gh api repos/<owner>/<repo>/discussions/<number>
gh search code '<keyword>' --repo <owner>/<repo>
gh api repos/<owner>/<repo>/contents/<path> --jq '.content' | base64 -d
```

A verified answer MUST provide at least one:

- exact configuration or command
- code fix with file and line evidence
- actionable workaround
- mechanism-backed explanation
- repository documentation link

Discard answers that merely restate limitations or uncertainty.

Return `VERIFIED: <answer>` or `DISCARD: <reason>`.

## Phase 3: Authorize and post

Present the verified answers before mutation. If the user has not explicitly authorized posting,
request one confirmation for the complete batch.

Post only authorized answers:

```text
gh api graphql -f query='{
  repository(owner:"<owner>", name:"<repo>") {
    discussion(number:<number>) { id }
  }
}'

gh api graphql \
  -f query='mutation AddDiscussionComment($discussionId: ID!, $body: String!) {
  addDiscussionComment(input: {discussionId: $discussionId, body: $body}) {
    comment { url }
  }
}' \
  -F discussionId='<discussion-id>' \
  -F 'body=@<answer-file>'
```

Write the exact authorized answer to `<answer-file>`. Pass it as the typed `$body` variable; NEVER
interpolate answer text into the GraphQL document or a shell command.

After an uncertain timeout, re-read the discussion before retrying. This prevents duplicate comments.

Unsubscribe only when explicitly requested:

```text
gh api -X DELETE /notifications/threads/<thread-id>/subscription
```

Re-read each posted comment. Return posted URLs and every failed or skipped mutation.

## Answer format

- One or two sentences
- Include file and line evidence when relevant
- Give a concrete action
- Remove fluff and AI-speak
