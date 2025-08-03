from typing import List, Dict, Any
from mcp.types import Tool, TextContent

tool_spec = Tool(
    name="ping",
    description="서버 상태 확인(pong 반환)",
    inputSchema={"type": "object", "properties": {}},
)

async def handle(arguments: Dict[str, Any]) -> List[TextContent]:
    return [TextContent(type="text", text="pong")]