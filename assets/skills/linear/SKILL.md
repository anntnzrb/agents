---
name: linear
description: Manage Linear issues, projects, teams, cycles, comments, and documentation through MCPorter.
compatibility: Requires Linear configured and authenticated in MCPorter under server name `linear`.
---

# Linear

## Overview

This skill provides structured workflows for managing issues, projects, and teams through MCPorter.

## Prerequisites
- Linear must be configured and authenticated in MCPorter under server name `linear`
- Confirm access to the relevant Linear workspace, teams, and projects

## Tool Routing
- Execute operations with `mcporter call linear.<tool>`.
- Run `mcporter list linear --schema` only when the needed tool signature is unknown.

## Required Workflow

**Follow these steps in order. Do not skip steps.**

### Step 0: Verify Linear access

If Linear is unavailable through MCPorter server `linear`, run `mcporter auth linear`, then verify workspace access. Continue with Step 1 after access is available.

### Step 1
Clarify the user's goal and scope (e.g., issue triage, sprint planning, documentation audit, workload balance). Confirm team/project, priority, labels, cycle, and due dates as needed.

### Step 2
Select the appropriate workflow (see Practical Workflows below) and identify the Linear tools you will need. Confirm required identifiers (issue ID, project ID, team key) before calling tools.

### Step 3
Execute Linear operations in logical batches through `mcporter call linear.<tool>`:
- Read first (list/get/search) to build context.
- Create or update next (issues, projects, labels, comments) with all required fields.
- For bulk operations, explain the grouping logic before applying changes.

### Step 4
Summarize results, call out remaining gaps or blockers, and propose next actions (additional issues, label changes, assignments, or follow-up comments).

## Available Tools

Issue Management: `list_issues`, `get_issue`, `create_issue`, `update_issue`, `list_my_issues`, `list_issue_statuses`, `list_issue_labels`, `create_issue_label`

Project & Team: `list_projects`, `get_project`, `create_project`, `update_project`, `list_teams`, `get_team`, `list_users`

Documentation & Collaboration: `list_documents`, `get_document`, `search_documentation`, `list_comments`, `create_comment`, `list_cycles`

## Practical Workflows

- Sprint Planning: Review open issues for a target team, pick top items by priority, and create a new cycle (e.g., "Q1 Performance Sprint") with assignments.
- Bug Triage: List critical/high-priority bugs, rank by user impact, and move the top items to "In Progress."
- Documentation Audit: Search documentation (e.g., API auth), then open labeled "documentation" issues for gaps or outdated sections with detailed fixes.
- Team Workload Balance: Group active issues by assignee, flag anyone with high load, and suggest or apply redistributions.
- Release Planning: Create a project (e.g., "v2.0 Release") with milestones (feature freeze, beta, docs, launch) and generate issues with estimates.
- Cross-Project Dependencies: Find all "blocked" issues, identify blockers, and create linked issues if missing.
- Automated Status Updates: Find your issues with stale updates and add status comments based on current state/blockers.
- Smart Labeling: Analyze unlabeled issues, suggest/apply labels, and create missing label categories.
- Sprint Retrospectives: Generate a report for the last completed cycle, note completed vs. pushed work, and open discussion issues for patterns.

## Tips for Maximum Productivity

- Batch operations for related changes; consider smart templates for recurring issue structures.
- Use natural queries when possible ("Show me what John is working on this week").
- Leverage context: reference prior issues in new requests.
- Break large updates into smaller batches to avoid rate limits; cache or reuse filters when listing frequently.

## Troubleshooting

- Authentication: Run `mcporter auth linear`, then verify workspace permissions and API access.
- Tool Calling Errors: Confirm the model supports multiple tool calls, provide all required fields, and split complex requests.
- Missing Data: Refresh token, verify workspace access, check for archived projects, and confirm correct team selection.
- Performance: Remember Linear API rate limits; batch bulk operations, use specific filters, or cache frequent queries.
