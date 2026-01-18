# Tooling Reference

Short constraints and defaults for each CLI command.

## search
- Command: `exa.ts search <query>`
- Options: `-n <num>`, `--type <auto|fast|deep>`, `--text-max <num>`
- Notes: returns text output from `web_search_exa`.

## contents
- Command: `exa.ts contents <url>`
- Options: `--text-max <num>`
- Notes: single URL only; uses `crawling_exa`.

## answer
- Command: `exa.ts answer <question>`
- Options: `--text`, `--system <prompt>`, `--schema <json>`
- Notes: SDK-backed; returns answer + citations.

## research-start
- Command: `exa.ts research-start <instructions>`
- Options: `--model <exa-research|exa-research-pro>`
- Notes: returns task id (async).

## research-check
- Command: `exa.ts research-check <task-id>`
- Notes: poll until status `completed`.

## deep-search
- Command: `exa.ts deep-search <objective>`
- Options: `--queries a,b,c`

## code-context
- Command: `exa.ts code-context <query>`
- Options: `--tokens <1000-50000>` (default 50000)

## company-research
- Command: `exa.ts company-research <company name>`
- Options: `-n <num>`

## linkedin-search
- Command: `exa.ts linkedin-search <query>`
- Options: `--type <profiles|companies|all>`, `-n <num>`
