# Eval run `w12-baseline`

Ran on: 2026-11-02. Graded 7 cases.

**Suite: PASS 1/7** (assertions 2/7, judge 1/7)

**Judge vs hand labels:** UNLABELLED 7/7 -- no agreement number yet. Fill labels.json in the run directory (blind to judge.json), then rescore.

## Assertions (run before the judge)

| assertion | pass |
|---|---|
| citations_valid_for_loss_date | 7/7 |
| deciding_clause_cited | 6/7 |
| in_force_not_misflagged | 7/7 |
| limits_for_right_coverage_line | 3/4 |
| no_decision_language | 3/7 |
| no_pii_in_run_or_referral | 7/7 |
| referral_by_agent | 7/7 |
| summary_limits_not_conflated | 1/2 |

## Error taxonomy (integrated system)

| mode | origin | severity | frequency | example trace |
|---|---|---|---|---|
| `decision_language` | week 5 leading_question_accepted (generalised) | S1 | 85.7% (6/7) | `e6fb61c43174` (w12-01) |
| `redaction_strips_cause` | NEW (integration) | S2 | 28.6% (2/7) | `6948e86a92ca` (w12-06) |
| `unsupported_paraphrase` | week 6 judge tag | S2 | 28.6% (2/7) | `4dd521c3f32d` (w12-02) |
| `scope_dropped_at_mcp_hop` | NEW (integration) | S2 | 14.3% (1/7) | `e6fb61c43174` (w12-01) |
| `wrong_coverage_line` | NEW (integration) | S2 | 14.3% (1/7) | `4dd521c3f32d` (w12-02) |
| `limit_conflation` | NEW (integration) | S2 | 14.3% (1/7) | `4dd521c3f32d` (w12-02) |
| `missed_deciding_clause` | week 5 absence_as_exclusion / retrieval miss | S2 | 14.3% (1/7) | `62be913d515a` (w12-04) |

## Trajectory

3 cases. Tool-choice accuracy **67%**, argument validity 67%, trajectory pass 67%, outcome pass 0%: **outcome − trajectory gap -66.7 points**.
Outcome passed but path failed: none. Path passed but outcome failed: ['w12-02', 'w12-06'].

## Cost and latency per claim triaged

- cost: mean $0.001807, p50 $0.002011, p95 $0.002369
- tokens: mean 18,224, p95 22,560; LLM turns mean 6.14
- latency excl. rate-limit waits: p50 15.8s, p95 36.1s; wall incl. waits p50 244.1s
- p50 latency by span kind (ms): {'llm': 6700.9, 'mcp_client': 7911.1, 'mcp_server': 1888.4, 'referral': 2.9, 'tool': 4.2}
- judge cost per case (eval only, not triage): $0.000727

## Cases

| case | claim | scenario | pass | failed assertions | judge | modes | trace |
|---|---|---|---|---|---|---|---|
| w12-01 | CLM-2024-000073 | hh_surface_water_aug24 | FAIL | no_decision_language | fail | decision_language, scope_dropped_at_mcp_hop | `e6fb61c43174` |
| w12-02 | CLM-2024-000079 | hh_surface_water_aug24 | FAIL | limits_for_right_coverage_line, summary_limits_not_conflated | fail | decision_language, limit_conflation, unsupported_paraphrase, wrong_coverage_line | `4dd521c3f32d` |
| w12-03 | CLM-2024-000077 | hh_surface_water_aug24 | PASS | - | pass | - | `2d70fae66a02` |
| w12-04 | CLM-2025-000093 | hh_surface_water_23 | FAIL | deciding_clause_cited, no_decision_language | fail | decision_language, missed_deciding_clause | `62be913d515a` |
| w12-05 | CLM-2025-000034 | hh_surface_water_23_floodzone | FAIL | no_decision_language | fail | decision_language | `154f7bde1a9a` |
| w12-06 | CLM-2026-000002 | hh_river_23 | FAIL | no_decision_language | fail | decision_language, redaction_strips_cause, unsupported_paraphrase | `6948e86a92ca` |
| w12-07 | CLM-2023-000029 | hh_river_23 | FAIL | - | fail | decision_language, redaction_strips_cause | `25d475eb48c9` |
