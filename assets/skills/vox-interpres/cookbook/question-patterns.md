# vox-interpres cookbook: question patterns

This file optimizes the human prompts used to "talk" with a song.

## Intent coverage (implemented)

Current deterministic intents:
- `tempo`
- `key`
- `beats`
- `duration`
- `energy`
- `spectral`
- `sections`
- `metadata`
- fallback `summary`

Multi-intent is supported in one query.

---

## High-signal prompt templates

## Tempo/rhythm
- "tempo?"
- "what bpm is this?"
- "how fast is this track?"

## Key/harmony
- "what key is this in?"
- "major or minor?"
- "tonic and mode?"

## Beat grid
- "how many beats were detected?"
- "first and last beat timing?"

## Duration/segment
- "how long is the analyzed segment?"
- "did we analyze full track or a slice?"

## Energy
- "how dynamic is this?"
- "is this high-energy or calm?"
- "show low/high energy ratios"

## Spectral/timbre
- "how bright is this mix?"
- "spectral centroid and rolloff?"

## Sections/structure
- "where are the sections?"
- "give me intro/verse/chorus hints"

## Metadata/container
- "codec, bitrate, sample rate, channels?"
- "show ffprobe metadata"

---

## Multi-intent prompts (recommended)

- "tempo and key?"
- "tempo, key, and sections"
- "metadata + duration + energy"
- "spectral and energy profile"

These return concatenated deterministic answers.

---

## Spanish examples

- "¿Cuál es el tempo y la tonalidad?"
- "¿Qué tan energética es esta canción?"
- "Muéstrame la estructura por secciones"
- "Dame metadata: codec, bitrate y sample rate"

Note: intent matching is keyword-based in English tokens right now. For Spanish-first behavior, add Spanish tokens in `src/vox_interpres/query.py`.

---

## Prompt anti-patterns

Avoid vague prompts when precision matters:
- "what vibe is this?" (not model-based mood classification)
- "who is the artist?" (only if metadata tags contain it)
- "what are the lyrics?" (not implemented)

Better:
- "show key/tempo/energy and section hints"

---

## Confidence-aware phrasing

When key confidence is low, ask with fallback framing:
- "best key estimate and confidence"
- "top estimate; mention uncertainty"

When making decisions (DJ set, playlist matching), compare multiple tracks with the same command template.
