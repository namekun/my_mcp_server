#!/usr/bin/env python3
"""
엔트리포인트(server.py)
=======================

이 파일은 MCP 서버를 **실행**하는 가장 바깥쪽 진입점입니다.
가능한 한 얇게 유지해서, 실제 서버 로직은 `core.py`(또는 패키지 내부 `mcp_server/core.py`)에서 관리하고
여기서는 실행, 로깅, 예외 처리만 담당합니다.

전체 흐름
--------
1) 로깅 설정: 환경변수 `LOG_LEVEL` 로 로그 레벨을 제어합니다.
2) `AppServer` 생성: 내부에서 도구(툴) 등록과 핸들러(list_tools/call_tool) 연결을 마칩니다.
3) `app.run()` 호출: 표준입출력(STDIO) 기반 MCP 서버를 구동합니다.
4) 예외 처리: 키보드 인터럽트/일반 예외를 잡아 사용자 친화적으로 종료 로그를 남깁니다.

팁
--
- 개발 중에는 `LOG_LEVEL=DEBUG python server.py` 로 상세 로그를 보면서 동작을 확인하세요.
- `from core import AppServer` 경로는 프로젝트 구조에 따라 달라질 수 있습니다.
  (예: 패키지 형태라면 `from mcp_server.core import AppServer`를 사용할 수 있습니다.)
"""

import asyncio
import logging
import os
import sys

# 서버 코어: 실제 MCP 서버 로직(도구 등록, 핸들러, 실행)을 캡슐화
from core import AppServer

# ---------------------------------------------------------------------------
# 로깅 설정
# - 기본 레벨은 INFO, 환경변수 LOG_LEVEL 로 덮어쓸 수 있습니다.
# - 포맷은 [시간 레벨 로거이름 메시지] 형태로 단순하게 지정했습니다.
# ---------------------------------------------------------------------------
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("mcp.entry")  # 엔트리포인트 전용 로거 이름


async def main():
    """메인 비동기 함수: 서버를 생성하고 실행(run)합니다."""
    # AppServer 안에서 MCP 서버 인스턴스 생성, 툴 레지스트리 등록,
    # list_tools/call_tool 핸들러 연결까지 모두 처리됩니다.
    app = AppServer()
    await app.run()


if __name__ == "__main__":
    # asyncio.run 으로 이벤트 루프를 열고 main()을 실행합니다.
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # 사용자가 Ctrl+C 등으로 종료한 경우 친절한 로그만 남기고 끝냅니다.
        logger.info("Stopped by user")
    except Exception:
        # 예기치 못한 예외는 스택트레이스까지 남겨 디버깅에 도움을 줍니다.
        logger.exception("Server error")
        sys.exit(1)