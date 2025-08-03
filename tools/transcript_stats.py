"""
MCP Tool: transcript_stats

이 모듈은 MCP 클라이언트(예: Claude Desktop)가 사용할 수 있는 "자막 통계" 도구를 정의합니다.
핵심 구성 요소는 두 가지입니다:
  1) tool_spec: LLM이 참고하는 도구의 "메뉴판"(이름/설명/입력 스키마)
  2) handle(): LLM이 call_tool로 이 도구를 호출했을 때 실제로 실행되는 비동기 함수

흐름 개요
---------
- LLM은 먼저 서버의 list_tools()로 tool_spec 목록을 조회합니다.
- 사용자의 요청을 보고 이 도구가 적합하다고 판단되면, inputSchema에 맞추어 arguments를 구성한 뒤
  call_tool(name="transcript_stats", arguments={...}) 로 호출합니다.
- handle()는 URL에서 비디오 ID를 추출하고, 자막을 불러와 길이/세그먼트 수 등 통계를 계산하여 반환합니다.

참고
----
- 자막 로딩은 utils.youtube.fetch_transcript_flexible()가 수행합니다.
  이 헬퍼는 언어 후보를 순차적으로 시도하고(dict/객체 반환 차이도 흡수) full_text/길이까지 계산합니다.
"""

from typing import List, Dict, Any

# MCP 표준 타입: Tool(도구 메타데이터), TextContent(텍스트 응답 콘텐츠)
from mcp.types import Tool, TextContent

# 내부 유틸: URL에서 비디오 ID 추출, 자막 유연 로딩/정규화
from utils.youtube import extract_video_id, fetch_transcript_flexible

# ---------------------------------------------------------------------------
# tool_spec: LLM에 노출되는 도구의 "메뉴판" 정의
# - name/description: 도구 선택을 돕는 핵심 정보
# - inputSchema: JSON Schema로 입력 파라미터 규정 (여기서는 간단히 url/language만 사용)
#   * required: ["url"] 로 URL은 반드시 필요함을 명시
#   * 보다 강한 제약/예시가 필요하면 summarize_youtube의 스키마처럼 확장 가능
# ---------------------------------------------------------------------------
tool_spec = Tool(
    name="transcript_stats",
    description="YouTube 자막의 통계 정보만 반환",
    inputSchema={
        "type": "object",
        "properties": {
            "url": {"type": "string"},           # 분석 대상 비디오 URL
            "language": {"type": "string"},      # 선택: 자막 언어 코드(ko, en, ja, en-US 등)
        },
        "required": ["url"],
    },
)


# ---------------------------------------------------------------------------
# handle(): LLM이 call_tool("transcript_stats", arguments)로 이 도구를 실행할 때 호출
# 처리 순서
#  1) 입력 정리 → 2) 비디오 ID 추출 → 3) 자막 로딩 → 4) 통계 메시지 구성
# 반환은 MCP 콘텐츠 파트(List[TextContent]) 형식
# ---------------------------------------------------------------------------
async def handle(arguments: Dict[str, Any]) -> List[TextContent]:
    # 1) 입력 정리 -------------------------------------------------------------
    url = arguments.get("url")
    language = arguments.get("language")

    # 2) 비디오 ID 추출 --------------------------------------------------------
    vid = extract_video_id(url)
    if not vid:
        return [TextContent(type="text", text="❌ 유효한 YouTube URL이 아닙니다.")]

    # 3) 자막 로딩 --------------------------------------------------------------
    # 언어가 지정되면 해당 언어 → 자동생성 후보 → 실패 시 다른 후보/기본 언어 순으로 시도
    data, lang_used, duration_str, full_text = await fetch_transcript_flexible(vid, language)
    if not data:
        return [TextContent(type="text", text="❌ 자막을 찾을 수 없습니다.")]

    # 4) 통계 메시지 구성 -------------------------------------------------------
    # - lang_used: 실제로 선택된 자막 언어(또는 알 수 없음)
    # - len(data): 세그먼트 개수
    # - len(full_text): 전체 텍스트 길이(문자 수)
    # - duration_str: 마지막 세그먼트의 start+duration으로 추정한 길이(분/초)
    msg = (
        f"📊 통계\n"
        f"- 언어: {lang_used or '알 수 없음'}\n"
        f"- 세그먼트: {len(data)}\n"
        f"- 본문 길이: {len(full_text)}자\n"
        f"- 추정 길이: {duration_str}\n"
    )
    return [TextContent(type="text", text=msg)]