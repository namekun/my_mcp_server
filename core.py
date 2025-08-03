import logging
from typing import List, Dict, Any
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from registry import ToolRegistry
from tools import ALL as TOOL_MODULES

logger = logging.getLogger("mcp.core")

class AppServer:
    """여러 MCP 툴을 한 서버에서 제공하는 코어 서버."""
    def __init__(self) -> None:
        self.server = Server("mcp-multi-tools")
        self.registry = ToolRegistry()
        self._register_tools()

        @self.server.list_tools()
        async def list_tools() -> List[Tool]:
            return self.registry.tools

        @self.server.call_tool()
        async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
            logger.info("call_tool start name=%s", name)
            handler = self.registry.get_handler(name)
            try:
                result = await handler(arguments)
                # 간단한 응답 크기 로깅
                size = 0
                if result and isinstance(result[0], TextContent) and hasattr(result[0], 'text'):
                    size = len(getattr(result[0], 'text', '') or '')
                logger.info("call_tool done name=%s size=%s", name, size)
                return result
            except Exception:
                logger.exception("call_tool error name=%s", name)
                raise

    def _register_tools(self) -> None:
        for mod in TOOL_MODULES:
            self.registry.register(mod.tool_spec, mod.handle)

    async def run(self) -> None:
        async with stdio_server() as (read_stream, write_stream):
            logger.info("MCP server starting")
            await self.server.run(
                read_stream,
                write_stream,
                InitializationOptions(
                    server_name="mcp-multi-tools",
                    server_version="1.0.0",
                    capabilities=self.server.get_capabilities(
                        notification_options=NotificationOptions(),
                        experimental_capabilities={},
                    ),
                ),
            )
            logger.info("MCP server stopped")