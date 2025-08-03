"""
Tool Registry
=============

이 모듈은 MCP 서버에서 사용할 **툴 메타데이터(Tool)와 실행 핸들러**를
이름으로 매핑/관리하는 아주 단순한 레지스트리 구현을 제공합니다.

왜 필요한가?
------------
- MCP 서버는 여러 개의 도구를 한 프로세스에서 노출할 수 있습니다.
- 서버 코어(`core.py`)는 list_tools()/call_tool() 핸들러를 단 한 번만 정의하고,
  실제 도구 목록과 라우팅은 이 레지스트리에 위임하면 구조가 깔끔해집니다.

설계 요점
---------
- `register(tool, handler)` 로 (이름 → Tool / 이름 → 핸들러) 두 가지 테이블을 동시에 채웁니다.
- `tools` 프로퍼티는 **LLM이 볼 메뉴판**(Tool 객체 리스트)입니다.
- `get_handler(name)` 는 call_tool에서 실행할 **비동기 핸들러**를 반환합니다.
- 이름 중복/미등록 이름에는 명시적인 예외를 던져 초기 설정 오류를 빠르게 드러냅니다.

간단한 사용 예
--------------
>>> registry = ToolRegistry()
>>> registry.register(tool_spec, handle)  # 한 번만 등록
>>> menu = registry.tools                 # list_tools()에서 그대로 반환
>>> handler = registry.get_handler("summarize_youtube")
>>> await handler({"url": "https://youtu.be/..."})
"""

from typing import Dict, Callable, List, Awaitable
from mcp.types import Tool, TextContent

# 비동기 툴 핸들러 시그니처: arguments(dict) → List[TextContent]
# - MCP의 call_tool은 (name, arguments) 형태로 오며, handler는 arguments만 받도록 통일합니다.
ToolHandler = Callable[[dict], Awaitable[List[TextContent]]]


class ToolRegistry:
    """툴 메타데이터와 실행 핸들러를 이름으로 매핑/관리하는 레지스트리.

    Attributes
    ----------
    _tools : Dict[str, Tool]
        도구 이름 → Tool 메타데이터. list_tools() 응답의 근간이 됩니다.
    _handlers : Dict[str, ToolHandler]
        도구 이름 → 비동기 실행 핸들러. call_tool 라우팅에 사용됩니다.
    """

    def __init__(self) -> None:
        # 내부 딕셔너리는 서버 초기화 시 한 번 채워지고, 런타임에는 읽기만 한다고 가정합니다.
        self._tools: Dict[str, Tool] = {}
        self._handlers: Dict[str, ToolHandler] = {}

    def register(self, tool: Tool, handler: ToolHandler) -> None:
        """도구 하나를 레지스트리에 등록합니다.

        Parameters
        ----------
        tool : Tool
            MCP가 이해하는 도구 메타데이터(이름/설명/입력 스키마 포함).
        handler : ToolHandler
            해당 도구를 실제로 실행하는 비동기 함수.

        Raises
        ------
        ValueError
            같은 이름의 도구가 이미 등록되어 있는 경우.
        """
        name = tool.name
        # 개발 시 실수를 빠르게 포착: 같은 이름으로 중복 등록은 금지합니다.
        if name in self._tools:
            raise ValueError(f"Duplicate tool: {name}")

        # 이름을 키로 메타데이터/핸들러를 각각 저장합니다.
        self._tools[name] = tool
        self._handlers[name] = handler

    @property
    def tools(self) -> List[Tool]:
        """등록된 모든 도구의 Tool 메타데이터 리스트를 반환합니다.

        Notes
        -----
        - list_tools() 핸들러에서 그대로 반환하면 LLM이 **메뉴판**으로 사용합니다.
        - dict.values()는 파이썬 3.7+에서 삽입 순서를 보존하므로, 등록 순서가 곧 노출 순서가 됩니다.
        """
        return list(self._tools.values())

    def get_handler(self, name: str) -> ToolHandler:
        """이름에 해당하는 비동기 핸들러를 반환합니다.

        Parameters
        ----------
        name : str
            call_tool로 들어온 도구 이름.

        Returns
        -------
        ToolHandler
            arguments(dict) 하나를 받아 List[TextContent]를 반환하는 비동기 함수.

        Raises
        ------
        ValueError
            미등록 이름이 들어온 경우. 상위 레이어에서 400/사용자 메시지로 변환해도 좋습니다.
        """
        if name not in self._handlers:
            raise ValueError(f"Unknown tool: {name}")
        return self._handlers[name]