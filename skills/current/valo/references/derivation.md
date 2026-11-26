# Snapshot derivation heuristics

These heuristics are tunable judgment calls, not truths. They are embedded
in the snapshot output under `thresholds` so users can judge every derived
claim against the raw numbers. The raw agent rows are always one `agents`
call away; when the user disputes a derivation, show the thresholds and the
rows, not just the conclusion.

## Contents

- Abuse: meta bucket
- Abuse: niche bucket
- Avoid
- Movers
- Why winrate times pickrate is the signal

## Abuse: meta bucket

Rule: winrate at least 51.0 and pickrate at least 8.0.

An agent above both bars is statistically broken in the current meta: it wins
more than half its games while showing up in enough games that the winrate
cannot be a small-sample artifact. These are the agents every lobby sees and
every lobby loses to. The 51/8 split is a judgment call: lowering the
pickrate bar floods the bucket with noise, raising it hides genuinely
oppressive picks that players have not caught onto yet.

## Abuse: niche bucket

Rule: winrate at least 51.0 and pickrate below 8.0, labeled separately.

Same winrate bar, but low presence. These are specialist or underrated
picks: strong when played well, rare enough that the meta has not priced
them in. They are labeled separately because the interpretation differs:
a niche pick is a personal weapon to learn, not proof the agent is broken
in every hand. Low-sample caution applies; a 0.7 percent pickrate agent can
swing half a point of winrate in a week.

## Avoid

Rule: the bottom three agents by winrate.

Not "unplayable", just the worst-performing end of the ladder right now.
Three is a judgment call: enough to name the real problem tier without
shaming half the roster. An agent here with a positive 7-day delta is
recovering; one trending down is getting worse. The rows carry the deltas
so the user can tell.

## Movers

Rule: the three biggest 7-day win-rate risers and the three biggest fallers,
ranked by signed delta.

Movers answer "what changed this week" mechanically, before patch notes are
digested into the meta. Risers often signal an undervalued buff or a map
pool shift favoring the agent; fallers track nerfs or meta adaptation.
Small deltas near zero are noise, but the ranking is still the honest
answer to the question.

## Why winrate times pickrate is the signal

Winrate alone rewards one-trick agents with tiny samples. Pickrate alone
rewards comfort picks everyone plays at average skill. The combination
separates four cases that one number cannot: broken-in-the-meta (high,
high), niche-strong (high, low), popular-but-mediocre (low, high), and
irrelevant (low, low). That is why the abuse derivation is a conjunction
and why the niche bucket exists instead of a single ranking.
