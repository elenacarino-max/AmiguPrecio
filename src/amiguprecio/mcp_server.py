"""Servidor MCP local de referencias comerciales (transporte stdio)."""

from mcp.server.fastmcp import FastMCP

from amiguprecio.references import search_references

mcp = FastMCP("amiguprecio-market", instructions="Devuelve solo precios y fuentes verificables.")


@mcp.tool()
def search_market_references(
    query: str,
    max_results: int = 3,
    live: bool = True,
    currency: str | None = None,
) -> dict:
    """Busca hasta tres referencias de amigurumis y declara su procedencia."""

    result = search_references(
        query=query,
        max_results=max_results,
        live=live,
        currency=currency,
    )
    return result.model_dump(mode="json")


if __name__ == "__main__":
    mcp.run(transport="stdio")
