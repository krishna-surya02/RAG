"""Policy-document search as an MCP server (stdio). Server one of week 9.

    python policy_server.py          # normally launched by mcp_agent.py via mcp_config.json

One tool, search_policy, over the same retrieval.retrieve() every other script
in this repo uses -- this file adds the MCP framing and nothing else.
"""

from mcp.server.mcpserver import MCPServer

import claims_tools
import retrieval

VALID_EDITIONS = {"01-22", "02-23", "03-24"}

mcp = MCPServer("policy-search")


@mcp.tool()
def search_policy(query: str, edition: str | None = None, k: int = 3) -> str:
    """Find passages in the homeowners policy PDFs (form HO-0304, plus endorsements).
    Use this when you need the actual policy wording -- an exclusion, a sublimit,
    an endorsement buy-back -- rather than guessing it.

    query: plain-English description of the provision, e.g. "theft of building
        materials during construction". Describe the provision, not the claim.
    edition: optional policy edition to restrict results to, MM-YY. Only 01-22,
        02-23 and 03-24 exist. Editions can word the same exclusion differently,
        so pass the claim's edition when you know it; omit it to search all.
    k: how many passages to return (default 3).

    Returns passages, each headed [file, page N]. If the edition is not one we
    hold, the error lists the valid ones: retry with one of them, or omit
    edition. Do not repeat the same call."""
    if edition is not None and edition not in VALID_EDITIONS:
        return (
            f"edition {edition!r} not found: this index holds only editions "
            f"{', '.join(sorted(VALID_EDITIONS))} (format MM-YY). Retry with one "
            "of these, or omit edition to search all editions."
        )
    try:
        hits = retrieval.retrieve(query, k=max(k, 1) * 3 if edition else k)
    except SystemExit as exc:  # retrieve() raises SystemExit on a bad RETRIEVAL_MODE
        return f"retrieval misconfigured: {exc}"
    if edition:
        hits = [h for h in hits if claims_tools.extract_edition(h.source_file) in (None, edition)][:k]
    return retrieval.format_hits(hits) or "no results"


if __name__ == "__main__":
    mcp.run("stdio")
