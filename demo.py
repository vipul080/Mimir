"""End-to-end demo: talks to the Mimir MCP server over the real MCP protocol
and walks through fixing the bug in demo_shop, the way an AI agent would.

Runs on a fresh copy of demo_shop, so it can be repeated.
    python demo.py
"""
import asyncio
import shutil
import sys
import tempfile
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HERE = Path(__file__).parent


def banner(step: str):
    print(f"\n{'=' * 70}\n>>> {step}\n{'=' * 70}")


async def main():
    work = Path(tempfile.mkdtemp(prefix="mimir-demo-")) / "demo_shop"
    shutil.copytree(HERE / "demo_shop", work)
    params = StdioServerParameters(command=sys.executable, args=["-m", "mimir.server", str(work)], cwd=str(HERE))

    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        await s.initialize()

        async def call(tool, **args):
            res = await s.call_tool(tool, args)
            text = "\n".join(c.text for c in res.content if hasattr(c, "text"))
            print(text)
            return text

        tools = await s.list_tools()
        banner(f"Server offers {len(tools.tools)} tools: " + ", ".join(t.name for t in tools.tools))

        banner("1. repo_map(): what does this project look like?")
        await call("repo_map")

        banner("2. check(): is anything broken?")
        await call("check")

        banner("3. get_symbol('apply_discount'): read only the suspect function")
        await call("get_symbol", name="apply_discount")

        banner("4. who_calls('apply_discount'): who depends on it?")
        await call("who_calls", name="apply_discount")

        banner("5. checkpoint(): save before editing")
        await call("checkpoint", label="before discount fix")

        banner("6. replace_symbol with broken syntax: refused, nothing written")
        await call("replace_symbol", name="apply_discount",
                   new_source="def apply_discount(price, percent)\n    return price")

        banner("7. replace_symbol with a wrong fix: written, tests catch it")
        await call("replace_symbol", name="apply_discount",
                   new_source="def apply_discount(price: float, percent: float) -> float:\n"
                              "    return price * percent / 100\n")

        banner("8. restore(): roll back the wrong fix")
        await call("restore", checkpoint_id="001-before-discount-fix")

        banner("9. replace_symbol with the right fix")
        await call("replace_symbol", name="apply_discount",
                   new_source='def apply_discount(price: float, percent: float) -> float:\n'
                              '    """Return the price after a percentage discount (percent is 0-100)."""\n'
                              '    return price - price * percent / 100\n')

        banner("10. diff_since(): what changed overall?")
        await call("diff_since", checkpoint_id="001-before-discount-fix")

        banner("Token cost: whole file vs outline vs one symbol")
        whole = (work / "shop" / "cart.py").read_text()
        outline = (await s.call_tool("outline", {"file": "shop/cart.py"})).content[0].text
        sym = (await s.call_tool("get_symbol", {"name": "Cart.total"})).content[0].text
        print(f"read whole cart.py: {len(whole)} chars | outline: {len(outline)} | get_symbol('Cart.total'): {len(sym)}")

    print(f"\nActivity log for the dashboard: {work / '.mimir' / 'activity.jsonl'}")


if __name__ == "__main__":
    asyncio.run(main())
