# Firecrawl Parse Reference

Convert local disk documents (PDF, DOCX, XLSX, RTF, ODT, HTML) into clean, structured Markdown, AI-generated summaries, or targeted question-answering outputs.

## Command Syntax

```bash
firecrawl parse <file-path> [options]
```

## Options & Flags

- `-S, --summary`: Generate an executive summary of the document.
- `-Q, --query <text>`: Ask a specific analytical question about the document content.
- `-o, --output <path>`: Write parsed output to a file (recommended).
- `--json`: Output result as structured JSON.
- `--pretty`: Pretty-print JSON.

## Supported File Formats

- PDF (`.pdf`)
- Microsoft Word (`.docx`, `.doc`)
- Microsoft Excel (`.xlsx`, `.xls`)
- Rich Text Format (`.rtf`)
- OpenDocument Text (`.odt`)
- HTML (`.html`, `.htm`)

## Recipes

### 1. Convert Local PDF to Markdown
```bash
firecrawl parse "./whitepaper.pdf" -o .firecrawl/whitepaper.md
```

### 2. Generate Document Summary
```bash
firecrawl parse "./financial-report.xlsx" -S -o .firecrawl/financial-summary.md
```

### 3. Targeted Document Q&A
```bash
firecrawl parse "./contract.docx" -Q "What are the termination notice requirements and liability caps?" -o .firecrawl/contract-qa.md
```

## Constraints & Limits

- Maximum file upload size is **50 MB** per document.
- Quoting: Always quote local paths with spaces (e.g. `firecrawl parse "./Q4 Report.pdf"`).
- Credits: Document parsing consumes approximately 1 credit per PDF page (HTML is 1 credit flat).
- Always save output to `.firecrawl/` with `-o` to avoid flooding agent context with multi-page text dumps.
