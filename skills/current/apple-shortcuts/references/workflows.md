# Workflows

Read this when selecting an end-to-end blueprint, artifact, inspection, or app-integration route.

## Workflow A: New Shortcut (User-Level)

1. Capture intent:
   - Goal
   - Trigger surface (app, widget, Siri, watch, automation)
   - Input/output types
   - Device scope
2. Draft blueprint with `make_blueprint.py`
3. Build action graph:
   - Normalize input first
   - Branch only when needed
   - Name variables explicitly
4. Add resilience:
   - Empty input guard
   - Permission/network checks
   - Fallback output
5. Validate against test matrix

## Workflow B: Personal/Home Automation

1. Classify automation type:
   - Personal automation trigger
   - Home automation trigger
2. Verify trigger availability on target OS/device
3. Confirm unattended execution constraints
4. Add state checks to avoid repeated/looping behavior
5. Include disable/rollback procedure

## Workflow C: Cross-Device Shortcut

1. Identify creation surface vs execution surfaces
2. Split device-specific actions into branches
3. Keep shared logic in common pre/post sections
4. Test each target device explicitly

## Workflow D: App Integration (Developer)

1. Choose App Intents entity and intent boundaries
2. Define App Shortcut phrases and discoverability
3. Validate behavior in Shortcuts + Spotlight entry points
4. Confirm parameter typing and entity resolution
5. Add migration notes if converting SiriKit custom intents

## Standard Output Shape

Always produce:

1. Goal
2. Trigger
3. Inputs
4. Action Graph (ordered)
5. Variables (name, type, source)
6. Failure Handling
7. Validation Matrix
