# Before / after: one failing call, same prompt

Tool: `search_policy` on **our own** `policy_server.py`. Model: `openai/gpt-oss-20b` via `mcp_agent.py`.
Prompt (identical both runs): *"Search the policy documents, edition 04-24, for what it says about theft of building materials during construction."*
Edition `04-24` doesn't exist (index holds 01-22, 02-23, 03-24). Raw traces: `traces/mcp_error_before.jsonl`, `traces/mcp_error_after.jsonl`.

## Before
Docstring: `"""Search policy documents."""` — error path returns `Error 3`.

| turn | model call | tool result |
|---|---|---|
| 1 | `search_policy(edition='04-24', k=3, query='theft of building materials during construction')` | `Error 3` |
| 2 | same, query shortened | `Error 3` |
| 3 | same, `k` dropped | `Error 3` |
| 4 | same, `k=5` | `Error 3` |

Final answer: *"I'm unable to retrieve the policy text at this time. If you have a copy of the 04-24 edition handy…"* — no policy wording, user is told to go find it. 4 identical-in-substance retries, 2,946 tokens, 3.1 s.

## After
Docstring rewritten as a prompt (when to use, what each arg means and its format, valid editions, "do not repeat the same call"). Error path now returns:
`edition '04-24' not found: this index holds only editions 01-22, 02-23, 03-24 (format MM-YY). Retry with one of these, or omit edition to search all editions.`

| turn | model call | tool result |
|---|---|---|
| 1 | `search_policy(edition='04-24', k=3, query='theft of building materials during construction')` | the recoverable error above |
| 2 | `search_policy(k=3, query='theft of building materials during construction')` — **edition omitted** | `[HO-0304_ed-03-24.pdf, page 2] … E-19 Theft in Course of Construction. We do not cover theft of building materials…` |

Final answer quotes E-19. Recovered on the first retry; 2,837 tokens. Latency was 11.4 s vs 3.1 s, but that is the embedding model cold-loading inside the server on the first successful search, not the recovery itself.

## Caveats (honest)
- n = 1 run per side; the model is sampled (temp 0.4), so this shows the mechanism, not a rate.
- The model dropped the edition instead of asking the user, and its answer labels the wording "HO-0304, all editions" although the retrieved passage is from the 03-24 PDF only. The error message made recovery possible; it did not make the answer's scope claim correct.
- Both versions return the error as ordinary text with MCP `isError: false`. Setting `isError: true` would be the more protocol-correct signal; I left it so the only variable changed is the message and docstring.
