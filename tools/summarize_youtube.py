"""
MCP Tool: summarize_youtube

이 모듈은 MCP 클라이언트(예: Claude Desktop)가 사용할 수 있는 "요약" 도구를 정의합니다.
핵심 구성 요소는 두 가지입니다:
  1) tool_spec: LLM이 참고하는 도구의 "메뉴판"(이름/설명/입력 스키마)
  2) handle(): LLM이 call_tool로 이 도구를 호출했을 때 실제로 실행되는 비동기 함수

흐름 개요
---------
- LLM은 먼저 서버의 list_tools()를 호출해 사용 가능한 도구 목록(tool_spec 리스트)을 받습니다.
- 사용자의 자연어 요청을 해석한 뒤, 이 도구의 이름과 입력 스키마를 참고해 arguments를 구성합니다.
- 클라이언트는 call_tool(name="summarize_youtube", arguments={...}) 를 보내며, 이때 아래 handle()가 실행됩니다.
- handle()는 URL에서 비디오 ID를 추출하고, 자막을 가져와(full_text), 지정된 길이(max_summary_length)로 요약하여 반환합니다.

주의사항
--------
- youtube-transcript-api 버전에 따라 자막 세그먼트가 dict 또는 FetchedTranscriptSnippet(객체)일 수 있어
  공용 접근 헬퍼를 utils.youtube 내부에서 사용하도록 되어 있습니다.
- inputSchema는 JSON Schema 규격을 따르며, LLM이 올바른 인자를 만들도록 돕기 위해 examples/제약을 적극 활용합니다.
"""

from typing import List, Dict, Any

# MCP 타입: Tool(메타데이터), TextContent(텍스트 응답 콘텐츠)
from mcp.types import Tool, TextContent

# 내부 유틸: URL에서 비디오 ID 추출, 자막을 유연하게 가져오기(언어 후보 순회/객체-딕셔너리 호환)
from utils.youtube import extract_video_id, fetch_transcript_flexible

# 텍스트 유틸: 긴 본문을 단순 휴리스틱(시작/중간/끝)으로 잘라 요약
from utils.text import summarize_sections

# ---------------------------------------------------------------------------
# tool_spec: LLM에 노출되는 도구의 "메뉴판" 정의
# - name: 도구를 호출할 때 사용할 식별자
# - description: 도구의 용도(한 줄 요약)
# - inputSchema: JSON Schema로 입력 파라미터를 명확히 규정
#   * additionalProperties: false => 정의된 키 외의 인자를 거부하여 LLM의 실수를 줄임
#   * examples: LLM에게 올바른 예시를 보여줘 인자 생성 품질을 향상
# ---------------------------------------------------------------------------
tool_spec = Tool(
    name="summarize_youtube",
    description="YouTube 비디오의 자막을 가져와서 요약합니다",
    inputSchema={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            # 분석 대상 비디오 URL
            "url": {
                "type": "string",
                "description": "YouTube 비디오 URL",
                "minLength": 10,  # 매우 짧은 값(예: 빈 문자열) 방지
                "examples": [
                    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                    "https://youtu.be/dQw4w9WgXcQ"
                ]
            },
            # 자막 언어 코드(선택): ko, en, ja, en-US 등
            "language": {
                "type": "string",
                "description": "자막 언어 코드(예: ko, en, ja)",
                "pattern": "^[A-Za-z-]+$",  # 문자와 하이픈만 허용(간단한 밸리데이션)
                "examples": ["ko", "en", "ja", "en-US"]
            },
            # 요약 길이 상한(문자 수). LLM이 너무 긴 요약을 만들지 않도록 가이드
            "max_summary_length": {
                "type": "integer",
                "description": "요약 최대 길이(문자 수). 200~5000 권장",
                "minimum": 200,
                "maximum": 5000,
                "default": 1000
            }
        },
        "required": ["url"],
        "examples": [
            {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "language": "ko", "max_summary_length": 1200}
        ]
    },
)


# ---------------------------------------------------------------------------
# handle(): LLM이 call_tool("summarize_youtube", arguments)로 이 도구를 실행할 때 호출되는 함수
# - 반환은 MCP의 콘텐츠 파트(List[TextContent])
# - 안정성을 위해 입력 정규화/검증 → 자막 fetch → 요약 → 결과 메시지 구성 순서로 처리
# ---------------------------------------------------------------------------
async def handle(arguments: Dict[str, Any]) -> List[TextContent]:
    # 1) 입력 정리 및 검증 -----------------------------------------------------
    # URL은 공백 제거, 언어 코드는 소문자로 통일하여 내부 로직의 분기 케이스를 줄임
    url = (arguments.get("url") or "").strip()
    language = arguments.get("language")
    if isinstance(language, str):
        language = language.strip() or None
        if language:
            language = language.lower()

    # 요약 최대 길이: LLM이 제공하지 않으면 기본 1000자로 사용
    max_len = arguments.get("max_summary_length")
    if not isinstance(max_len, int):
        max_len = 1000
    # 가드레일: 스키마 최소/최대 범위를 코드에서도 한 번 더 보장
    if max_len < 200:
        max_len = 200
    if max_len > 5000:
        max_len = 5000

    # 2) 비디오 ID 추출 --------------------------------------------------------
    # YouTube는 다양한 URL 형태를 가지므로, 헬퍼를 통해 11자 ID를 안전하게 추출
    vid = extract_video_id(url)
    if not vid:
        # LLM/사용자에게 바로 도움이 되는 예시 URL을 함께 제공
        return [TextContent(type="text", text="❌ 올바른 YouTube URL이 아닙니다. 예: https://youtu.be/<VIDEO_ID>")]

    # 3) 자막 가져오기 ----------------------------------------------------------
    # 내부 헬퍼는 언어 후보를 여러 번 시도(지정 언어 → 자동생성 → 다른 후보 → 기본)하고,
    # dict/객체(FetchedTranscriptSnippet) 반환 차이를 흡수하여 full_text를 만들어 줍니다.
    data, lang_used, duration_str, full_text = await fetch_transcript_flexible(vid, language)
    if not data:
        # 사용자가 바로 시도해볼 수 있는 행동 가이드를 함께 전달
        hint = "언어 코드를 바꾸거나(예: ko, en, ja), 자동 생성 자막이 있는지 확인해 보세요."
        return [TextContent(type="text", text=f"❌ 사용 가능한 자막을 찾을 수 없습니다. {hint}")]

    # 4) 요약 생성 --------------------------------------------------------------
    # 길이 한도(max_len)를 넘지 않도록 시작/중간/끝을 추려 붙이는 간단한 방법을 사용
    summary = summarize_sections(full_text, max_length=max_len)

    # 5) 결과 메시지 구성 -------------------------------------------------------
    # LLM/사용자가 후속 조치를 쉽게 하도록, 요약 외에도 기본 통계를 함께 제공
    msg = (
        f"📊 **비디오 정보**\n"
        f"- 비디오 ID: {vid}\n"
        f"- 비디오 길이: {duration_str}\n"
        f"- 사용된 자막: {lang_used}\n"
        f"- 전체 텍스트: {len(full_text):,}자\n"
        f"- 단어 수: {len(full_text.split()):,}개\n"
        f"- 자막 세그먼트: {len(data):,}개\n"
        f"- 요약 길이 한도: {max_len:,}자\n\n"
        f"📝 **자막 요약**\n{summary}\n\n"
        f"💡 **힌트**\n- 더 짧게 원하면 `max_summary_length`를 줄이세요.\n"
        f"- 특정 언어 자막만 원하면 `language`(예: 'ko', 'en-US')를 지정하세요.\n"
    )
    return [TextContent(type="text", text=msg)]