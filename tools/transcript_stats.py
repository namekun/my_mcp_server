from typing import List, Dict, Any
from mcp.types import Tool, TextContent
from utils.youtube import extract_video_id, fetch_transcript_flexible

tool_spec = Tool(
    name="transcript_stats",
    description="YouTube 자막의 통계 정보만 반환",
    inputSchema={
        "type": "object",
        "properties": {
            "url": {"type": "string"},
            "language": {"type": "string"},
        },
        "required": ["url"],
    },
)

async def handle(arguments: Dict[str, Any]) -> List[TextContent]:
    url = arguments.get("url")
    language = arguments.get("language")
    vid = extract_video_id(url)
    if not vid:
        return [TextContent(type="text", text="❌ 유효한 YouTube URL이 아닙니다.")]
    data, lang_used, duration_str, full_text = await fetch_transcript_flexible(vid, language)
    if not data:
        return [TextContent(type="text", text="❌ 자막을 찾을 수 없습니다.")]
    msg = (
        f"📊 통계\n"
        f"- 언어: {lang_used or '알 수 없음'}\n"
        f"- 세গ먼트: {len(data)}\n"
        f"- 본문 길이: {len(full_text)}자\n"
        f"- 추정 길이: {duration_str}\n"
    )
    return [TextContent(type="text", text=msg)]