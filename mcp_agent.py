"""A tool-calling agent whose tools all come from MCP servers named in a config file.

    python mcp_agent.py --list                       # raw tools/list from every configured server
    python mcp_agent.py "your question here"         # run the agent
    python mcp_agent.py --config other.json "..."

Nothing in this file knows what any server or tool is called. Servers come from
mcp_config.json; tools come from each server's tools/list at startup; a model
tool call is routed to whichever server advertised that name. Adding a server
is therefore a config edit, not a code change -- week 9's whole point.

Same Groq model and budget idea as claim_agent.py, same trace writer.
"""

import argparse
import asyncio
import json
import time
from contextlib import AsyncExitStack
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from mcp import ClientSession, StdioServerParameters, stdio_client

import claims_common
import config

CONFIG_PATH = "mcp_config.json"
TRACE_PATH = "traces/mcp_agent_traces.jsonl"

SYSTEM_PROMPT = (
    "You are an insurance-claims assistant. Use the tools provided when they help "
    "answer the question, and answer concisely from what they return."
)

DEFAULT_MAX_ITERATIONS = 6
DEFAULT_MAX_TOKENS = 8000
DEFAULT_MAX_SECONDS = 60.0


def load_config(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))["servers"]


class Servers:
    """Spawns every configured server, keeps their sessions open, and remembers
    which server owns which tool."""

    def __init__(self, servers_cfg):
        self.cfg = servers_cfg
        self.stack = AsyncExitStack()
        self.owner = {}  # tool name -> (server name, session)
        self.tools = []  # raw tools/list entries, tagged with their server

    async def __aenter__(self):
        await self.stack.__aenter__()
        for name, spec in self.cfg.items():
            params = StdioServerParameters(
                command=spec["command"], args=spec.get("args", []), env=spec.get("env")
            )
            read, write = await self.stack.enter_async_context(stdio_client(params))
            session = await self.stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            listed = await session.list_tools()
            for tool in listed.tools:
                if tool.name in self.owner:
                    raise RuntimeError(
                        f"tool name {tool.name!r} is advertised by both "
                        f"{self.owner[tool.name][0]!r} and {name!r}"
                    )
                self.owner[tool.name] = (name, session)
                self.tools.append({"server": name, "tool": tool})
        return self

    async def __aexit__(self, *exc):
        return await self.stack.__aexit__(*exc)

    def model_tools(self):
        return [
            {
                "type": "function",
                "function": {
                    "name": t["tool"].name,
                    "description": t["tool"].description or "",
                    "parameters": t["tool"].input_schema,
                },
            }
            for t in self.tools
        ]

    async def call(self, name, args):
        if name not in self.owner:
            return "unknown", f"unknown tool {name!r}", True
        server, session = self.owner[name]
        result = await session.call_tool(name, args)
        text = "\n".join(c.text for c in result.content if getattr(c, "type", "") == "text")
        return server, text, bool(result.is_error)


def tools_listing(servers):
    return {
        "count": len(servers.tools),
        "tools": [
            {"server": t["server"], "name": t["tool"].name} for t in servers.tools
        ],
    }


async def run(question, servers_cfg, max_iterations, max_tokens, max_seconds, trace_path, verbose):
    def log(msg):
        if verbose:
            print(msg)

    async with Servers(servers_cfg) as servers:
        llm = config.get_llm(model=claims_common.CLAIMS_CHAT_MODEL).bind_tools(servers.model_tools())
        messages = [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=question)]
        start = time.perf_counter()
        tokens_used = 0
        calls = []
        answer, status = None, "budget_exceeded"

        for turn in range(1, max_iterations + 1):
            if time.perf_counter() - start > max_seconds or tokens_used >= max_tokens:
                break
            response = llm.invoke(messages)
            p, c = claims_common.usage_of(response)
            tokens_used += p + c
            messages.append(response)
            if not response.tool_calls:
                answer, status = response.content, "ok"
                break
            for tc in response.tool_calls:
                server, text, is_error = await servers.call(tc["name"], tc["args"])
                log(f"[turn {turn}] {server}.{tc['name']}({tc['args']}) -> {text[:300]}")
                calls.append(
                    {"turn": turn, "server": server, "name": tc["name"], "args": tc["args"],
                     "result": text, "is_error": is_error}
                )
                messages.append(ToolMessage(content=text, tool_call_id=tc["id"]))

        claims_common.write_claim_trace(
            trace_path, "mcp_agent", None,
            {
                "input": {"question": question},
                "servers": list(servers_cfg),
                "tools_discovered": [t["tool"].name for t in servers.tools],
                "tokens_used": tokens_used,
                "latency_ms": round((time.perf_counter() - start) * 1000, 1),
                "tool_calls": calls,
                "status": status,
                "output": answer,
            },
        )
        return answer, calls


async def list_only(servers_cfg):
    async with Servers(servers_cfg) as servers:
        listing = tools_listing(servers)
        listing["raw"] = [
            {"server": t["server"], **t["tool"].model_dump(by_alias=True, exclude_none=True)}
            for t in servers.tools
        ]
        return listing


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", nargs="?")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--config", default=CONFIG_PATH)
    parser.add_argument("--max-iterations", type=int, default=DEFAULT_MAX_ITERATIONS)
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument("--max-seconds", type=float, default=DEFAULT_MAX_SECONDS)
    parser.add_argument("--trace-path", default=TRACE_PATH)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    servers_cfg = load_config(args.config)

    if args.list:
        print(json.dumps(asyncio.run(list_only(servers_cfg)), indent=2))
        return
    if not args.question:
        parser.error("give a question, or --list")
    config.preflight()
    answer, _ = asyncio.run(
        run(args.question, servers_cfg, args.max_iterations, args.max_tokens,
            args.max_seconds, args.trace_path, not args.quiet)
    )
    print(answer)


if __name__ == "__main__":
    main()
