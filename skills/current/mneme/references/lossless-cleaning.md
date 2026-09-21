# Lossless Transcript Cleaning Guidelines

This reference defines the strict protocol for denoising raw automatic speech recognition (ASR) transcripts from voice recordings, audio notes, or video calls.

## Core Invariant: Zero Information Loss

The primary failure mode when cleaning transcripts is premature summarization or aggressive pruning. You MUST preserve 100% of the conversational signal, context, and nuance.

### What MUST Be Cleaned / Denoised

1. **Verbal Fillers and Tics**:
   - Strip meaningless verbal fillers: *“um”*, *“uh”*, *“you know”*, *“like”*, *“ah”*, *“er”* (when purely passive acknowledgment).
2. **ASR Hallucinations and Stutter Loops**:
   - Remove acoustic loop repetitions (e.g., *“we need to, to, to review”* -> *“we need to review”*).
   - Remove false starts that are immediately corrected (e.g., *“We should— I mean, if we check—”* -> *“If we check—”*).
3. **Punctuation and Paragraph Structure**:
   - Break massive run-on blocks into readable, grammatically coherent paragraphs.
   - Fix missing question marks, colons, and quotation marks around direct speech.
4. **Speaker Attribution and Turn Reconstruction**:
   - When ASR mistakenly assigns all text to a single speaker or uses generic labels (`Speaker 1`), use contextual evidence (greetings, roles, self-references) to assign turns to the true participants.

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

The cleaned transcript must use standard Markdown with clear speaker headers:

```markdown
# Clean Transcript: [Meeting Title / Topic]

**Date:** YYYY-MM-DD (if known)
**Participants:**
- **[Participant 1]:** [Role / Title]
- **[Participant 2]:** [Role / Title]

---

### [Topic / Section 1]

**[Participant 1]:**
Clean dialogue text preserving all details...

**[Participant 2]:**
Clean response...
```
