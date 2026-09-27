# Lossless Transcript Cleaning Guidelines

This reference defines the strict protocol for denoising raw automatic speech recognition (ASR) transcripts from voice recordings, audio notes, or video calls.

## Core Invariant: Zero Information Loss

The primary failure mode when cleaning transcripts is premature summarization or aggressive pruning. You MUST preserve 100% of the conversational signal, context, and nuance.

### What MUST Be Cleaned / Denoised

1. **Verbal Fillers and Tics**:
   - Strip meaningless verbal fillers across languages, such as `"um"`, `"uh"`, `"you know"`, `"like"`, `"ah"`, `"er"`, `"o sea"`, `"tipo"`, and `"este..."`, when they carry no semantic weight.
2. **ASR Hallucinations and Stutter Loops**:
   - Remove acoustic loop repetitions (for example, `"we need to, to, to review"` -> `"we need to review"`).
   - Remove false starts that the speaker immediately corrects (for example, `"We should, I mean, if we check"` -> `"If we check"`).
3. **Punctuation and Paragraph Structure**:
   - Break run-on blocks into readable, grammatically coherent paragraphs.
   - Fix missing question marks, colons, and quotation marks around direct speech.
4. **Speaker Attribution and Turn Reconstruction**:
   - Preserve every speaker turn in chronological order. NEVER merge alternating turns into a single speaker block.
   - Strip meeting-platform suffixes such as `(You)`, `(Host)`, or `(Guest)` while preserving full Unicode and accented names.
   - When ASR assigns all text to one speaker, uses generic labels (`Speaker 1`), or misspells names, use contextual clues (greetings, roles, self-references) and any available participant roster to assign turns accurately.

### What MUST NEVER Be Dropped (Sacred Signal)

1. **Exact Numbers, Amounts, and Dates**:
   - Financial figures, quantities, deadlines, percentages, dates, and times.
2. **Disagreements, Hesitations, and Unresolved Questions**:
   - If participants debate a topic, record both viewpoints and the state in which the discussion concluded.
3. **Tangents and Contextual Anecdotes**:
   - Preserve side remarks and background context in full prose; they frequently contain crucial domain rationale.
4. **Specific Names and Terminology**:
   - Keep names of people, projects, organizations, products, and specific domain terms verbatim.

## Output Format

Format the cleaned transcript as standard Markdown with clear speaker headers in a continuous chronological stream. Do not insert artificial topic headings (`### 1. ...`) that split the dialogue into chapters. Do not put internal pipeline labels (`denoised`, `raw`) in user-facing titles:

```markdown
# Clean Transcript: [Meeting Title]

**Date:** YYYY-MM-DD (if known)
**Participants:**
- **[Participant 1]:** [Role]
- **[Participant 2]:** [Role]

---

**[Participant 1]:**
Clean dialogue text preserving all details...

**[Participant 2]:**
Clean response...
```
