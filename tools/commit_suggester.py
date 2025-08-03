"""
MCP Tool: commit_suggester

🤖 **Git 커밋 메시지 자동 생성 도구**

이 모듈은 Git의 변경 사항을 분석해서 적절한 커밋 메시지를 자동으로 제안해주는 도구입니다.
프로그래밍 초보자도 쉽게 이해할 수 있도록 상세한 주석과 함께 작성되었습니다.

📋 **주요 기능:**
1. **자동 타입 추정**: 변경된 파일을 보고 feat, fix, docs 등 커밋 타입을 자동으로 판단
2. **스코프 추정**: 프로젝트 구조를 분석해서 적절한 스코프(모듈명) 제안
3. **다국어 지원**: 한국어/영어 커밋 메시지 생성
4. **사용자 정의 포맷**: 원하는 커밋 메시지 형식으로 커스터마이징 가능
5. **브랜치명 활용**: 브랜치 이름에서 추가 정보 추출
6. **안전한 실행**: 다양한 에러 상황에 대한 체크와 해결 가이드 제공

🎯 **동작 원리:**
1. Git 환경 확인 (git 설치, repository 존재 여부)
2. 변경된 파일 목록 수집 (staged/working/range 모드)
3. 파일 경로와 이름 분석으로 커밋 타입 추정
4. 프로젝트 구조에서 스코프 추정
5. 브랜치명에서 추가 정보 추출
6. 여러 커밋 메시지 후보 생성

🔧 **사용자 정의 포맷 지원:**
템플릿 변수를 사용해 원하는 형식으로 커밋 메시지를 만들 수 있습니다.

지원하는 템플릿 변수:
- {type}: 추정된 커밋 타입 (feat, fix, docs 등)
- {scope}: 추정된 스코프 (모듈/컴포넌트명)
- {subject}: 생성된 제목
- {emoji}: 타입별 이모지 (✨, 🐛, 📝 등)
- {files_changed}: 총 변경된 파일 수
- {files_added}: 추가된 파일 수
- {files_modified}: 수정된 파일 수
- {files_deleted}: 삭제된 파일 수
- {branch}: 현재 브랜치명
- {body}: 생성된 본문

📝 **포맷 예시:**
- Conventional Commits: "{type}({scope}): {subject}"
- 상세 정보 포함: "[{type}] {subject} - {files_changed} files changed"
- 이모지 활용: "{emoji} {type}: {subject}\\n\\n{body}"
- 브랜치 정보: "🚀 {branch} | {type}: {subject}"

🛡️ **안전 기능:**
- git 명령어 실행 가능 여부 사전 체크
- git repository 존재 여부 확인
- 타임아웃 설정으로 무한 대기 방지
- 상세한 에러 진단 및 해결 가이드 제공
- 쉘 인젝션 공격 방지를 위한 안전한 명령 실행

💡 **사용 대상:**
- Git 커밋 메시지 작성이 어려운 개발자
- 일관된 커밋 메시지 규칙을 적용하고 싶은 팀
- Conventional Commits 표준을 따르고 싶은 프로젝트
- 커밋 메시지 작성 시간을 단축하고 싶은 모든 개발자
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from mcp.types import Tool, TextContent

logger = logging.getLogger("mcp.tools.commit_suggester")

# ---------------------------------------------------------------------------
# MCP Tool 스펙 정의: LLM이 이 도구를 이해하고 호출할 수 있도록 하는 "설명서"
# ---------------------------------------------------------------------------
# 
# 이 tool_spec은 MCP(Model Context Protocol) 표준에 따라 정의된 도구 명세입니다.
# LLM(언어모델)이 이 도구를 언제, 어떻게 사용해야 하는지 알 수 있도록 
# 상세한 설명과 매개변수 정보를 제공합니다.

tool_spec = Tool(
    # 도구의 고유 이름 (LLM이 호출할 때 사용)
    name="commit_suggester",
    
    # 도구의 기능에 대한 간단한 설명 (LLM이 도구 선택할 때 참고)
    description="Git 변경 내용을 요약해 규칙(Conventional Commits 등)에 맞춘 커밋 메시지 후보를 생성합니다. 사용자 정의 포맷도 지원합니다.",
    inputSchema={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "mode": {
                "type": "string",
                "description": "변경 범위: staged(스테이징), working(작업 트리), range(커밋 범위)",
                "enum": ["staged", "working", "range"],
                "default": "staged"
            },
            "range": {
                "type": "string",
                "description": "mode=range일 때 사용할 git 범위 (예: HEAD~3..HEAD)",
                "examples": ["HEAD~3..HEAD", "origin/main..HEAD"]
            },
            "format": {
                "type": "string",
                "description": "사용자 정의 커밋 메시지 포맷. 템플릿 변수 사용 가능: {type}, {scope}, {subject}, {emoji}, {files_changed}, {branch} 등",
                "examples": [
                    "{type}({scope}): {subject}",
                    "[{type}] {subject} - {files_changed} files changed",
                    "{emoji} {type}: {subject}\\n\\n{body}",
                    "🚀 {branch} | {type}: {subject}"
                ]
            },
            "rules": {
                "type": "object",
                "description": "커밋 규칙 설정(미지정 시 기본 Conventional Commits 규칙 사용)",
                "properties": {
                    "types": {
                        "type": "array", "items": {"type": "string"},
                        "description": "허용 type 목록", 
                        "default": ["feat","fix","docs","refactor","test","chore","build","perf","ci"]
                    },
                    "require_scope": {"type": "boolean", "default": False},
                    "subject_max": {"type": "integer", "default": 72, "minimum": 10, "maximum": 120},
                    "allow_emoji": {"type": "boolean", "default": False},
                    "scope_enum": {"type": "array", "items": {"type": "string"}}
                },
                "additionalProperties": False
            },
            "language": {
                "type": "string",
                "enum": ["ko", "en"],
                "default": "ko"
            },
            "suggestions": {
                "type": "integer",
                "minimum": 1,
                "maximum": 10,
                "default": 3
            },
            "breaking": {
                "type": "boolean",
                "description": "BREAKING CHANGE footer 포함 여부",
                "default": False
            },
            "debug": {
                "type": "boolean",
                "description": "디버깅 정보 출력 여부",
                "default": False
            },
            "path": {
                "type": "string",
                "description": "사용자가 지정한 Git 리포지터리 경로. 상대 경로이면 현재 작업 디렉토리 기준으로 해석됨",
                "examples": ["./", "subproject/"]
            }
        },
        "required": [],
        "examples": [
            {
                "mode": "staged", 
                "language": "ko", 
                "suggestions": 3,
                "format": "{type}({scope}): {subject}"
            },
            {
                "mode": "range", 
                "range": "HEAD~5..HEAD", 
                "language": "en", 
                "format": "[{type}] {subject} - {files_changed} files changed"
            },
            {
                "mode": "working",
                "format": "{emoji} {branch} | {type}: {subject}\\n\\n📝 Changed files: {files_changed}\\n{body}",
                "debug": True,
                "path": "./"
            }
        ]
    },
)

# -------------------------
# 내부 데이터 구조/헬퍼
# -------------------------

@dataclass
class DiffSummary:
    """
    Git diff 결과를 요약한 데이터 구조입니다.
    
    이 클래스는 git diff --name-status 명령의 출력을 파싱한 결과를 저장합니다.
    변경된 파일들의 상세 정보와 전체적인 통계 정보를 함께 제공합니다.
    """
    # 변경된 파일들의 목록: [(상태코드, 파일경로), ...]
    # 상태코드 예시: A=추가, M=수정, D=삭제, R=이름변경, C=복사
    changed: List[Tuple[str, str]]
    
    # 변경 유형별 통계: {"added": 3, "modified": 2, "deleted": 1, "renamed": 0}
    stats: Dict[str, int]


@dataclass
class CommitContext:
    """
    커밋 메시지 생성에 필요한 모든 컨텍스트 정보를 담는 데이터 구조입니다.
    
    이 클래스는 커밋 메시지 포맷팅에 필요한 모든 정보를 한 곳에 모아둡니다.
    사용자 정의 포맷이나 표준 포맷 모두에서 이 정보를 활용할 수 있습니다.
    """
    type: str                    # 커밋 타입 (feat, fix, docs 등)
    scope: Optional[str]         # 스코프 (모듈/컴포넌트명, 없을 수 있음)
    subject: str                 # 커밋 제목/요약
    body: List[str]              # 커밋 본문 (여러 줄일 수 있음)
    emoji: str                   # 타입에 해당하는 이모지
    branch: Optional[str]        # 현재 브랜치명 (없을 수 있음)
    stats: Dict[str, int]        # 변경 통계 정보
    files_changed: int           # 총 변경된 파일 수
    files_added: int             # 추가된 파일 수
    files_modified: int          # 수정된 파일 수
    files_deleted: int           # 삭제된 파일 수


async def _check_git_availability() -> Tuple[bool, str]:
    """
    git 명령어가 사용 가능한지 확인하는 함수입니다.
    
    이 함수는 다음 두 단계로 git의 사용 가능성을 검증합니다:
    1. 시스템의 PATH 환경변수에서 git 실행파일을 찾을 수 있는지 확인
    2. 실제로 git 명령어를 실행해보고 정상 동작하는지 테스트
    
    반환값:
        Tuple[bool, str]: (사용 가능 여부, 상세 메시지)
        - bool: True면 git 사용 가능, False면 사용 불가
        - str: 결과에 대한 상세 설명 메시지
    """
    # 1. git 실행 파일이 PATH에 있는지 확인
    # shutil.which()는 PATH에서 실행파일을 찾는 함수입니다
    # 예를 들어 "/usr/bin/git" 같은 경로를 반환하거나, 찾지 못하면 None을 반환
    git_path = shutil.which("git")
    if not git_path:
        return False, "git 명령어를 찾을 수 없습니다. Git이 설치되어 있고 PATH에 포함되어 있는지 확인하세요."
    
    # 2. git 버전 확인으로 실행 가능 여부 테스트
    # 실제로 git 명령어를 실행해서 정상 동작하는지 확인합니다
    try:
        # subprocess.run()으로 외부 명령어를 안전하게 실행
        # capture_output=True: 출력을 캡처해서 변수에 저장
        # text=True: 바이트가 아닌 문자열로 결과를 받음
        # timeout=5: 5초 안에 끝나지 않으면 강제 종료
        result = subprocess.run(
            [git_path, "--version"],  # 실행할 명령어와 인자들을 리스트로 전달
            capture_output=True, 
            text=True, 
            timeout=5
        )
        
        # returncode가 0이면 명령어가 성공적으로 실행된 것
        # Unix/Linux에서는 0이 성공, 0이 아닌 값은 실패를 의미
        if result.returncode == 0:
            return True, f"Git 사용 가능 (경로: {git_path}, 버전: {result.stdout.strip()})"
        else:
            # 실행은 됐지만 에러로 종료된 경우
            return False, f"git --version 실행 실패: {result.stderr}"
    except subprocess.TimeoutExpired:
        # 5초 안에 끝나지 않은 경우 (네트워크 문제 등)
        return False, "git 명령어 실행 시간 초과"
    except Exception as e:
        # 그 외 예상하지 못한 에러가 발생한 경우
        return False, f"git 실행 중 예외 발생: {e}"


async def _check_git_repository(cwd: Optional[str] = None) -> Tuple[bool, str]:
    """
    현재 디렉토리가 git repository인지 확인하는 함수입니다.
    
    Git repository인지 확인하는 방법:
    1. 현재 디렉토리에 .git 폴더/파일이 있는지 확인
    2. 없다면 상위 디렉토리들을 차례로 올라가면서 .git을 찾음
    3. 루트 디렉토리까지 올라가도 못 찾으면 git repository가 아님
    
    매개변수:
        cwd: 확인할 디렉토리 경로 (None이면 현재 작업 디렉토리 사용)
    
    반환값:
        Tuple[bool, str]: (git repo 여부, 상세 메시지)
        - bool: True면 git repository, False면 아님
        - str: 결과에 대한 상세 설명
    """
    # 확인할 디렉토리 결정: 매개변수로 받았으면 그것을, 아니면 현재 디렉토리
    # Path.cwd()는 현재 작업 디렉토리를 Path 객체로 반환
    check_dir = Path(cwd) if cwd else Path.cwd()
    
    # .git 디렉토리 또는 파일 확인
    # .git은 보통 폴더이지만, git worktree에서는 파일일 수도 있음
    # Path의 / 연산자로 경로를 결합할 수 있음 (예: /home/user + .git = /home/user/.git)
    git_path = check_dir / ".git"
    if git_path.exists():
        return True, f"Git repository 확인됨 (경로: {check_dir})"
    
    # 상위 디렉토리로 올라가면서 .git 찾기
    # Git은 현재 디렉토리에 .git이 없으면 상위 디렉토리들을 찾아 올라감
    # 이렇게 해서 프로젝트 내 어떤 하위 폴더에서도 git 명령어를 쓸 수 있음
    current = check_dir
    for parent in current.parents:  # parents는 상위 디렉토리들을 순서대로 반환
        git_path = parent / ".git"
        if git_path.exists():
            return True, f"Git repository 확인됨 (상위 경로: {parent})"
    
    # 루트까지 올라가도 .git을 못 찾은 경우
    return False, f"Git repository가 아닙니다. 현재 경로: {check_dir}\\n'git init' 또는 git repository가 있는 디렉토리에서 실행하세요."


async def _run_git_safe(*args: str, cwd: Optional[str] = None, timeout: int = 10) -> Tuple[int, str, str]:
    """
    안전하게 git 명령을 실행하고 결과를 반환하는 함수입니다.
    
    이 함수가 안전한 이유:
    1. 쉘 인젝션 공격 방지: 쉘을 거치지 않고 직접 실행
    2. 타임아웃 설정: 무한히 기다리지 않고 일정 시간 후 강제 종료
    3. 사전 검증: git과 repository 상태를 미리 확인
    4. 예외 처리: 다양한 에러 상황에 대한 적절한 처리
    
    매개변수:
        *args: git 명령의 인자들 (예: "diff", "--staged", "--name-status")
        cwd: git 명령을 실행할 디렉토리 (None이면 현재 디렉토리)
        timeout: 타임아웃 시간(초), 기본값은 10초
    
    반환값:
        Tuple[int, str, str]: (리턴코드, 표준출력, 표준에러)
        - int: 명령어 실행 결과 코드 (0=성공, 0이외=실패)
        - str: 명령어의 정상 출력 (stdout)
        - str: 명령어의 에러 출력 (stderr)
    """
    # 1. git 사용 가능 여부 체크
    # 먼저 시스템에 git이 설치되어 있고 사용 가능한지 확인
    git_available, git_message = await _check_git_availability()
    if not git_available:
        logger.error(f"Git 사용 불가: {git_message}")
        # 127은 "command not found" 에러 코드
        return 127, "", git_message
    
    # 2. git repository 여부 체크
    # 일부 git 명령어는 repository가 없어도 실행 가능하므로 예외 처리
    if args and args[0] not in ["--version", "init"]:  # init이나 version 체크가 아닌 경우만
        repo_available, repo_message = await _check_git_repository(cwd)
        if not repo_available:
            logger.error(f"Git repository 없음: {repo_message}")
            # 128은 일반적인 git 에러 코드
            return 128, "", repo_message
    
    # 3. 실제 git 명령 실행
    try:
        # asyncio.create_subprocess_exec로 비동기 프로세스 생성
        # 쉘을 거치지 않고 직접 실행하므로 보안상 안전함
        # PIPE로 설정하면 출력을 캡처할 수 있음
        proc = await asyncio.create_subprocess_exec(
            "git", *args,  # "git" + 인자들 (예: git diff --staged)
            cwd=cwd,  # 실행할 디렉토리
            stdout=asyncio.subprocess.PIPE,  # 표준 출력 캡처
            stderr=asyncio.subprocess.PIPE,  # 표준 에러 캡처
        )
        
        try:
            # 프로세스가 끝나기를 기다리면서 출력 받기
            # wait_for로 타임아웃 설정 - 무한 대기 방지
            out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return (
                proc.returncode,  # 프로세스 종료 코드
                out_b.decode("utf-8", "ignore"),  # 바이트를 문자열로 디코딩
                err_b.decode("utf-8", "ignore")   # 에러도 문자열로 디코딩
            )
        except asyncio.TimeoutError:
            # 타임아웃이 발생하면 프로세스를 강제 종료
            proc.kill()
            await proc.wait()  # 프로세스가 완전히 종료될 때까지 대기
            return 124, "", f"git {' '.join(args)} 시간 초과 ({timeout}초)"
            
    except FileNotFoundError:
        # git 실행파일을 찾을 수 없는 경우
        return 127, "", "git 명령어를 찾을 수 없습니다"
    except PermissionError:
        # git 실행 권한이 없는 경우
        return 126, "", "git 명령어 실행 권한이 없습니다"
    except Exception as e:
        # 그 외 예상하지 못한 에러
        logger.exception(f"git 명령 실행 중 예외: {e}")
        return 1, "", f"git 명령 실행 중 예외: {e}"


async def _get_current_branch(cwd: Optional[str] = None) -> Optional[str]:
    """
    현재 체크아웃된 브랜치 이름을 가져오는 함수입니다.
    
    Git에서 현재 브랜치를 확인하는 방법:
    - git rev-parse --abbrev-ref HEAD 명령어 사용
    - 이 명령어는 현재 브랜치의 이름을 간단히 반환함 (예: "main", "feature/login")
    - detached HEAD 상태(특정 커밋을 직접 체크아웃한 상태)에서는 "HEAD"를 반환
    
    매개변수:
        cwd: git 명령을 실행할 디렉토리 (None이면 현재 디렉토리)
    
    반환값:
        Optional[str]: 브랜치명, detached HEAD이거나 실패 시 None
    """
    # git rev-parse --abbrev-ref HEAD 명령 실행
    # 이 명령어는 현재 체크아웃된 브랜치의 이름을 반환
    code, out, err = await _run_git_safe("rev-parse", "--abbrev-ref", "HEAD", cwd=cwd)
    
    if code != 0:
        # 명령어 실행에 실패한 경우 (git repo가 아니거나 다른 문제)
        logger.warning(f"브랜치 확인 실패: {err}")
        return None
    
    branch = out.strip()  # 앞뒤 공백 제거
    
    # detached HEAD 상태 확인
    # detached HEAD는 브랜치가 아닌 특정 커밋에 직접 체크아웃된 상태
    # 이 경우 브랜치명이 "HEAD"로 나오거나 빈 문자열이 됨
    if not branch or branch == "HEAD":
        return None
    
    return branch


def _summarize_status(lines: List[str]) -> DiffSummary:
    """
    git diff --name-status 형식의 출력을 파싱해서 변경 통계를 계산하는 함수입니다.
    
    git diff --name-status의 출력 형식:
    - 각 라인은 "상태\t파일경로" 형태
    - 상태 코드:
      * A: Added (새 파일 추가)
      * M: Modified (기존 파일 수정) 
      * D: Deleted (파일 삭제)
      * R: Renamed (파일 이름 변경)
      * C: Copied (파일 복사)
    - 예시: "M\tsrc/app.py", "A\tnew_file.txt", "D\told_file.txt"
    
    매개변수:
        lines: git diff --name-status 명령의 출력 라인들
    
    반환값:
        DiffSummary: 변경된 파일 목록과 통계가 담긴 객체
    """
    # 변경된 파일들의 (상태, 경로) 튜플 목록
    changed: List[Tuple[str, str]] = []
    
    # 변경 유형별 카운트를 저장할 딕셔너리
    stats = {"added": 0, "modified": 0, "deleted": 0, "renamed": 0}
    
    for line in lines:
        line = line.strip()  # 앞뒤 공백 제거
        if not line:
            continue  # 빈 라인 건너뛰기
        
        # 탭 문자로 분리 (git diff --name-status의 표준 형식)
        # 예) "A\tsrc/app.py" -> ["A", "src/app.py"]
        # 예) "R100\told.py\tnew.py" -> ["R100", "old.py", "new.py"]
        parts = line.split("\t")
        if len(parts) < 2:
            continue  # 잘못된 형식의 라인 건너뛰기
            
        status = parts[0]  # 상태 코드 (A, M, D, R 등)
        path = parts[-1]   # 파일 경로 (rename의 경우 마지막이 새 경로)
        s = status[0]      # 상태 코드의 첫 번째 문자만 추출
        
        # 상태별로 카운트 증가
        if s == "A":
            stats["added"] += 1
        elif s == "M":
            stats["modified"] += 1
        elif s == "D":
            stats["deleted"] += 1
        elif s == "R":
            stats["renamed"] += 1
            
        # 변경된 파일 목록에 추가
        changed.append((s, path))
    
    return DiffSummary(changed=changed, stats=stats)


def _infer_type_and_scope(changed: List[Tuple[str, str]]) -> Tuple[str, Optional[str]]:
    """
    변경된 파일들을 분석해서 커밋 타입과 스코프를 자동으로 추정하는 함수입니다.
    
    추정 방법:
    1. 타입 추정: 파일 경로와 이름에서 키워드를 찾아서 판단
       - "fix", "bug" 등이 있으면 -> "fix"
       - ".md", "docs/" 등이 있으면 -> "docs"
       - "test", ".spec." 등이 있으면 -> "test"
       - 기타 빌드 관련 파일들 -> "build"
       - 그 외 -> "feat" (새 기능으로 간주)
    
    2. 스코프 추정: 최상위 디렉토리명을 스코프로 사용
       - 예: src/app/main.py -> scope="src"
       - 예: tools/commit_suggester.py -> scope="tools"
    
    매개변수:
        changed: [(상태, 경로)] 형태의 변경된 파일 목록
    
    반환값:
        Tuple[str, Optional[str]]: (추정된 타입, 추정된 스코프)
    """
    # 변경된 파일이 없으면 기본값 반환
    if not changed:
        return "chore", None

    # 모든 파일 경로를 하나의 문자열로 합치고 소문자로 변환
    # 이렇게 하면 정규식으로 한 번에 패턴을 찾을 수 있음
    paths = [p for _, p in changed]  # 경로만 추출
    lower_blob = "\\n".join(paths).lower()  # 소문자로 변환해서 대소문자 구분 없이 검색
    
    # 타입 추정 (우선순위 순으로 체크)
    import re
    
    # 1. 버그 수정 관련 키워드 체크
    if re.search(r"(fix|bug|error|exception|hotfix)", lower_blob):
        ctype = "fix"
    # 2. 문서 관련 파일 체크
    elif re.search(r"(doc|readme|mkdocs|docs/|\\.md$)", lower_blob):
        ctype = "docs"
    # 3. 테스트 관련 파일 체크
    elif re.search(r"(test|spec|pytest|jest|\\.test\\.|__tests__|\\.spec\\.)", lower_blob):
        ctype = "test"
    # 4. 빌드/배포 관련 파일 체크
    elif re.search(r"(build|dockerfile|docker-compose|\\.lock$|package\\.json|requirements\\.txt)", lower_blob):
        ctype = "build"
    # 5. 리팩터링 관련 키워드 체크
    elif re.search(r"(refactor|rename|cleanup|restructure)", lower_blob):
        ctype = "refactor"
    # 6. 성능 최적화 관련 키워드 체크
    elif re.search(r"(perf|benchmark|optimi[s|z]e)", lower_blob):
        ctype = "perf"
    # 7. 위에 해당하지 않으면 새로운 기능으로 간주
    else:
        ctype = "feat"

    # scope 추정: 최상위 디렉토리명 사용
    # 프로젝트 구조에서 최상위 폴더명이 보통 모듈이나 컴포넌트를 나타내므로
    # 이를 스코프로 사용하면 적절한 경우가 많음
    scope = None
    for p in paths:
        parts = p.split("/")  # 경로를 "/" 기준으로 분리
        # 하위 디렉토리가 있고, 최상위가 ".", ".." 같은 특수 디렉토리가 아닌 경우
        if len(parts) > 1 and parts[0] not in (".", ".."):
            scope = parts[0]  # 최상위 디렉토리명을 스코프로 설정
            break  # 첫 번째로 찾은 것을 사용
    
    return ctype, scope


def _get_emoji_for_type(ctype: str) -> str:
    """
    커밋 타입에 해당하는 이모지를 반환하는 함수입니다.
    
    각 커밋 타입별로 의미에 맞는 이모지를 매핑해둡니다.
    이모지를 사용하면 커밋 로그를 볼 때 한눈에 어떤 종류의 변경인지 알 수 있어서
    프로젝트 히스토리를 이해하기 쉬워집니다.
    
    매개변수:
        ctype: 커밋 타입 (feat, fix, docs 등)
    
    반환값:
        str: 해당하는 이모지 (매핑되지 않은 타입은 기본 이모지 "📝" 반환)
    """
    # 커밋 타입별 이모지 매핑
    # 각 이모지는 해당 작업의 성격을 직관적으로 나타냄
    emoji_map = {
        "feat": "✨",      # 새로운 기능 - 반짝이는 별
        "fix": "🐛",       # 버그 수정 - 벌레
        "docs": "📝",      # 문서 작업 - 메모
        "refactor": "♻️",  # 리팩터링 - 재활용 (코드 재구성)
        "test": "✅",      # 테스트 - 체크마크
        "build": "🏗️",     # 빌드 관련 - 건설 크레인
        "perf": "🚀",      # 성능 개선 - 로켓 (빠른 속도)
        "chore": "🧹",     # 잡무 - 빗자루 (정리 작업)
        "ci": "🔧",        # CI/CD - 렌치 (도구)
        "style": "💄"      # 스타일링 - 립스틱 (꾸미기)
    }
    
    # get() 메서드로 안전하게 접근 - 키가 없으면 기본값 반환
    return emoji_map.get(ctype, "📝")


def _generate_subject_templates(ctype: str, lang: str) -> List[str]:
    """
    커밋 타입과 언어에 따른 주제 템플릿들을 생성하는 함수입니다.
    
    이 함수는 각 커밋 타입별로 적절한 주제 문구들을 미리 준비해두고,
    사용자가 선택할 수 있는 여러 옵션을 제공합니다.
    한국어와 영어 모두 지원하여 다양한 프로젝트에서 사용할 수 있습니다.
    
    매개변수:
        ctype: 커밋 타입 (feat, fix, docs 등)
        lang: 언어 코드 ("ko"=한국어, "en"=영어)
    
    반환값:
        List[str]: 해당 타입에 맞는 주제 템플릿 목록 (보통 3개 정도)
    """
    if lang == "ko":
        # 한국어 템플릿들 - 각 타입별로 자주 사용되는 표현들
        templates = {
            "feat": ["새 기능 추가", "기능 초기 도입", "기능 지원 구현"],
            "fix": ["버그 수정", "문제 해결", "엣지 케이스 처리"],
            "docs": ["문서 업데이트", "README 보완", "사용 가이드 추가"],
            "refactor": ["리팩터링", "코드 구조 재정비", "정리"],
            "test": ["테스트 추가", "테스트 커버리지 개선", "플레이키 테스트 안정화"],
            "build": ["빌드 설정 업데이트", "의존성 조정", "패키징 수정"],
            "perf": ["성능 최적화", "오버헤드 감소", "지연시간 개선"],
            "chore": ["유지보수 작업", "사소한 수정", "설정 업데이트"],
        }
    else:
        # 영어 템플릿들 - 국제적으로 통용되는 표현들
        templates = {
            "feat": ["add new capability", "introduce feature", "implement initial support"],
            "fix": ["fix issue", "resolve bug", "handle edge case"],
            "docs": ["update documentation", "improve README", "add usage notes"],
            "refactor": ["refactor internal structure", "reorganize code", "cleanup"],
            "test": ["add tests", "improve test coverage", "stabilize flaky tests"],
            "build": ["update build config", "adjust dependencies", "tweak packaging"],
            "perf": ["optimize performance", "reduce overhead", "improve latency"],
            "chore": ["maintenance chores", "minor tweaks", "update config"],
        }
    
    # 해당 타입의 템플릿을 반환, 없으면 기본값 반환
    return templates.get(ctype, ["update"] if lang == "en" else ["업데이트"])


def _truncate_subject(text: str, max_len: int) -> str:
    """
    커밋 메시지 제목이 너무 길면 잘라내는 함수입니다.
    
    커밋 메시지 제목은 일반적으로 50-72자 이내로 제한하는 것이 좋습니다.
    너무 길면 Git 로그나 GitHub에서 제대로 표시되지 않을 수 있기 때문입니다.
    
    매개변수:
        text: 원본 텍스트
        max_len: 최대 허용 길이 (보통 50-72자)
    
    반환값:
        str: 길이가 조정된 텍스트 (잘렸을 때는 끝에 "…" 추가)
    """
    text = text.strip()  # 앞뒤 공백 제거
    
    # 길이가 제한 이내면 그대로 반환
    if len(text) <= max_len:
        return text
    else:
        # 너무 길면 잘라내고 말줄임표 추가
        # max(0, max_len - 1)로 음수가 되지 않도록 보호
        return text[: max(0, max_len - 1)] + "…"


def _apply_custom_format(format_template: str, context: CommitContext) -> str:
    """
    사용자가 정의한 커밋 메시지 포맷 템플릿에 실제 값들을 치환하는 함수입니다.
    
    이 함수는 템플릿 엔진의 역할을 합니다. 사용자가 {type}, {scope} 같은 
    플레이스홀더를 포함한 템플릿을 제공하면, 실제 커밋 정보로 치환해줍니다.
    
    지원하는 플레이스홀더:
    - {type}: 커밋 타입 (feat, fix 등)
    - {scope}: 스코프 (있을 경우)
    - {subject}: 커밋 제목
    - {emoji}: 타입별 이모지
    - {branch}: 현재 브랜치명
    - {files_changed}: 총 변경된 파일 수
    - {files_added}: 추가된 파일 수
    - {files_modified}: 수정된 파일 수
    - {files_deleted}: 삭제된 파일 수
    - {body}: 커밋 본문
    
    매개변수:
        format_template: 사용자가 제공한 포맷 템플릿 (예: "{type}({scope}): {subject}")
        context: 치환할 실제 값들이 담긴 컨텍스트 객체
    
    반환값:
        str: 포맷이 적용된 최종 커밋 메시지
    """
    # 치환할 변수들을 딕셔너리로 준비
    # None 값들은 빈 문자열로 변환하여 템플릿에서 안전하게 사용 가능
    replacements = {
        "type": context.type,
        "scope": context.scope or "",  # None이면 빈 문자열
        "subject": context.subject,
        "emoji": context.emoji,
        "branch": context.branch or "",  # None이면 빈 문자열
        "files_changed": str(context.files_changed),  # 숫자를 문자열로 변환
        "files_added": str(context.files_added),
        "files_modified": str(context.files_modified),
        "files_deleted": str(context.files_deleted),
        "body": "\\n".join(context.body) if context.body else ""  # 리스트를 문자열로 결합
    }
    
    # 스코프가 있는 경우의 조건부 포맷팅
    # 예: scope가 "auth"이면 "(auth)", 없으면 빈 문자열
    scope_part = f"({context.scope})" if context.scope else ""
    replacements["scope_with_parens"] = scope_part
    
    # 템플릿에서 플레이스홀더 찾아서 실제 값으로 치환
    result = format_template
    for key, value in replacements.items():
        # {key} 형태의 플레이스홀더를 실제 값으로 교체
        result = result.replace(f"{{{key}}}", str(value))
    
    # 이스케이프 문자 처리
    # 사용자가 \\n을 입력했으면 실제 줄바꿈으로 변환
    result = result.replace("\\\\n", "\\n").replace("\\\\t", "\\t")
    
    return result


def _format_conventional_message(context: CommitContext, breaking: bool, lang: str) -> str:
    """
    Conventional Commits 표준 형식으로 커밋 메시지를 포맷하는 함수입니다.
    
    Conventional Commits는 커밋 메시지의 표준 형식으로, 다음과 같은 구조를 가집니다:
    
    <type>[optional scope]: <description>
    
    [optional body]
    
    [optional footer(s)]
    
    예시:
    feat(auth): add login functionality
    
    Implement OAuth2 login with Google provider
    - Add login button to header
    - Handle authentication flow
    
    BREAKING CHANGE: login API endpoint changed
    
    매개변수:
        context: 커밋 관련 모든 정보가 담긴 컨텍스트 객체
        breaking: BREAKING CHANGE footer를 포함할지 여부
        lang: 언어 설정 ("ko" 또는 "en")
    
    반환값:
        str: Conventional Commits 형식으로 포맷된 커밋 메시지
    """
    # 헤더 구성: type(scope): subject
    # scope가 있으면 괄호로 감싸고, 없으면 생략
    scope_part = f"({context.scope})" if context.scope else ""
    head = f"{context.type}{scope_part}: {context.subject}"
    
    # 메시지의 각 부분을 담을 리스트
    parts = [head]
    
    # 본문 추가 (있는 경우)
    # 헤더와 본문 사이에는 빈 줄이 있어야 함
    if context.body:
        parts.append("")  # 빈 줄 추가
        parts.extend(context.body)  # 본문의 각 라인 추가
    
    # Breaking change footer 추가 (요청된 경우)
    # 본문과 footer 사이에도 빈 줄이 있어야 함
    if breaking:
        parts.append("")  # 빈 줄 추가
        if lang == "ko":
            parts.append("BREAKING CHANGE: 하위 호환되지 않는 변경")
        else:
            parts.append("BREAKING CHANGE: behavior changed in a backward-incompatible way")
    
    # 모든 부분을 줄바꿈으로 연결해서 최종 메시지 생성
    return "\\n".join(parts)


async def handle(arguments: Dict[str, Any]) -> List[TextContent]:
    """
    MCP 클라이언트의 요청을 처리하여 커밋 메시지 후보들을 생성하는 메인 함수입니다.
    
    이 함수는 전체 프로세스를 조율하는 역할을 합니다:
    1. 사용자 입력 파싱 및 검증
    2. Git 환경 확인 (git 설치, repository 존재 등)
    3. Git 변경사항 수집 (staged, working, range 모드별로)
    4. 변경사항 분석하여 커밋 타입과 스코프 추정
    5. 브랜치 이름 기반 추가 정보 수집
    6. 커밋 메시지 후보들 생성
    7. 사용자 정의 포맷 또는 표준 형식으로 포맷팅
    
    매개변수:
        arguments: MCP 클라이언트에서 전달된 인자들 (딕셔너리)
                  mode, range, format, rules, language, suggestions 등 포함
    
    반환값:
        List[TextContent]: 생성된 커밋 메시지 후보들을 담은 리스트
    """
    # 0) 입력 파싱 및 기본값 설정
    # 각 매개변수에 대해 기본값을 설정하고 타입 변환 수행
    
    # 변경사항을 가져올 모드 설정 (staged: 스테이징된 변경사항, working: 작업트리 변경사항, range: 커밋 범위)
    mode = (arguments.get("mode") or "staged").lower()
    
    # range 모드에서 사용할 git 범위 (예: HEAD~3..HEAD)
    rng = arguments.get("range")
    
    # 사용자 정의 커밋 메시지 포맷 템플릿
    custom_format = arguments.get("format")
    
    # 커밋 규칙 설정 (타입 제한, 스코프 필수 여부 등)
    rules = arguments.get("rules") or {}
    
    # 언어 설정 (한국어/영어)
    lang = (arguments.get("language") or "ko").lower()
    
    # 생성할 메시지 후보 개수
    suggestions = arguments.get("suggestions") or 3
    
    # BREAKING CHANGE footer 포함 여부
    breaking = bool(arguments.get("breaking") or False)
    
    # 디버깅 정보 출력 여부
    debug = bool(arguments.get("debug") or False)

    # 1) 사용자 지정 경로 처리
    # 사용자가 특정 디렉토리를 지정했다면 그 경로에서 git 명령을 실행
    # 지정하지 않았다면 현재 작업 디렉토리 사용
    path_arg = arguments.get("path")
    if path_arg:
        # 경로가 문자열인지 확인
        if not isinstance(path_arg, str):
            return [TextContent(type="text", text="❌ 'path'는 문자열이어야 합니다. 예: path: './' 또는 'subdir/'")]
        
        candidate = Path(path_arg)
        
        # 상대 경로인 경우 절대 경로로 변환
        if not candidate.is_absolute():
            candidate = (Path.cwd() / candidate).resolve()
        
        # 경로가 실제로 존재하고 디렉토리인지 확인
        if not candidate.exists() or not candidate.is_dir():
            return [TextContent(type="text", text=f"❌ 지정한 경로가 존재하지 않거나 디렉토리가 아닙니다: {candidate}")]
        
        repo_check_cwd: Optional[str] = str(candidate)
    else:
        repo_check_cwd = None  # 현재 디렉토리 사용

    # 2) 디버그 정보 수집
    # 디버그 모드일 때 상세한 실행 정보를 수집
    debug_info = []
    if debug:
        debug_info.append(f"🔍 디버그 모드 활성화")
        debug_info.append(f"📂 현재 작업 디렉토리: {Path.cwd()}")
        debug_info.append(f"🎯 모드: {mode}")
        debug_info.append(f"📌 경로 기준: {repo_check_cwd or Path.cwd()}")

    # 3) 커밋 규칙 설정 (Conventional Commit 스타일 기본값)
    # 사용자가 rules에서 지정하지 않은 항목들은 기본값 사용
    
    # 허용되는 커밋 타입들 (feat, fix, docs 등)
    allowed_types = rules.get("types") or ["feat","fix","docs","refactor","test","chore","build","perf","ci"]
    
    # 스코프가 필수인지 여부
    require_scope = bool(rules.get("require_scope") or False)
    
    # 제목의 최대 길이 (일반적으로 50-72자)
    subject_max = int(rules.get("subject_max") or 72)
    
    # 이모지 사용 허용 여부
    allow_emoji = bool(rules.get("allow_emoji") or False)
    
    # 허용되는 스코프 목록 (지정된 경우에만)
    scope_enum = rules.get("scope_enum")

    # 4) Git 환경 사전 체크
    # Git이 설치되어 있고 사용 가능한지 확인
    git_available, git_message = await _check_git_availability()
    if debug:
        debug_info.append(f"🔧 Git 체크: {git_message}")
    
    # Git이 사용 불가능한 경우 에러 메시지와 해결 방법 제공
    if not git_available:
        error_msg = f"❌ Git 설정 문제\\n\\n{git_message}\\n\\n해결 방법:\\n1. Git 설치 확인: https://git-scm.com/\\n2. PATH 환경변수에 git 포함 확인\\n3. 터미널에서 'git --version' 명령 테스트"
        if debug:
            error_msg += f"\\n\\n🔍 디버그 정보:\\n" + "\\n".join(debug_info)
        return [TextContent(type="text", text=error_msg)]

    # Git repository가 있는지 확인
    repo_available, repo_message = await _check_git_repository(cwd=repo_check_cwd)
    if debug:
        debug_info.append(f"📁 Repository 체크: {repo_message}")
    
    # Git repository가 없는 경우 에러 메시지와 해결 방법 제공
    if not repo_available:
        error_msg = f"❌ Git Repository 문제\\n\\n{repo_message}\\n\\n해결 방법:\\n1. git repository가 있는 디렉토리로 이동\\n2. 새 repository 초기화: 'git init'\\n3. 기존 repository 클론: 'git clone <URL>'"
        if debug:
            error_msg += f"\\n\\n🔍 디버그 정보:\\n" + "\\n".join(debug_info)
        return [TextContent(type="text", text=error_msg)]

    # 5) Git 변경사항 수집
    # 모드에 따라 다른 git diff 명령을 실행하여 변경된 파일 목록 수집
    
    if mode == "staged":
        # 스테이징된 변경사항만 가져오기 (git add 된 파일들)
        code, out, err = await _run_git_safe("diff", "--staged", "--name-status", cwd=repo_check_cwd)
    elif mode == "working":
        # 작업 트리의 모든 변경사항 가져오기 (스테이징 여부 무관)
        code, out, err = await _run_git_safe("diff", "--name-status", cwd=repo_check_cwd)
    elif mode == "range":
        # 특정 커밋 범위의 변경사항 가져오기 (예: HEAD~3..HEAD)
        if not rng:
            return [TextContent(type="text", text="❌ mode=range 인데 range 값이 없습니다. 예: HEAD~3..HEAD")]
        code, out, err = await _run_git_safe("diff", "--name-status", rng, cwd=repo_check_cwd)
    else:
        # 지원하지 않는 모드인 경우
        return [TextContent(type="text", text=f"❌ 알 수 없는 mode: {mode}")]

    if debug:
        debug_info.append(f"⚙️ Git 명령 결과: 리턴코드={code}, 출력길이={len(out)}, 에러={err[:100]}...")

    if code != 0:
        logger.warning("git diff failed rc=%s err=%s", code, err.strip())
        error_msg = f"❌ git diff 실패: {err.strip() or f'리턴코드 {code}'}\\n\\n가능한 원인:\\n1. 잘못된 range 형식 (올바른 예: HEAD~3..HEAD)\\n2. 존재하지 않는 커밋 참조\\n3. git repository 상태 문제"
        if debug:
            error_msg += f"\\n\\n🔍 디버그 정보:\\n" + "\\n".join(debug_info)
        return [TextContent(type="text", text=error_msg)]

    lines = [ln for ln in out.splitlines() if ln.strip()]
    summary = _summarize_status(lines)

    if debug:
        debug_info.append(f"📊 변경 통계: {summary.stats}")

    if not summary.changed:
        hint = {
            "ko": "변경이 없습니다. 먼저 파일을 수정하거나, staged 모드에서는 `git add`로 스테이징하세요.",
            "en": "No changes. Modify files first, or run `git add` for staged mode.",
        }[lang]
        info_msg = f"ℹ️ {hint}"
        if debug:
            info_msg += f"\\n\\n🔍 디버그 정보:\\n" + "\\n".join(debug_info)
        return [TextContent(type="text", text=info_msg)]

    # 3) 타입/스코프 추정
    ctype, scope_guess = _infer_type_and_scope(summary.changed)

    # 브랜치 이름 기반 보정
    branch = await _get_current_branch(cwd=repo_check_cwd)
    if debug:
        debug_info.append(f"🌿 현재 브랜치: {branch}")
        debug_info.append(f"🎨 추정된 타입: {ctype}, 스코프: {scope_guess}")

    if branch:
        # feature/user-auth, fix/login-bug 등의 패턴 처리
        import re
        m = re.match(r'^(?P<prefix>feature|fix|docs|refactor|test|chore|perf|build)(?:/(?P<scope>[^/]+))?', branch)
        if m:
            prefix = m.group('prefix')
            branch_scope = m.group('scope')
            
            # prefix 매핑
            prefix_map = {
                'feature': 'feat',
                'fix': 'fix',
                'docs': 'docs',
                'refactor': 'refactor',
                'test': 'test',
                'chore': 'chore',
                'perf': 'perf',
                'build': 'build',
            }
            
            if prefix in prefix_map:
                ctype = prefix_map[prefix]
            if branch_scope:
                scope_guess = branch_scope

    # 스코프 규칙 적용
    if scope_enum and scope_guess not in scope_enum:
        scope_guess = None

    if require_scope and not scope_guess:
        scope_guess = "core"

    # 타입 규칙 적용
    if ctype not in allowed_types:
        ctype = "feat" if "feat" in allowed_types else allowed_types[0]

    if debug:
        debug_info.append(f"✅ 최종 타입: {ctype}, 최종 스코프: {scope_guess}")

    # 4) 본문 생성
    if lang == "ko":
        body_lines = [
            f"- 추가: {summary.stats['added']} 파일, 수정: {summary.stats['modified']} 파일, 삭제: {summary.stats['deleted']} 파일",
            f"- 대표 변경 경로: {', '.join(sorted(set(p for _, p in summary.changed[:5])))}",
        ]
    else:
        body_lines = [
            f"- added: {summary.stats['added']} files, modified: {summary.stats['modified']} files, deleted: {summary.stats['deleted']} files",
            f"- key paths: {', '.join(sorted(set(p for _, p in summary.changed[:5])))}",
        ]

    # 5) 커밋 메시지 후보 생성
    subject_templates = _generate_subject_templates(ctype, lang)
    subject_templates = subject_templates[:max(1, min(10, suggestions))]
    
    messages: List[str] = []
    
    for template in subject_templates:
        # 주제 생성 (이모지 옵션 포함)
        emoji = _get_emoji_for_type(ctype) if allow_emoji else ""
        if emoji:
            subject = f"{emoji} {template}".strip()
        else:
            subject = template
        
        subject = _truncate_subject(subject, subject_max)
        
        # 커밋 컨텍스트 생성
        context = CommitContext(
            type=ctype,
            scope=scope_guess,
            subject=subject,
            body=body_lines,
            emoji=_get_emoji_for_type(ctype),
            branch=branch,
            stats=summary.stats,
            files_changed=len(summary.changed),
            files_added=summary.stats['added'],
            files_modified=summary.stats['modified'],
            files_deleted=summary.stats['deleted']
        )
        
        # 사용자 정의 포맷이 있으면 그것을 사용, 없으면 기본 Conventional Commits 형식
        if custom_format:
            message = _apply_custom_format(custom_format, context)
        else:
            message = _format_conventional_message(context, breaking, lang)
        
        messages.append(message)

    # 6) 결과 반환
    result_text = ""
    
    # 디버그 정보 추가 (디버그 모드일 때)
    if debug:
        result_text += "🔍 **디버그 정보**\\n\\n"
        result_text += "\\n".join(debug_info)
        result_text += "\\n\\n---\\n\\n"
    
    # 커밋 메시지 후보들 추가
    if len(messages) == 1:
        result_text += messages[0]
    else:
        # 여러 후보를 번호를 붙여서 반환
        result_text += "\\n\\n---\\n\\n".join(f"[{i+1}]\\n{m}" for i, m in enumerate(messages))

    return [TextContent(type="text", text=result_text)]
