### eval suite `before` — PASS 6/13

prompt claims-v1, retrieval dense, answers by openai/gpt-oss-120b, judged by openai/gpt-oss-20b

| case | result | verdict | call | why it failed |
|---|---|---|---|---|
| q01 | PASS | correct_supported | covered |  |
| q02 | PASS | right_call_wrong_support | no_call |  |
| q03 | PASS | correct_supported | other |  |
| q04 | PASS | correct_supported | covered |  |
| q05 | **FAIL** | wrong_call | covered | verdict wrong_call |
| q06 | PASS | right_call_wrong_support | covered |  |
| q07 | **FAIL** | correct_supported | no_call | assertion exclusion_id_on_denial: expected 'E-10', judge saw None |
| q08 | **FAIL** | correct_supported | other | assertion deductible_conditional: answer states 'deductible is the full $19,000', expected '$1,000' |
| q09 | PASS | correct_supported | other |  |
| q10 | **FAIL** | wrong_call | excluded | verdict wrong_call; assertion exclusion_id_on_denial: expected 'F-3', judge saw 'E-17' |
| q11 | **FAIL** | right_call_wrong_support | no_call | assertion exclusion_id_on_denial: expected 'F-1', judge saw 'E-3' |
| q12 | **FAIL** | wrong_call | other | verdict wrong_call |
| w11_termite_0122 | **FAIL** | no_call | no_call | verdict no_call; assertion exclusion_id_on_denial: expected 'E-15', judge saw None |
