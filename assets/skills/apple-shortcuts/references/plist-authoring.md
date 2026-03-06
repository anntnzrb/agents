# Plist Authoring

Use this reference only when the user explicitly wants raw `.shortcut` generation, plist/XML output, or an importable signed file.

## Rule
- Prefer the normal blueprint/action-graph workflow unless raw serialization is the point.
- Keep output minimal: root plist, action array, variable wiring, control-flow links, signing/import steps.
- Do not mirror giant action catalogs here; pull only the exact action identifiers needed for the requested shortcut.

## Root Shape

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>WFWorkflowActions</key>
  <array>
    <!-- action dicts -->
  </array>
  <key>WFWorkflowClientVersion</key>
  <string>2700.0.4</string>
  <key>WFWorkflowMinimumClientVersion</key>
  <integer>900</integer>
  <key>WFWorkflowMinimumClientVersionString</key>
  <string>900</string>
  <key>WFWorkflowIcon</key>
  <dict>
    <key>WFWorkflowIconGlyphNumber</key>
    <integer>59511</integer>
    <key>WFWorkflowIconStartColor</key>
    <integer>4282601983</integer>
  </dict>
  <key>WFWorkflowImportQuestions</key>
  <array/>
  <key>WFWorkflowName</key>
  <string>My Shortcut</string>
</dict>
</plist>
```

## Minimal Action Dict

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.gettext</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>UUID</key>
    <string>A1B2C3D4-E5F6-7890-ABCD-EF1234567890</string>
    <key>WFTextActionText</key>
    <string>Hello World!</string>
  </dict>
</dict>
```

## Variable Tokens
- UUIDs should be uppercase.
- Use `WFTextTokenAttachment` when the parameter is only a variable reference.
- Use `WFTextTokenString` when text wraps one or more variables.
- Variable placement is driven by `attachmentsByRange`.

```xml
<key>Text</key>
<dict>
  <key>Value</key>
  <dict>
    <key>string</key>
    <string>Hello, &#xFFFC;!</string>
    <key>attachmentsByRange</key>
    <dict>
      <key>{7, 1}</key>
      <dict>
        <key>OutputUUID</key>
        <string>A1B2C3D4-E5F6-7890-ABCD-EF1234567890</string>
        <key>OutputName</key>
        <string>Text</string>
        <key>Type</key>
        <string>ActionOutput</string>
      </dict>
    </dict>
  </dict>
  <key>WFSerializationType</key>
  <string>WFTextTokenString</string>
</dict>
```

## Control Flow Wiring
- `GroupingIdentifier` links the start, middle, and end actions in a block.
- `WFControlFlowMode` must be an integer.
- Modes: `0` start, `1` middle (`Otherwise` / menu case), `2` end.

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.repeat.count</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>GroupingIdentifier</key>
    <string>11111111-1111-1111-1111-111111111111</string>
    <key>WFControlFlowMode</key>
    <integer>0</integer>
    <key>WFRepeatCount</key>
    <integer>3</integer>
  </dict>
</dict>
```

```xml
<dict>
  <key>WFWorkflowActionIdentifier</key>
  <string>is.workflow.actions.conditional</string>
  <key>WFWorkflowActionParameters</key>
  <dict>
    <key>GroupingIdentifier</key>
    <string>22222222-2222-2222-2222-222222222222</string>
    <key>WFControlFlowMode</key>
    <integer>0</integer>
    <key>WFCondition</key>
    <string>Equals</string>
  </dict>
</dict>
```

## Signing And Import
1. Write the plist as XML to `MyShortcut.shortcut`.
2. Sign it:

```bash
shortcuts sign --mode anyone --input MyShortcut.shortcut --output MyShortcut-signed.shortcut
```

3. Open the signed file in Shortcuts.app to import it.

## Guardrails
- Prefer exact action identifiers over guessed names.
- Keep the snippet set small and task-specific.
- If a parameter shape is uncertain, say so and provide the nearest verified structure instead of inventing one.
