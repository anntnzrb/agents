# Action Item & Summary Synthesis Guidelines

This reference defines how to transform cleaned transcripts into structured executive summaries and actionable task lists.

## 1. Executive Summary Schema

The summary captures high-level context, core decisions, and follow-up commitments without obscuring the underlying transcript.

```markdown
## Executive Summary

### Context and Objective
Brief description of the meeting purpose and primary participants.

### Key Decisions Agreed
- **[Decision 1]**: Detail of the agreement reached and parties involved.
- **[Decision 2]**: Specific rules or policies established.

### Commitments and Next Steps
- **[Owner]**: Follow-up task or scheduled session with target date/time.
```

## 2. Action Items Schema (JSON)

When extracting actionable items for task managers, checklists, or issue trackers, format them with structured fields and unambiguous completion criteria.

```json
{
  "meeting_id": "2026-09-20_planning-session",
  "generated_at": "2026-09-20T12:00:00Z",
  "tasks": [
    {
      "id": "ACTION-01",
      "title": "Update client onboarding checklist with new compliance requirements",
      "owner": "Operations Team",
      "priority": "high",
      "context": "Discussed during the quarterly operations review to ensure all new accounts provide required identity verification.",
      "scope": [
        "Add identity verification step to onboarding checklist template.",
        "Notify account managers of updated verification timeline.",
        "Archive outdated checklist version."
      ],
      "completion_criteria": [
        "Updated checklist template is published and accessible to the team.",
        "All new client accounts initiate verification under the new procedure."
      ]
    }
  ]
}
```

## 3. General Principles

- **Capture actionable intent**: Identify what needs to be done, who owns it, and the deadline discussed.
- **State clear completion conditions**: Frame completion criteria in testable or observable outcomes.
- **Preserve accountability**: Link each action item directly to the discussion context that motivated it.
