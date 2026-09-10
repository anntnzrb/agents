# XML view rules

Static AST and semantic validation rules for Odoo 17 XML views and QWeb templates.

## Overview

The XML view linter (`xml_view_linter.py`) parses XML files into an AST and evaluates structural rules to detect syntax errors, deprecated Odoo 16 patterns, fragile xpath selectors, accessibility issues, and non-extensible containers before deployment.

These rules run automatically when executing `odoo-ops lint <module>` and can be run independently with `odoo-ops lint-views <module>`.

## Rule catalog

| Rule ID | Severity | Description | Remedy |
| --- | --- | --- | --- |
| `ODOO_XML_001` | CRITICAL | Deprecated `attrs` or `states` attributes | Replace with direct expressions: `invisible="..."`, `readonly="..."`, `required="..."`. |
| `ODOO_XML_002` | CRITICAL | Deprecated `invisible` in `<tree>` column | Use `column_invisible="..."` for list view columns in Odoo 17. |
| `ODOO_XML_003` | WARNING | Fragile XPath using exact `@class` match | Use Odoo XPath helper `hasclass('classname')`. |
| `ODOO_XML_004` | WARNING | Fragile positional XPath indexing (`//group[1]`) | Target elements semantically using `@name` or unique structural anchors. |
| `ODOO_XML_005` | CRITICAL | Duplicate field without mutually exclusive conditions | Ensure duplicate field occurrences define distinct mutually exclusive `invisible` rules. |
| `ODOO_XML_006` | WARNING | Inner `<group>` or `<page>` missing `name` | Add semantic `name="..."` attribute to enable clean inheritance and extension. |
| `ODOO_XML_007` | WARNING | Bootstrap alert missing accessible role | Add `role="status"` or `role="alert"` to `<div class="alert ...">`. |
| `ODOO_XML_008` | WARNING | Literal `<xpath>` tag inside non-inherited template | Remove misplaced `<xpath>` or specify `inherit_id="..."` on `<template>`. |
| `ODOO_XML_009` | INFO | Dead commented-out XML UI code block | Delete obsolete commented-out XML blocks instead of leaving dead markup. |

## CLI invocation

Run view checks as part of the standard linting suite:

```text
odoo-ops lint <module>
odoo-ops lint <module> --strict
```

Or run dedicated XML view checks:

```text
odoo-ops lint-views <module>
odoo-ops lint-views <module> --strict --json
odoo-ops lint-views --all
```
