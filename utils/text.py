"""
텍스트 요약 유틸리티 모듈

긴 텍스트를 읽기 쉽게 요약하는 기능을 제공합니다.
"""

import re

def summarize_sections(text: str, max_length: int = 1000) -> str:
    """
    긴 텍스트를 시작-중간-끝 부분으로 나누어 요약하는 함수
    
    이 함수는 긴 텍스트를 다음과 같은 비율로 나누어 요약합니다:
    - 시작 부분: 40%
    - 중간 부분: 20% 
    - 끝 부분: 40%
    
    매개변수(Parameters):
        text (str): 요약할 원본 텍스트
        max_length (int, optional): 요약된 텍스트의 최대 길이. 기본값은 1000자
    
    반환값(Returns):
        str: 요약된 텍스트. 각 부분이 구분되어 표시됨
    
    작동 방식:
        1. 텍스트가 최대 길이보다 짧으면 그대로 반환
        2. 문장 단위로 분리 (마침표, 느낌표, 물음표 기준)
        3. 시작/중간/끝 부분을 각각 추출
        4. 생략된 부분의 길이를 계산하여 표시
    """
    # 텍스트가 최대 길이보다 짧으면 그대로 반환
    if len(text) <= max_length:
        return text

    # 문장 단위로 분리 (마침표, 느낌표, 물음표 뒤의 공백을 기준으로)
    sentences = re.split(r'(?<=[.!?])\s+', text)
    
    # 시작 부분 추출 (전체 길이의 40%)
    start, start_cap = "", int(max_length * 0.4)
    for s in sentences:
        # 현재 문장을 추가해도 제한을 넘지 않으면 추가
        if len(start) + len(s) < start_cap:
            start += s + " "
        else:
            break
    
    # 중간 부분 추출 (전체 길이의 20%)
    mid, mid_cap = "", int(max_length * 0.2)
    mid_i = len(sentences) // 2  # 전체 문장의 중간 지점
    # 중간 지점 앞뒤 5문장씩 범위에서 추출
    for i in range(max(0, mid_i - 5), min(len(sentences), mid_i + 5)):
        if len(mid) + len(sentences[i]) < mid_cap:
            mid += sentences[i] + " "
    
    # 끝 부분 추출 (전체 길이의 40%)
    end, end_cap = "", int(max_length * 0.4)
    # 뒤에서부터 문장을 추가 (역순으로)
    for s in reversed(sentences):
        if len(end) + len(s) < end_cap:
            end = s + " " + end  # 앞에 추가하여 순서 유지
        else:
            break

    # 생략된 문자 수 계산
    omitted = max(0, len(text) - len(start) - len(mid) - len(end))
    
    # 최종 요약 텍스트 구성
    parts = [
        "**[시작 부분]**",
        start.strip(),
        "",
        f"... *약 {omitted:,}자 생략* ...",  # 천 단위 구분자로 표시
        "",
        "**[중간 부분]**",
        mid.strip(),
        "",
        "... *생략* ...",
        "",
        "**[마지막 부분]**",
        end.strip(),
    ]
    return "\n".join(parts)
