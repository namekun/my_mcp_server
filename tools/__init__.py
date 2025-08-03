"""
툴 패키지 초기화 모듈.

- 이 파일은 MCP 서버가 로딩할 "사용 가능한 툴 모듈"들을 한 곳에서 모아 노출합니다.
- `ALL` 리스트에 포함된 모듈들은 `mcp_server.core`에서 자동 등록됩니다.
- 새 툴을 추가하려면 같은 디렉터리에 모듈 파일을 만들고, 아래 ALL에 import + 추가하세요.
"""

from . import summarize_youtube, transcript_stats, ping, commit_suggester

# 서버가 로드할 툴 모듈 목록 (등록 순서가 list_tools 노출 순서가 됩니다)
ALL = [summarize_youtube, transcript_stats, ping, commit_suggester]