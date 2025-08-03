"""
MCP 서버 코어(core.py)
======================

이 파일은 **여러 MCP 도구(툴)** 를 한 서버에서 제공하기 위한 핵심 로직을 담고 있습니다.
초보자도 흐름을 쉽게 이해할 수 있도록 단계별로 설명을 덧붙였습니다.

전체 흐름 요약
--------------
1) 서버를 만들고(ToolRegistry로 도구 목록을 보관)
2) `list_tools()` 핸들러: 클라이언트(LLM)에게 사용 가능한 도구 "메뉴판"을 제공
3) `call_tool()` 핸들러: 클라이언트가 요청한 도구 이름과 인자를 받아 실제로 실행
4) `run()`: 표준입출력(STDIO)으로 MCP 서버를 구동(IDE/앱이 파이프로 연결)

용어
----
- **MCP**: Model Context Protocol. LLM과 "도구"를 연결해 주는 표준 인터페이스.
- **Tool**: LLM이 호출할 수 있는 기능 단위(예: summarize_youtube, ping 등).
- **ToolRegistry**: 도구 메타데이터와 실행 함수를 이름으로 보관/조회하는 작은 등록소.
"""

import logging
from typing import List, Dict, Any

# MCP SDK (저수준 서버 API). 데코레이터 팩토리(@server.list_tools(), @server.call_tool())를 제공합니다.
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server  # STDIO(표준입출력) 전송을 위한 컨텍스트

# 응답/도구 스키마 타입들
from mcp.types import Tool, TextContent

# 로컬 모듈: 레지스트리(도구 등록/라우팅)와 툴 모듈 목록
from registry import ToolRegistry
from tools import ALL as TOOL_MODULES

# 로거: 이 파일의 실행 단계/에러를 보기 좋게 출력
logger = logging.getLogger("mcp.core")


class AppServer:
    """여러 MCP 툴을 한 서버에서 제공하는 코어 서버.

    생성되면:
      - Server 인스턴스를 만들고
      - ToolRegistry에 툴들을 등록한 뒤
      - list_tools/call_tool 핸들러를 MCP 서버에 연결합니다.
    """

    def __init__(self) -> None:
        # MCP 서버 인스턴스(식별자 문자열은 임의로 정할 수 있음)
        self.server = Server("mcp-multi-tools")

        # 툴 메타데이터/핸들러를 이름으로 보관할 레지스트리
        self.registry = ToolRegistry()

        # tools/__init__.py의 ALL 목록을 순회하며 모든 툴을 한 번에 등록
        self._register_tools()

        # -------------------------------------------------------------
        # 1) list_tools 핸들러: 클라이언트가 "무슨 도구가 있나요?"라고 물을 때 호출됨
        #    반환값은 Tool 객체들의 리스트(= 메뉴판)
        # -------------------------------------------------------------
        @self.server.list_tools()
        async def list_tools() -> List[Tool]:
            return self.registry.tools

        # -------------------------------------------------------------
        # 2) call_tool 핸들러: 클라이언트가 특정 도구를 "이 인자로 실행해줘"라고 할 때 호출됨
        #    name: 문자열(도구 이름), arguments: dict(JSON 인자)
        # -------------------------------------------------------------
        @self.server.call_tool()
        async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
            logger.info("call_tool start name=%s", name)

            # 이름으로 실행 함수를 찾음(등록되지 않았으면 예외)
            handler = self.registry.get_handler(name)
            try:
                # 실제 도구 핸들러 비동기 실행
                result = await handler(arguments)

                # 간단한 진단 로그: 첫 TextContent의 길이를 응답 크기 지표로 사용
                size = 0
                if result and isinstance(result[0], TextContent) and hasattr(result[0], 'text'):
                    size = len(getattr(result[0], 'text', '') or '')
                logger.info("call_tool done name=%s size=%s", name, size)
                return result
            except Exception:
                # 에러 발생 시 스택트레이스를 함께 출력하여 문제 원인을 쉽게 파악
                logger.exception("call_tool error name=%s", name)
                raise

    def _register_tools(self) -> None:
        """툴 모듈들을 레지스트리에 등록합니다.

        tools/__init__.py 의 ALL 리스트에 모든 툴 모듈이 들어있다고 가정합니다.
        각 모듈은 `tool_spec`(메타데이터)와 `handle`(비동기 실행 함수)를 export 합니다.
        """
        for mod in TOOL_MODULES:
            self.registry.register(mod.tool_spec, mod.handle)

    async def run(self) -> None:
        """MCP 서버를 표준입출력(STDIO) 전송으로 실행합니다.

        - `stdio_server()` 컨텍스트는 (읽기 스트림, 쓰기 스트림)을 제공합니다.
        - `InitializationOptions`에는 서버 이름/버전/기능(capabilities)을 선언합니다.
          클라이언트는 이 정보를 바탕으로 서버가 어떤 알림/실험 기능을 지원하는지 인지합니다.
        """
        async with stdio_server() as (read_stream, write_stream):
            logger.info("MCP server starting")

            await self.server.run(
                read_stream,
                write_stream,
                InitializationOptions(
                    server_name="mcp-multi-tools",
                    server_version="1.0.0",
                    # capabilities는 서버가 어떤 기능을 지원하는지 알려주는 선언
                    capabilities=self.server.get_capabilities(
                        notification_options=NotificationOptions(),
                        experimental_capabilities={},
                    ),
                ),
            )

            logger.info("MCP server stopped")