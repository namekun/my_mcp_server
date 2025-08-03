"""
MCP Tool: ping

가장 단순한 MCP 도구 예시입니다. 클라이언트(LLM)가 서버 상태를 확인(health check)
하거나 입출력 경로가 제대로 연결됐는지 점검할 때 사용합니다.

구성 요소
--------
1) tool_spec  : LLM이 참고하는 도구의 메타데이터(이름/설명/입력 스키마)
2) handle()   : LLM이 call_tool("ping")을 호출했을 때 실행되는 비동기 함수

동작
----
- 입력 파라미터는 필요하지 않습니다(빈 object).  
- 호출되면 항상 "pong" 문자열을 TextContent로 반환합니다.

테스트 팁
--------
- 이 도구가 정상 동작하면 MCP 클라이언트 ↔ 서버 간 STDIO 경로가 살아있다는 뜻입니다.
- list_tools → call_tool("ping") 흐름이 잘 되는지 빠르게 확인할 때 유용합니다.
"""

from typing import List, Dict, Any
from mcp.types import Tool, TextContent


# ---------------------------------------------------------------------------
# tool_spec: 도구 메타데이터(메뉴판)
# - name/description: LLM이 도구를 고를 때 참고
# - inputSchema: 빈 object (추가 속성 없음)
# ---------------------------------------------------------------------------
tool_spec = Tool(
    name="ping",
    description="서버 상태 확인(pong 반환)",
    inputSchema={
        "type": "object",
        "additionalProperties": False,
        "properties": {}
    },
)

# ---------------------------------------------------------------------------
# handle(): call_tool("ping", arguments) 시 실행되는 비동기 핸들러
# - 반환은 MCP 표준 콘텐츠 파트(List[TextContent])
# ---------------------------------------------------------------------------
async def handle(arguments: Dict[str, Any]) -> List[TextContent]:
    # 인자를 사용하지 않지만, 인터페이스 일관성을 위해 arguments를 받습니다.
    return [TextContent(type="text", text="pong")]