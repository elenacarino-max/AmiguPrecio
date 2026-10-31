import asyncio

from amiguprecio.mcp_client import search_references_mcp


def test_stdio_client_connects_and_calls_real_tool() -> None:
    result = asyncio.run(search_references_mcp("amigurumi", live=False))

    assert result.used_fallback is True
    assert len(result.references) == 3
    assert all(reference.provenance == "saved" for reference in result.references)
