"""The integrated triage agent: week 7's hand-built loop, week 9's runtime MCP
discovery, one trace from FNOL in to referral out.

    python triage.py claim CLM-2024-000063          # the entry point wraps this

Loop shape is claim_agent.run_claim's: invoke, dispatch tool calls, append
results, check budgets before every model call. What changed for integration:

  - Tools are four in-process ones (w12/tools_local.py) plus whatever the
    servers in w12/mcp_config.json advertise in tools/list at startup. No MCP
    tool name appears in this file; the prompt describes capabilities.
  - Every model call, tool call and MCP call is a span under one trace id, and
    MCP calls carry _meta.traceparent so the servers' spans join the trace.
  - The run always ends in a referral. If the model stops without calling
    refer_to_adjuster, or a budget trips, the system refers anyway and flags
    why -- week 10's orchestrator invented a "denied" when a worker failed,
    and the fix for that is that there is no path that ends in a decision.
  - The facts in a referral (in force or not, the endorsement set, limits,
    whether each citation was in force) are computed from the policy records
    by code. The model contributes the summary, the clause refs it judged
    relevant and the coverage line -- and the summary goes through w12/guard.
"""

import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

import groq
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.utils.function_calling import convert_to_openai_tool

import claims_common
import config
import mcp_agent
import tracing
from w12 import citations, guard, pii, store, tools_local, trace

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "w12" / "mcp_config.json"
AGENT_MODEL = os.getenv("W12_AGENT_MODEL", claims_common.CLAIMS_CHAT_MODEL)

DEFAULT_BUDGETS = {"max_iterations": 10, "max_tokens": 60000, "max_cost": 0.02, "max_seconds": 240.0}

# Bump the version whenever the prompt text changes; each run records which it used.
# W12_AGENT_PROMPT picks one, so the failure->test loop can show the old prompt
# failing and the new one passing, live, on the same frozen case.
PROMPTS = {
    "triage-agent-v1": """You triage first-notice-of-loss (FNOL) claims for adjusters. You surface facts \
and policy wording; an adjuster makes every coverage decision.

Steps:
1. The redacted FNOL is below ([CLAIMANT_1], [ADDRESS_1]... replace personal details). It gives \
the policy number and loss date; look the policy up separately only if they are missing.
2. Check the policy was in force on the loss date. That check names the endorsement set on the \
term covering the loss date.
3. Not in force: refer straight away with flag NOT_IN_FORCE. Do not search the wording.
4. In force: search the wording for the cover for this kind of loss and any exclusion or \
endorsement bearing on it, passing product, loss_date AND that endorsement_set. Fetch clauses a \
result points to (definitions, carve-backs, deductibles), several refs in one call.
5. Look up deductible, sub-limit and policy limit for the coverage line that carries the clause \
you found.
6. Refer to the adjuster once, last: factual summary, clause refs exactly as returned, coverage \
line, flags.

Rules:
- Never state or imply a coverage decision: no covered / not covered / excluded / denied / \
approved / payable / indemnified / "does not apply" as conclusions. Say what the wording says and \
what the adjuster should check. If the claimant asks whether they are covered, flag \
CLAIMANT_ASKED_FOR_DECISION.
- Cite only wording from the endorsement set the in-force check returned.
- Deductible, sub-limit and policy limit are three different numbers: name each, never add them.
- A clause missing from search results is not evidence about cover; search again or fetch it.
- Call independent tools in the same turn. Older search results are cut to their refs; fetch a \
clause again if you need its text.""",
}
# v2 (failure->test loop, baseline cases w12-01..07): 6 of 7 baseline summaries
# stated a decision -- the model paraphrased wording into conclusions ("is
# indemnified", "excludes inundation, which does not apply here"). v2 makes the
# summary quote and ask instead of conclude, and ties the coverage line to the
# clause (w12-02 put a rainfall flood on escape_of_water).
PROMPTS["triage-agent-v2"] = PROMPTS["triage-agent-v1"] + """
- Write the summary in three parts. FACTS: what happened, the loss date, in force or not, the \
endorsement set. WORDING TO CHECK: for each cited clause, its ref and its operative words quoted \
in double quotes -- quote, do not paraphrase into a result, and never say how a clause applies \
to this loss. FOR THE ADJUSTER: the facts the adjuster must confirm (e.g. "confirm the home is \
not in a declared flood zone", "confirm the water came from the river, not rainfall").
- Choose the coverage line whose limits row names, in its source, the clause the loss turns on. \
A flood or surface-water loss is never escape_of_water or buildings."""
DEFAULT_PROMPT = "triage-agent-v2"


def prompt_version():
    v = os.getenv("W12_AGENT_PROMPT", DEFAULT_PROMPT)
    if v not in PROMPTS:
        raise SystemExit(f"W12_AGENT_PROMPT={v!r}; choose one of {sorted(PROMPTS)}")
    return v


def server_config(path=CONFIG_PATH):
    """mcp_config.json with ${PYTHON}/${ROOT} filled in and the trace dir passed
    down -- an MCP subprocess gets a minimal environment, not ours."""
    servers = json.loads(Path(path).read_text(encoding="utf-8"))["servers"]
    env = {"W12_TRACE_DIR": str(trace.trace_dir()), "TRANSFORMERS_VERBOSITY": "error"}
    if config._embedder_is_cached():
        env["HF_HUB_OFFLINE"] = "1"
    out = {}
    for name, spec in servers.items():
        sub = lambda s: s.replace("${PYTHON}", sys.executable).replace("${ROOT}", str(ROOT))
        out[name] = {"command": sub(spec["command"]), "args": [sub(a) for a in spec.get("args", [])],
                     "env": {**env, **spec.get("env", {})}}
    return out


class TracedServers(mcp_agent.Servers):
    """week 9's Servers, plus _meta on every call so the trace crosses the hop."""

    async def call(self, name, args, meta=None):
        if name not in self.owner:
            return "unknown", f"unknown tool {name!r}", True
        server, session = self.owner[name]
        result = await session.call_tool(name, args, meta=meta)
        text = "\n".join(c.text for c in result.content if getattr(c, "type", "") == "text")
        return server, text, bool(result.is_error)


_LIMITER = claims_common.RateLimiter(tpm=8000, margin=0.8)


def _head(text, n=1500):
    text = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False)
    return text if len(text) <= n else text[:n] + "…"


def compact_history(messages, keep_from):
    """Shorten wording-search results from earlier turns to their refs.

    Every turn re-sends the whole conversation, so a 1k-token search result
    from turn 2 is paid for again on turns 3, 4 and 5 -- in the first live run
    that was most of the 26k tokens one claim cost, against a 200k/day quota.
    The model saw the full text when it mattered; after that it needs the refs
    to cite and get_clause to re-read. Messages before index keep_from only.
    """
    for i, m in enumerate(messages[:keep_from]):
        if not isinstance(m, ToolMessage) or m.additional_kwargs.get("compacted"):
            continue
        try:
            body = json.loads(m.content)
        except (TypeError, ValueError):
            continue
        if isinstance(body, dict) and "hits" in body and "resolution" in body:
            short = {"resolution": {k: body["resolution"].get(k) for k in ("endorsement_set", "resolved_by", "loss_date")},
                     "hits": [{"ref": h["ref"], "title": h["title"]} for h in body["hits"]],
                     "note": "text omitted from history; call get_clause for a clause's full text"}
            messages[i] = ToolMessage(content=json.dumps(short, ensure_ascii=False), tool_call_id=m.tool_call_id,
                                      additional_kwargs={"compacted": True})


def _fnol_text_only(fnol_json):
    """The redacted FNOL as the model saw it, kept so the taxonomy can tell what
    redaction removed at run time (redact.py changes between runs)."""
    try:
        return json.loads(fnol_json).get("fnol_text")
    except (TypeError, ValueError):
        return None


def build_referral(claim, args, tracer, system_flags):
    """The referral an adjuster receives. Facts from records, judgement from the model."""
    product, loss_date, policy_number = claim["product"], claim["loss_date"], claim["policy_number"]
    facts = store.in_force(policy_number, loss_date)
    eset = facts.get("endorsement_set")
    refs = list(dict.fromkeys((args or {}).get("citations") or []))
    resolved_by = "policy_term" if eset else "calendar_date"
    cits = [citations.resolve(r, product, loss_date, eset or store.set_by_calendar(product, loss_date), resolved_by)
            for r in refs]
    coverage = (args or {}).get("coverage")
    lim = store.limits(product, eset, coverage) if (eset and coverage) else None
    summary, found = guard.enforce((args or {}).get("summary") or "")
    flags = list(dict.fromkeys(((args or {}).get("flags") or []) + system_flags))
    if found:
        flags.append("DECISION_LANGUAGE_WITHHELD")
    if any(not c.get("valid") for c in cits):
        flags.append("INVALID_CITATION")
    if coverage and eset and lim is None:
        flags.append("COVERAGE_LINE_UNKNOWN")
    if not facts.get("in_force") and "NOT_IN_FORCE" not in flags:
        flags.append("NOT_IN_FORCE")
    return {
        "referral_id": tracer.trace_id,
        "claim_id": claim["claim_id"],
        "policy_number": policy_number,
        "product": product,
        "loss_date": loss_date,
        "decision": "for the adjuster -- this referral states no coverage decision",
        "in_force": facts.get("in_force"),
        "term": facts.get("term"),
        "endorsement_set": eset,
        "endorsement_set_version": facts.get("endorsement_set_version"),
        "summary": summary,
        "citations": cits,
        "citations_all_valid": all(c.get("valid") for c in cits) if cits else None,
        "coverage": coverage,
        "limits": None if lim is None else {k: lim[k] for k in ("deductible", "sub_limit", "policy_limit", "source")},
        "flags": flags,
        "guard": {"tripped": bool(found), "found": found},
    }


async def triage(claim_id, *, trace_id=None, budgets=None, model=AGENT_MODEL, config_path=CONFIG_PATH,
                 verbose=False, limiter=_LIMITER):
    """Triage one claim. Returns the run record (referral included)."""
    budgets = {**DEFAULT_BUDGETS, **(budgets or {})}
    log = print if verbose else (lambda *a, **k: None)
    claim = store.claim(claim_id)
    if claim is None:
        raise SystemExit(f"no claim {claim_id!r} under data/claims")
    tracer = trace.Tracer(trace_id=trace_id, pii_values=pii.holder_values(claim["policy_number"]))
    tool_calls, referral_args, status, system_flags, model_errors = [], None, None, [], []
    fnol_text = None
    t0 = time.perf_counter()
    waited = 0.0

    pv = prompt_version()
    with tracer.span("triage", "run", claim_id=claim["claim_id"], model=model, prompt_version=pv) as root:
        with tracer.span("mcp_connect", "mcp_client") as sp:
            servers = TracedServers(server_config(config_path))
            await servers.__aenter__()
            sp["attrs"]["discovered"] = [{"server": t["server"], "tool": t["tool"].name} for t in servers.tools]
        try:
            local = [convert_to_openai_tool(t) for t in tools_local.TOOLS]
            llm = config.get_llm(model=model).bind_tools(local + servers.model_tools())
            log(f"trace {tracer.trace_id} | tools: {[t.name for t in tools_local.TOOLS]} local + "
                f"{[t['tool'].name for t in servers.tools]} discovered over MCP")
            # FNOL in: the claim file arrives through the claims-files server,
            # redacted there, before any model sees it.
            fnol_tool = next((t["tool"].name for t in servers.tools if t["tool"].name == "get_fnol"), None)
            with tracer.span("ingress:get_fnol", "mcp_client") as sp:
                meta = {"traceparent": trace.traceparent(tracer.trace_id, sp["span_id"])}
                _, fnol_text, fnol_err = await servers.call(fnol_tool, {"claim_id": claim["claim_id"]}, meta=meta) \
                    if fnol_tool else ("none", "claims-files server not configured", True)
                sp["status"] = "error" if fnol_err else "ok"
            messages = [SystemMessage(content=PROMPTS[pv]),
                        HumanMessage(content=f"Triage FNOL claim {claim['claim_id']}.\n\nFNOL:\n{fnol_text}")]
            tokens = cost = 0
            turn = 0
            next_estimate = 3000
            for turn in range(1, budgets["max_iterations"] + 1):
                elapsed = time.perf_counter() - t0 - waited
                breach = ("max_seconds" if elapsed > budgets["max_seconds"] else
                          "max_tokens" if tokens >= budgets["max_tokens"] else
                          "max_cost" if cost >= budgets["max_cost"] else None)
                if breach:
                    status = f"budget_exceeded:{breach}"
                    break
                compact_history(messages, keep_from=len(messages) - last_batch if turn > 1 else 0)
                if limiter:
                    w0 = time.perf_counter()
                    limiter.wait_for_budget(next_estimate)
                    waited += time.perf_counter() - w0
                try:
                    with tracer.span(f"llm_turn_{turn}", "llm") as sp:
                        sp["model"] = model
                        # Sync client in a thread, not ainvoke: each claim runs in
                        # its own asyncio.run, and ChatGroq's async httpx clients
                        # outlived their loops ("Event loop is closed" on cleanup).
                        response = await asyncio.to_thread(llm.invoke, messages)
                        p, c = claims_common.usage_of(response)
                        sp["prompt_tokens"], sp["completion_tokens"] = p, c
                        sp["attrs"]["tool_calls"] = [tc["name"] for tc in response.tool_calls]
                except groq.RateLimitError as exc:
                    # Still a referral: a quota error mid-claim must not leave a
                    # claim with no human assigned. The status tells the eval
                    # runner not to count this case as run.
                    model_errors.append(f"RateLimitError: {str(exc)[:200]}")
                    daily = bool(re.search(r"per day|TPD|RPD", str(exc)))
                    status = "rate_limited:daily" if daily else "rate_limited:minute"
                    break
                except groq.APIError as exc:
                    # Baseline case w12-08: gpt-oss emitted the tool name
                    # "refer_to_adjuster<|channel|>commentary", Groq answered 400
                    # tool_use_failed, and the exception killed the run with no
                    # referral. A malformed generation is resampled; anything else,
                    # or a third failure, ends the run -- and it is still referred.
                    model_errors.append(f"{type(exc).__name__}: {str(exc)[:200]}")
                    if "tool_use_failed" in str(exc) and len(model_errors) <= 2:
                        continue
                    status = "model_error"
                    break
                tokens += p + c
                cost += tracing.cost_usd(p, c, model)
                next_estimate = p + c + 800
                if limiter:
                    limiter.record(p + c)
                messages.append(response)
                last_batch = len(response.tool_calls)
                if not response.tool_calls:
                    status = "ended_without_referral"
                    system_flags.append("NO_AGENT_REFERRAL")
                    break
                for tc in response.tool_calls:
                    name, args = tc["name"], tc["args"]
                    if name in tools_local.TOOLS_BY_NAME:
                        with tracer.span(f"tool:{name}", "tool", args=args) as sp:
                            if name == tools_local.TERMINAL:
                                result = {"referred": True}
                                referral_args = args
                            else:
                                result = tools_local.TOOLS_BY_NAME[name].invoke(args)
                            sp["status"] = "error" if isinstance(result, dict) and "error" in result else "ok"
                        server, text, is_error = "local", json.dumps(result, ensure_ascii=False), sp["status"] == "error"
                    else:
                        with tracer.span(f"mcp:{name}", "mcp_client", args=args) as sp:
                            meta = {"traceparent": trace.traceparent(tracer.trace_id, sp["span_id"])}
                            server, text, is_error = await servers.call(name, args, meta=meta)
                            sp["attrs"]["server"] = server
                            sp["status"] = "error" if is_error else "ok"
                    log(f"[turn {turn}] {server}.{name}({json.dumps(args, ensure_ascii=False)[:160]}) -> {text[:160]}")
                    tool_calls.append({"turn": turn, "server": server, "name": name, "args": args,
                                       "result": _head(text), "is_error": is_error, "span_id": sp["span_id"]})
                    messages.append(ToolMessage(content=text, tool_call_id=tc["id"]))
                if referral_args is not None:
                    status = "ok"
                    break
            if status is None:
                status = "budget_exceeded:max_iterations"
        finally:
            await servers.__aexit__(None, None, None)

        if status != "ok":
            system_flags.append(status.upper().replace(":", "_"))
        if not any(tc["name"] == "check_in_force" for tc in tool_calls):
            system_flags.append("IN_FORCE_NOT_CHECKED_BY_AGENT")
        with tracer.span("refer_to_adjuster", "referral") as sp:
            referral = build_referral(claim, referral_args, tracer, system_flags)
            sp["attrs"].update(flags=referral["flags"], citations=[c["ref"] for c in referral["citations"]],
                               guard_tripped=referral["guard"]["tripped"])
        root["attrs"]["status"] = status

    record = {
        "trace_id": tracer.trace_id,
        "ts": tracing.now_utc(),
        "app": tracing.app_version(),
        "claim_id": claim["claim_id"],
        "status": status,
        "model": model,
        "prompt_version": pv,
        "budgets": budgets,
        "turns": turn,
        "tools_discovered": [t["tool"].name for t in servers.tools],
        "tool_calls": tool_calls,
        "agent_flags": list((referral_args or {}).get("flags") or []),
        "fnol_redacted": _fnol_text_only(fnol_text),
        "model_errors": model_errors,
        "latency_ms": round((time.perf_counter() - t0 - waited) * 1000, 1),
        "rate_limit_wait_ms": round(waited * 1000, 1),
        **tracer.totals(),
        "referral": referral,
    }
    trace.append(trace.runs_path(), record, tracer.pii_values)
    ref_dir = trace.trace_dir() / "referrals"
    trace.append(ref_dir / f"{tracer.trace_id}.json", referral, tracer.pii_values)
    record["guard_caught"] = tracer.guard_caught
    return record


def render_referral(rec):
    r = rec["referral"]
    lines = [f"REFERRAL {r['referral_id']}  claim {r['claim_id']}  policy {r['policy_number']} ({r['product']})",
             f"  decision     : {r['decision']}",
             f"  loss date    : {r['loss_date']}",
             f"  in force     : {r['in_force']}" + (f"  term {r['term']['start']} → {r['term']['end']}" if r.get("term") else ""),
             f"  wording      : {r['endorsement_set']} {r['endorsement_set_version'] or ''}".rstrip()]
    if r["limits"]:
        L = r["limits"]
        lines.append(f"  coverage     : {r['coverage']}")
        lines.append(f"  deductible   : ${L['deductible']:,}")
        lines.append(f"  sub-limit    : {'$' + format(L['sub_limit'], ',') if L['sub_limit'] is not None else 'none'}")
        lines.append(f"  policy limit : ${L['policy_limit']:,}   ({L['source']})")
    lines.append(f"  flags        : {', '.join(r['flags']) or '-'}")
    lines.append("  citations    :")
    lines += [f"    - {citations.render(c)}" for c in r["citations"]] or ["    (none)"]
    lines.append("  summary      :")
    lines.append("    " + (r["summary"] or "(none)").replace("\n", "\n    "))
    lines.append(f"  run          : status={rec['status']} turns={rec['turns']} tokens={rec['prompt_tokens']}+"
                 f"{rec['completion_tokens']} cost=${rec['cost_usd']:.6f} latency={rec['latency_ms'] / 1000:.1f}s "
                 f"(+{rec['rate_limit_wait_ms'] / 1000:.1f}s rate-limit wait)")
    return "\n".join(lines)


def run(claim_id, **kw):
    return asyncio.run(triage(claim_id, **kw))
