"""Servidor MCP local de referencias comerciales (transporte stdio)."""

from decimal import Decimal, InvalidOperation

from mcp.server.fastmcp import FastMCP

from amiguprecio.references import search_market_candidates, search_references

mcp = FastMCP("amiguprecio-market", instructions="Devuelve solo precios y fuentes verificables.")


@mcp.tool()
def search_market_references(
    query: str,
    max_results: int = 3,
    live: bool = True,
    currency: str | None = None,
    product_name: str | None = None,
    category: str | None = None,
    height_cm: str | None = None,
    use_serpapi: bool | None = None,
) -> dict:
    """Busca candidatos comerciales y declara fuente y alcance de verificación."""

    parsed_height: Decimal | None = None
    if height_cm is not None:
        try:
            parsed_height = Decimal(height_cm)
        except InvalidOperation as exc:
            raise ValueError("height_cm debe ser un decimal válido") from exc
        if not parsed_height.is_finite() or parsed_height <= 0:
            raise ValueError("height_cm debe ser positivo y finito")
    if product_name and category:
        result = search_market_candidates(
            product_name=product_name,
            category=category,
            height_cm=parsed_height,
            currency=currency or "EUR",
            max_results=max_results,
            live=live,
            use_serpapi=use_serpapi,
        )
    else:
        result = search_references(
            query=query,
            max_results=max_results,
            live=live,
            currency=currency,
        )
    return result.model_dump(mode="json")


if __name__ == "__main__":
    mcp.run(transport="stdio")
