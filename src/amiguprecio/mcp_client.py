"""Cliente real del servidor MCP de AmiguPrecio."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import get_default_environment, stdio_client

from amiguprecio.references import ReferenceSearchResult


def _mcp_server_environment() -> dict[str, str]:
    """Propaga solo la configuración SerpApi necesaria además del entorno MCP seguro."""

    environment = get_default_environment()
    for name in ("SERPAPI_API_KEY", "SERPAPI_SEARCH_ENABLED"):
        value = os.getenv(name)
        if value:
            environment[name] = value
    return environment


async def search_references_mcp(
    query: str,
    max_results: int = 3,
    live: bool = True,
    currency: str | None = None,
    product_name: str | None = None,
    category: str | None = None,
    height_cm: str | None = None,
    use_serpapi: bool | None = None,
    timeout_seconds: float = 15.0,
) -> ReferenceSearchResult:
    """Lanza el servidor stdio, negocia MCP y llama a su herramienta."""

    project_root = Path(__file__).parents[2]
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "amiguprecio.mcp_server"],
        cwd=project_root,
        env=_mcp_server_environment(),
    )

    async def _call() -> ReferenceSearchResult:
        async with (
            stdio_client(params) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            tools = await session.list_tools()
            if not any(tool.name == "search_market_references" for tool in tools.tools):
                raise RuntimeError("El servidor MCP no expone la herramienta esperada")
            arguments: dict[str, object] = {
                "query": query,
                "max_results": min(max_results, 10),
                "live": live,
                "currency": currency,
            }
            optional_arguments = {
                "product_name": product_name,
                "category": category,
                "height_cm": height_cm,
                "use_serpapi": use_serpapi,
            }
            arguments.update(
                {key: value for key, value in optional_arguments.items() if value is not None}
            )
            result = await session.call_tool(
                "search_market_references",
                arguments,
            )
            if result.isError:
                raise RuntimeError("La herramienta MCP devolvió un error")
            payload = result.structuredContent
            if payload and "result" in payload:
                payload = payload["result"]
            if not payload and result.content:
                text = getattr(result.content[0], "text", None)
                if text:
                    payload = json.loads(text)
            if not payload:
                raise RuntimeError("La herramienta MCP no devolvió contenido estructurado")
            return ReferenceSearchResult.model_validate(payload)

    return await asyncio.wait_for(_call(), timeout=timeout_seconds)


def search_references_mcp_sync(
    query: str,
    max_results: int = 3,
    live: bool = True,
    currency: str | None = None,
    product_name: str | None = None,
    category: str | None = None,
    height_cm: str | None = None,
    use_serpapi: bool | None = None,
) -> ReferenceSearchResult:
    return asyncio.run(
        search_references_mcp(
            query,
            max_results=max_results,
            live=live,
            currency=currency,
            product_name=product_name,
            category=category,
            height_cm=height_cm,
            use_serpapi=use_serpapi,
        )
    )
