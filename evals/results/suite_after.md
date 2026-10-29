### eval suite `after` — PASS 9/13

prompt claims-v3, retrieval scoped, answers by openai/gpt-oss-120b, judged by openai/gpt-oss-20b

| case | result | verdict | call | why it failed |
|---|---|---|---|---|
| q01 | PASS | correct_supported | covered |  |
| q02 | PASS | correct_supported | excluded |  |
| q03 | PASS | correct_supported | other |  |
| q04 | PASS | correct_supported | covered |  |
| q05 | PASS | correct_supported | covered |  |
| q06 | **FAIL** | wrong_call | other | verdict wrong_call |
| q07 | **FAIL** | right_call_wrong_support | other | assertion exclusion_id_on_denial: expected 'E-10', judge saw None |
| q08 | PASS | correct_supported | covered |  |
| q09 | PASS | correct_supported | other |  |
| q10 | PASS | correct_supported | excluded |  |
| q11 | **FAIL** | right_call_wrong_support | excluded | assertion exclusion_id_on_denial: expected 'F-1', judge saw 'E-3' |
| q12 | **FAIL** | wrong_call | other | verdict wrong_call |
| w11_termite_0122 | PASS | correct_supported | excluded |  |

**vs `before`: 6/13 -> 9/13**

- q05: FAIL -> PASS
- q06: PASS -> FAIL
- q08: FAIL -> PASS
- q10: FAIL -> PASS
- w11_termite_0122: FAIL -> PASS
