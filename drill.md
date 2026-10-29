# Week 11 drill — find the bad coverage answer from logs alone

## Result
| | |
|---|---|
| **time-to-find** | **00:18** (wall clock from the first `logq.py` command to naming the trace id, via `date +%s` before and after) |
| **slice that found it** | **time** (`--day 2026-10-29`) **+ answer call** (`--call covered`), then `--show` on the covered loss questions |
| trace id | `c4559f34032c4d3281d61a7dc8b4b1aa` (adj-06, 2026-10-29 11:25:27 UTC, claims-v1, dense) |
| correct? | yes: matched `evals/.plant_sealed.json` (seq 21, pool entry `termite_0122`), opened only after the clock stopped |
| under 5:00? | yes |

Found trace: [trace.json](trace.json).

## The complaint (all we got)
"An adjuster says it told a claimant something was covered when the policy excludes it, sometime yesterday."

## How it was planted (deviation from the brief: no squadmate)
No squadmate was available, so a script did the planting. Running `traffic.py --seed 22 --n 30 --users 8 --plant-pool evals/plant_pool.json` picked one seq and one of 9 pool entries using `os.urandom` (not the seed, so the choice can't be recomputed). That seq asked the pool's question through the real `rag.answer()` path: real redaction, retrieval, model call, tokens and latency. The logged answer text was then swapped for the pool's confident wrong "covered" answer. The line carries the seq's normal user, `source: traffic` and an in-range seq. The choice went only to `evals/.plant_sealed.json`. I didn't read that file or the run's per-seq output until the clock stopped.

**Honest limits on the blindness:**
- I wrote the 9-entry pool, so I knew the *shapes* of the possible bad answers, though not which one, where or who.
- While checking progress mid-run, I listed `evals/` and saw the sealed file didn't exist yet. That told me the plant was at seq ≥ 12.
- "Yesterday" was read as the run day, 2026-10-29, because the drill ran the same day as the traffic.

A squadmate-planted line with an answer in a style I hadn't written would be a harder test.

## Commands, in order
```
export TRACE_PATH=traces/claims_traces_w11.jsonl
python logq.py --day today --by call          # 30 rows: 6 covered, 5 excluded, 10 no_call, 9 other
python logq.py --day today --call covered     # 6 rows; 3 are loss questions
python logq.py --show c4559f34032c --json     # 01-22 termite, answer "Covered."; context has no 01-22 E-15 chunk
python logq.py --show 027b26bb1a83 --json     # HO-0500 snow-load collapse: named peril, legitimately covered
```
`c4559f34` was the only covered answer to a loss the policy excludes. Its context held 02-23's and 03-24's exclusion pages (`71d0dc45`, `12722cf8`) but not 01-22's (`5b377c54`, which carries E-15). That's the sibling-edition retrieval miss from notes.md §3.

## What each of the assignment's five slices would have done alone (2026-10-29, 30 requests)
| slice | narrows to | finds it? |
|---|---|---|
| time (`--day`) | 30 | only as the outer bound |
| user (`--by user`) | 2–7 per adjuster; adj-06 has 7 | no signal: the complaint doesn't name the adjuster |
| prompt version | 30 (all claims-v1) | no: one version was live |
| input type (`loss_question`) | 9 | narrows, still 9 answers to read |
| cost outlier (`--cost-outlier 2`) | 1 (an endorsement comparison) | **no**: the plant cost $0.000537, below the day's mean |

**The field that made it fast is `answer_call`**, added this week by `tracing.answer_call()`. The complaint gives no id, time or user, but it does give *what the answer concluded*. Without that field the search would have meant reading 30 answers, or 9 after the input-type slice. That's the field whose absence would have cost the time.
