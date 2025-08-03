"""
YouTube 자막 추출 유틸리티 모듈

YouTube 비디오에서 자막을 추출하고 처리하는 기능을 제공합니다.
다양한 언어의 자막을 지원하며, 자동 생성 자막도 처리할 수 있습니다.
"""

import logging
import re
from typing import Any, List, Tuple, Optional
from youtube_transcript_api import YouTubeTranscriptApi

# 로깅 설정 (디버깅 및 오류 추적용)
logger = logging.getLogger("mcp.utils.youtube")

def extract_video_id(url: str) -> Optional[str]:
    """
    다양한 형태의 YouTube URL에서 비디오 ID를 추출하는 함수
    
    YouTube 비디오 ID는 11자리 문자열로 구성되며, 다양한 URL 형태에서 추출할 수 있습니다.
    
    매개변수(Parameters):
        url (str): YouTube 비디오 URL
    
    반환값(Returns):
        Optional[str]: 추출된 11자리 비디오 ID, 실패시 None
    
    지원하는 URL 형태:
        - https://www.youtube.com/watch?v=VIDEO_ID
        - https://youtu.be/VIDEO_ID
        - https://www.youtube.com/embed/VIDEO_ID
        - 기타 YouTube URL 변형들
    
    예시:
        extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") 
        # 결과: "dQw4w9WgXcQ"
    """
    # 다양한 YouTube URL 패턴을 정규표현식으로 정의
    patterns = [
        r"(?:v=|/)([0-9A-Za-z_-]{11}).*",    # v= 또는 / 뒤의 11자리
        r"(?:embed/)([0-9A-Za-z_-]{11})",    # embed/ 뒤의 11자리
        r"(?:youtu\\.be/)([0-9A-Za-z_-]{11})", # youtu.be/ 뒤의 11자리
    ]
    
    # 각 패턴을 순서대로 시도
    for p in patterns:
        m = re.search(p, url or "")
        if m:
            return m.group(1)  # 첫 번째 캡처 그룹 (비디오 ID) 반환
    
    return None  # 모든 패턴이 실패하면 None 반환

def _get_field(entry: Any, name: str, default=None):
    """
    자막 데이터에서 필드 값을 안전하게 추출하는 내부 함수
    
    YouTube 자막 API는 때로는 dict를 반환하고, 때로는 객체를 반환합니다.
    이 함수는 두 경우 모두 처리할 수 있도록 합니다.
    
    매개변수(Parameters):
        entry (Any): 자막 데이터 항목 (dict 또는 객체)
        name (str): 추출할 필드명
        default: 필드가 없을 때 반환할 기본값
    
    반환값(Returns):
        Any: 추출된 필드 값 또는 기본값
    
    작동 방식:
        1. dict인 경우: get() 메서드 사용
        2. 객체인 경우: getattr() 사용
        3. 메서드인 경우: 호출하여 결과 반환
        4. 오류 발생시: 기본값 반환
    """
    # dict 타입인 경우
    if isinstance(entry, dict):
        return entry.get(name, default)
    
    # 객체 타입인 경우
    val = getattr(entry, name, default)
    
    # 값이 메서드(callable)인 경우 호출
    if callable(val):
        try:
            return val()
        except Exception:
            return default
    
    return val

async def fetch_transcript_flexible(
    video_id: str, language: Optional[str]
) -> Tuple[List[Any], Optional[str], str, str]:
    """
    YouTube 비디오의 자막을 유연하게 가져오는 메인 함수
    
    여러 언어를 시도하여 자막을 가져오고, 비디오 길이와 전체 텍스트도 함께 계산합니다.
    언어가 지정되지 않으면 한국어 → 영어 → 일본어 순으로 시도합니다.
    
    매개변수(Parameters):
        video_id (str): YouTube 비디오 ID (11자리)
        language (Optional[str]): 원하는 자막 언어 코드 (예: "ko", "en", "ja")
    
    반환값(Returns):
        Tuple[List[Any], Optional[str], str, str]: 
            - transcript_data: 자막 데이터 리스트
            - language_used: 실제 사용된 언어
            - duration_str: 비디오 길이 문자열 (예: "5분 30초")
            - full_text: 전체 자막 텍스트
    
    언어 시도 순서 (language가 None인 경우):
        1. 한국어 (수동 생성)
        2. 한국어 (자동 생성)
        3. 영어 (수동 생성)
        4. 영어 (여러 지역)
        5. 일본어 (수동 생성)
        6. 일본어 (자동 생성)
        7. 기본 언어 (비디오 원본 언어)
    """
    # 초기값 설정
    transcript_data = None
    language_used = None

    def _calc(full: List[Any]) -> tuple[str, str]:
        """
        자막 데이터에서 총 시간과 전체 텍스트를 계산하는 내부 함수
        
        매개변수:
            full: 자막 데이터 리스트
        
        반환값:
            tuple: (시간 문자열, 전체 텍스트)
        """
        # 모든 자막 텍스트 추출
        texts = [str(_get_field(e, "text", "") or "") for e in full]
        full_text = " ".join(texts)
        
        if full:
            # 마지막 자막의 시작 시간과 지속 시간으로 총 길이 계산
            last = full[-1]
            start = _get_field(last, "start", 0) or 0
            dur = _get_field(last, "duration", 0) or 0
            
            # 안전한 형변환
            try: 
                start = float(start)
            except Exception: 
                start = 0.0
            try: 
                dur = float(dur)
            except Exception: 
                dur = 0.0
            
            # 총 시간 = 마지막 자막 시작 시간 + 지속 시간
            total = start + dur
            return f"{int(total // 60)}분 {int(total % 60)}초", full_text
        
        return "알 수 없음", full_text

    try:
        # 특정 언어가 지정된 경우
        if language:
            try:
                # 지정된 언어로 자막 가져오기 시도
                transcript_data = YouTubeTranscriptApi().fetch(video_id, languages=[language])
                language_used = language
            except Exception:
                try:
                    # 자동 생성 자막도 포함하여 재시도
                    transcript_data = YouTubeTranscriptApi().fetch(video_id, languages=[f"{language}-auto", language])
                    language_used = f"{language} (자동 생성)"
                except Exception:
                    transcript_data = None
        else:
            # 언어가 지정되지 않은 경우: 우선순위에 따라 시도
            language_candidates = [
                (["ko"], "한국어"),                    # 한국어 수동 자막
                (["ko-auto"], "한국어 (자동 생성)"),    # 한국어 자동 자막
                (["en"], "영어"),                      # 영어 수동 자막
                (["en-US", "en-GB"], "영어"),          # 영어 (여러 지역)
                (["ja"], "일본어"),                    # 일본어 수동 자막
                (["ja-auto"], "일본어 (자동 생성)"),    # 일본어 자동 자막
            ]
            
            # 각 언어 후보를 순서대로 시도
            for langs, name in language_candidates:
                try:
                    transcript_data = YouTubeTranscriptApi().fetch(video_id, languages=langs)
                    language_used = name
                    break  # 성공하면 루프 종료
                except Exception:
                    continue  # 실패하면 다음 언어 시도
            
            # 모든 언어가 실패한 경우: 기본 언어로 시도
            if not transcript_data:
                try:
                    transcript_data = YouTubeTranscriptApi().fetch(video_id)
                    language_used = "기본 언어"
                except Exception as e:
                    raise Exception(f"사용 가능한 자막을 찾을 수 없습니다: {e}")

        # 자막 데이터가 없으면 빈 결과 반환
        if not transcript_data:
            return [], language_used, "알 수 없음", ""

        # 총 시간과 전체 텍스트 계산
        duration_str, full_text = _calc(transcript_data)
        return transcript_data, language_used, duration_str, full_text

    except Exception:
        # 모든 오류를 로그에 기록
        logger.exception("fetch_transcript_flexible error")
        return [], language_used, "알 수 없음", ""
