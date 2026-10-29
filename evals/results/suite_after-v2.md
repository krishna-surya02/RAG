### eval suite `after-v2` — PASS 9/13

prompt claims-v2, retrieval scoped, answers by openai/gpt-oss-120b, judged by openai/gpt-oss-20b

| case | result | verdict | call | why it failed |
|---|---|---|---|---|
| q01 | PASS | correct_supported | covered |  |
| q02 | PASS | correct_supported | excluded |  |
| q03 | PASS | correct_supported | other |  |
| q04 | **FAIL** | wrong_call | other | verdict wrong_call |
| q05 | PASS | correct_supported | covered |  |
| q06 | PASS | correct_supported | covered |  |
| q07 | **FAIL** | right_call_wrong_support | other | assertion exclusion_id_on_denial: expected 'E-10', judge saw None |
| q08 | PASS | correct_supported | other |  |
| q09 | PASS | right_call_wrong_support | other |  |
| q10 | PASS | correct_supported | excluded |  |
| q11 | **FAIL** | wrong_call | excluded | verdict wrong_call; assertion exclusion_id_on_denial: expected 'F-1', judge saw 'E-3' |
| q12 | **FAIL** | wrong_call | other | verdict wrong_call |
| w11_termite_0122 | PASS | correct_supported | other |  |

**vs `before`: 6/13 -> 9/13**

- q04: PASS -> FAIL
- q05: FAIL -> PASS
- q08: FAIL -> PASS
- q10: FAIL -> PASS
- w11_termite_0122: FAIL -> PASS
