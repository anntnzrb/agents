# Debug Playbook

## Symptom: Shortcut stops mid-run
- Check the first action that depends on external state (permissions, network, app data).
- Add temporary notifications after each major block.
- Verify input type entering the failing action.

## Symptom: Empty output
- Confirm each branch writes to the same output variable.
- Check list/dictionary key names for typos or missing keys.
- Add fallback output when results are empty.

## Symptom: Works on iPhone, fails on Mac
- Check action availability and trigger surface differences.
- Replace mobile-specific actions with neutral alternatives where possible.
- Re-test from app and widget independently.

## Symptom: Automation runs too often
- Add state guard (time window, last-run value, condition gate).
- Use trigger-specific constraints when available.
- Add explicit cooldown logic.

## Symptom: API actions fail intermittently
- Validate headers and auth token freshness.
- Add retry with max attempts and branch for hard failure.
- Log status code and response fragment in debug mode.

## Symptom: Watch or Vision Pro execution mismatch
- Verify whether shortcut is intended to run locally or trigger remote app/device actions.
- Minimize UI-heavy actions for constrained surfaces.
- Keep interaction flow short and deterministic.

## CLI-Specific Checks
- `shortcuts -h` for command surface.
- `shortcuts help run` for I/O and output type behavior.
- Use `--output-path` and `--output-type` to make outputs explicit in automation scripts.
