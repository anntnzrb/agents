# Meeting Minutes Synthesis

The agent writes minutes from the clean transcript. No script does this: keyword matching cannot tell a decision from a passing remark.

## Inputs

1. Read the whole clean transcript. Do not summarize from a partial read.
2. Read the participant roster. In a Linear archive, the roster is the `## Key People` section of the index document; see [Archive in Linear](#archive-in-linear).
3. Read one or two recent minutes in the same archive and copy their language, title pattern, and section layout. Write in the meeting's language unless the user asks otherwise.

## Grounding rules

- Use full names and roles from the roster. Correct ASR misspellings of names to the roster spelling.
- Ask the user for the date and start time when the transcript does not state them. A file timestamp is not the meeting time.
- Leave out any figure the transcript states ambiguously, such as a goal value the speakers did not explain. A marker such as `[as transcribed]` still spreads the doubt, so omit the figure from the minutes. The transcript keeps it verbatim.
- Keep every quantity the speakers worked through explicitly, such as a computed total.
- Mark an owner or task inferred rather than assigned with `[inferido]` (Spanish) or `[inferred]` (English).
- Record each unresolved question and who is resolving it. Do not turn an open question into a decision.

## Minutes layout

Linear renders the document title as the page header, so do not repeat it as the first heading when uploading.

```markdown
# Resumen Ejecutivo: <tema>

**Fecha:** YYYY-MM-DD (Día) · HH:MM AM
**Proyecto:** <proyecto>
**Participantes:**

* **<Nombre completo>:** <rol del roster>

**Participaciones puntuales / Coordinaciones:** <personas que intervinieron por chat o teléfono>

---

## 1. Contexto y Objetivos

## 2. Acuerdos y Decisiones Clave

### A. <bloque temático>

1. **<Decisión>:** <detalle, partes involucradas, condiciones y cifras>

## 3. Preguntas Abiertas

## 4. Próximos Pasos y Compromisos

| Responsable | Compromiso / Tarea |
| -- | -- |
| **<Nombre completo>** | • <tarea concreta con criterio de cierre>&#10;• <otra tarea> |
```

- One row per owner. Separate tasks inside a cell with `&#10;• `.
- Each task names a concrete deliverable and, where the meeting gave one, its blocker or deadline.

## Archive in Linear

Use the `linear` skill for every call below.

1. Find the pinned index document of minutes and transcripts with `list_documents`. Read it with `get_document`.
2. Read the newest existing minutes and transcript and copy their title pattern, for example `YYYY-MM-DD · HH:MM · <type>: <topic> [<platform>]`. Reuse each document type's existing `color`.
3. Create both documents with `save_document` in the same project as the existing ones.
4. Re-read both with `get_document` and compare their content byte counts with the local files.
5. Update the index with `save_document` and a `patch`; never resend the whole index. Insert the meeting under its month and day heading, newest month first, linking both new documents. Add newcomers to `## Key People` with the role the user gave.
6. Re-read the index and confirm the new entry and roster lines.

Creating and editing Linear documents writes to an external system. Get the user's approval before step 3.
