"""
MCP Tool: commit_suggester

이 모듈은 **깃 커밋 메시지 자동 생성** 도구입니다. 
클라이언트(LLM)가 call_tool로 호출하면, 현재 레포의 변경 사항을 요약하여
규칙(예: Conventional Commits)에 맞는 커밋 메시지 후보들을 만들어 줍니다.

새로운 기능: 사용자 정의 포맷 지원
- 사용자가 원하는 커밋 메시지 포맷을 템플릿으로 제공할 수 있습니다
- 템플릿 변수를 사용해 동적으로 값을 치환합니다

지원하는 템플릿 변수:
- {type}: 추정된 커밋 타입 (feat, fix, docs 등)
- {scope}: 추정된 스코프
- {subject}: 생성된 주제
- {emoji}: 타입별 이모지
- {files_changed}: 총 변경된 파일 수
- {files_added}: 추가된 파일 수
- {files_modified}: 수정된 파일 수
- {files_deleted}: 삭제된 파일 수
- {branch}: 현재 브랜치명
- {body}: 생성된 본문

예시 포맷:
- "{type}({scope}): {subject}"
- "[{type}] {subject} - {files_changed} files changed"
- "{emoji} {type}: {subject}\\n\\n{body}"
- "🚀 {branch} | {type}: {subject}"

문제 해결:
- git 명령어 실행 가능 여부 사전 체크
- git repository 여부 확인
- 상세한 오류 진단 및 해결 가이드 제공
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
# tool_spec: LLM이 도구를 선택/호출할 때 참고하는 "메뉴판" 정의
# ---------------------------------------------------------------------------

tool_spec = Tool(
    name="commit_suggester",
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
    """Git diff 결과를 요약한 데이터 구조"""
    changed: List[Tuple[str, str]]  # [(status, path)] status: A/M/D/R/C...
    stats: Dict[str, int]           # 간단한 집계: added/modified/deleted/renamed


@dataclass
class CommitContext:
    """커밋 메시지 생성에 필요한 모든 컨텍스트 정보"""
    type: str
    scope: Optional[str]
    subject: str
    body: List[str]
    emoji: str
    branch: Optional[str]
    stats: Dict[str, int]
    files_changed: int
    files_added: int
    files_modified: int
    files_deleted: int


async def _check_git_availability() -> Tuple[bool, str]:
    """
    git 명령어가 사용 가능한지 확인합니다.
    
    반환값:
        Tuple[bool, str]: (사용 가능 여부, 상세 메시지)
    """
    # 1. git 실행 파일이 PATH에 있는지 확인
    git_path = shutil.which("git")
    if not git_path:
        return False, "git 명령어를 찾을 수 없습니다. Git이 설치되어 있고 PATH에 포함되어 있는지 확인하세요."
    
    # 2. git 버전 확인으로 실행 가능 여부 테스트
    try:
        result = subprocess.run(
            [git_path, "--version"], 
            capture_output=True, 
            text=True, 
            timeout=5
        )
        if result.returncode == 0:
            return True, f"Git 사용 가능 (경로: {git_path}, 버전: {result.stdout.strip()})"
        else:
            return False, f"git --version 실행 실패: {result.stderr}"
    except subprocess.TimeoutExpired:
        return False, "git 명령어 실행 시간 초과"
    except Exception as e:
        return False, f"git 실행 중 예외 발생: {e}"


async def _check_git_repository(cwd: Optional[str] = None) -> Tuple[bool, str]:
    """
    현재 디렉토리가 git repository인지 확인합니다.
    
    매개변수:
        cwd: 확인할 디렉토리 (None이면 현재 디렉토리)
    
    반환값:
        Tuple[bool, str]: (git repo 여부, 상세 메시지)
    """
    check_dir = Path(cwd) if cwd else Path.cwd()
    
    # .git 디렉토리 또는 파일 확인
    git_path = check_dir / ".git"
    if git_path.exists():
        return True, f"Git repository 확인됨 (경로: {check_dir})"
    
    # 상위 디렉토리로 올라가면서 .git 찾기
    current = check_dir
    for parent in current.parents:
        git_path = parent / ".git"
        if git_path.exists():
            return True, f"Git repository 확인됨 (상위 경로: {parent})"
    
    return False, f"Git repository가 아닙니다. 현재 경로: {check_dir}\\n'git init' 또는 git repository가 있는 디렉토리에서 실행하세요."


async def _run_git_safe(*args: str, cwd: Optional[str] = None, timeout: int = 10) -> Tuple[int, str, str]:
    """
    안전하게 git 명령을 실행하고 (returncode, stdout, stderr)를 반환합니다.
    
    보안 고려사항:
    - 쉘을 통하지 않고 인자 배열로 실행하여 보안을 높입니다
    - timeout(초) 안에 끝나지 않으면 취소합니다
    - git 실행 가능 여부를 사전 체크합니다
    
    매개변수:
        *args: git 명령의 인자들
        cwd: 실행할 디렉토리 (None이면 현재 디렉토리)
        timeout: 타임아웃 시간(초)
    
    반환값:
        Tuple[int, str, str]: (리턴코드, 표준출력, 표준에러)
    """
    # 1. git 사용 가능 여부 체크
    git_available, git_message = await _check_git_availability()
    if not git_available:
        logger.error(f"Git 사용 불가: {git_message}")
        return 127, "", git_message
    
    # 2. git repository 여부 체크
    if args and args[0] not in ["--version", "init"]:  # init이나 version 체크가 아닌 경우만
        repo_available, repo_message = await _check_git_repository(cwd)
        if not repo_available:
            logger.error(f"Git repository 없음: {repo_message}")
            return 128, "", repo_message
    
    # 3. 실제 git 명령 실행
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", *args,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        
        try:
            out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return (
                proc.returncode, 
                out_b.decode("utf-8", "ignore"), 
                err_b.decode("utf-8", "ignore")
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()  # 프로세스 완전 정리
            return 124, "", f"git {' '.join(args)} 시간 초과 ({timeout}초)"
            
    except FileNotFoundError:
        return 127, "", "git 명령어를 찾을 수 없습니다"
    except PermissionError:
        return 126, "", "git 명령어 실행 권한이 없습니다"
    except Exception as e:
        logger.exception(f"git 명령 실행 중 예외: {e}")
        return 1, "", f"git 명령 실행 중 예외: {e}"


async def _get_current_branch(cwd: Optional[str] = None) -> Optional[str]:
    """
    현재 체크아웃된 브랜치 이름을 반환합니다.
    
    반환값:
        Optional[str]: 브랜치명, detached HEAD 또는 실패 시 None
    """
    code, out, err = await _run_git_safe("rev-parse", "--abbrev-ref", "HEAD", cwd=cwd)
    if code != 0:
        logger.warning(f"브랜치 확인 실패: {err}")
        return None
    branch = out.strip()
    if not branch or branch == "HEAD":  # detached HEAD
        return None
    return branch


def _summarize_status(lines: List[str]) -> DiffSummary:
    """
    git diff --name-status 형식의 라인을 받아 간단한 통계를 계산합니다.
    
    매개변수:
        lines: git diff --name-status 출력 라인들
    
    반환값:
        DiffSummary: 변경된 파일들과 통계 정보
    """
    changed: List[Tuple[str, str]] = []
    stats = {"added": 0, "modified": 0, "deleted": 0, "renamed": 0}
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # 예) "A\tsrc/app.py"  "M\tREADME.md"  "D\told.txt"  "R100\told.py\tnew.py"
        parts = line.split("\t")
        if len(parts) < 2:
            continue
            
        status = parts[0]
        path = parts[-1]  # rename의 경우 마지막이 새 경로
        s = status[0]
        
        if s == "A":
            stats["added"] += 1
        elif s == "M":
            stats["modified"] += 1
        elif s == "D":
            stats["deleted"] += 1
        elif s == "R":
            stats["renamed"] += 1
            
        changed.append((s, path))
    
    return DiffSummary(changed=changed, stats=stats)


def _infer_type_and_scope(changed: List[Tuple[str, str]]) -> Tuple[str, Optional[str]]:
    """
    간단한 휴리스틱으로 type/scope를 추정합니다.
    
    파일 경로/이름/확장자에 따라 커밋 타입을 추정하고,
    최상위 디렉토리를 기반으로 스코프를 추정합니다.
    
    매개변수:
        changed: [(상태, 경로)] 형태의 변경된 파일 목록
    
    반환값:
        Tuple[str, Optional[str]]: (추정된 타입, 추정된 스코프)
    """
    if not changed:
        return "chore", None

    paths = [p for _, p in changed]
    lower_blob = "\\n".join(paths).lower()
    
    # 타입 추정 (우선순위 순)
    import re
    if re.search(r"(fix|bug|error|exception|hotfix)", lower_blob):
        ctype = "fix"
    elif re.search(r"(doc|readme|mkdocs|docs/|\\.md$)", lower_blob):
        ctype = "docs"
    elif re.search(r"(test|spec|pytest|jest|\\.test\\.|__tests__|\\.spec\\.)", lower_blob):
        ctype = "test"
    elif re.search(r"(build|dockerfile|docker-compose|\\.lock$|package\\.json|requirements\\.txt)", lower_blob):
        ctype = "build"
    elif re.search(r"(refactor|rename|cleanup|restructure)", lower_blob):
        ctype = "refactor"
    elif re.search(r"(perf|benchmark|optimi[s|z]e)", lower_blob):
        ctype = "perf"
    else:
        ctype = "feat"

    # scope 추정: 최상위 디렉토리
    # 예) src/app/main.py -> scope=src,  tools/commit_suggester.py -> scope=tools
    scope = None
    for p in paths:
        parts = p.split("/")
        if len(parts) > 1 and parts[0] not in (".", ".."):
            scope = parts[0]
            break
    
    return ctype, scope


def _get_emoji_for_type(ctype: str) -> str:
    """
    커밋 타입에 해당하는 이모지를 반환합니다.
    
    매개변수:
        ctype: 커밋 타입
    
    반환값:
        str: 해당하는 이모지
    """
    emoji_map = {
        "feat": "✨",
        "fix": "🐛", 
        "docs": "📝",
        "refactor": "♻️",
        "test": "✅",
        "build": "🏗️",
        "perf": "🚀",
        "chore": "🧹",
        "ci": "🔧",
        "style": "💄"
    }
    return emoji_map.get(ctype, "📝")


def _generate_subject_templates(ctype: str, lang: str) -> List[str]:
    """
    커밋 타입과 언어에 따른 주제 템플릿들을 생성합니다.
    
    매개변수:
        ctype: 커밋 타입
        lang: 언어 ("ko" 또는 "en")
    
    반환값:
        List[str]: 주제 템플릿 목록
    """
    if lang == "ko":
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
    
    return templates.get(ctype, ["update"] if lang == "en" else ["업데이트"])


def _truncate_subject(text: str, max_len: int) -> str:
    """
    subject 줄 길이를 제한합니다. 너무 길면 말줄임표를 붙입니다.
    
    매개변수:
        text: 원본 텍스트
        max_len: 최대 길이
    
    반환값:
        str: 길이가 조정된 텍스트
    """
    text = text.strip()
    return text if len(text) <= max_len else text[: max(0, max_len - 1)] + "…"


def _apply_custom_format(format_template: str, context: CommitContext) -> str:
    """
    사용자 정의 포맷 템플릿에 컨텍스트 값들을 치환합니다.
    
    매개변수:
        format_template: 사용자가 제공한 포맷 템플릿
        context: 치환할 값들이 담긴 컨텍스트
    
    반환값:
        str: 포맷이 적용된 최종 커밋 메시지
    """
    # 기본 치환 변수들
    replacements = {
        "type": context.type,
        "scope": context.scope or "",
        "subject": context.subject,
        "emoji": context.emoji,
        "branch": context.branch or "",
        "files_changed": str(context.files_changed),
        "files_added": str(context.files_added),
        "files_modified": str(context.files_modified),
        "files_deleted": str(context.files_deleted),
        "body": "\\n".join(context.body) if context.body else ""
    }
    
    # 스코프가 있는 경우의 조건부 포맷팅
    scope_part = f"({context.scope})" if context.scope else ""
    replacements["scope_with_parens"] = scope_part
    
    # 템플릿 치환
    result = format_template
    for key, value in replacements.items():
        result = result.replace(f"{{{key}}}", str(value))
    
    # 이스케이프 문자 처리
    result = result.replace("\\\\n", "\\n").replace("\\\\t", "\\t")
    
    return result


def _format_conventional_message(context: CommitContext, breaking: bool, lang: str) -> str:
    """
    Conventional Commits 형식으로 메시지를 포맷합니다.
    
    매개변수:
        context: 커밋 컨텍스트
        breaking: BREAKING CHANGE 포함 여부
        lang: 언어
    
    반환값:
        str: 포맷된 커밋 메시지
    """
    # 헤더 구성
    scope_part = f"({context.scope})" if context.scope else ""
    head = f"{context.type}{scope_part}: {context.subject}"
    
    parts = [head]
    
    # 본문 추가
    if context.body:
        parts.append("")
        parts.extend(context.body)
    
    # Breaking change footer 추가
    if breaking:
        parts.append("")
        if lang == "ko":
            parts.append("BREAKING CHANGE: 하위 호환되지 않는 변경")
        else:
            parts.append("BREAKING CHANGE: behavior changed in a backward-incompatible way")
    
    return "\\n".join(parts)


async def handle(arguments: Dict[str, Any]) -> List[TextContent]:
    """
    MCP 클라이언트 요청을 처리하여 커밋 메시지 후보들을 생성합니다.
    
    매개변수:
        arguments: MCP 클라이언트에서 전달된 인자들
    
    반환값:
        List[TextContent]: 생성된 커밋 메시지 후보들
    """
    # 0) 입력 파싱/기본값 설정
    mode = (arguments.get("mode") or "staged").lower()
    rng = arguments.get("range")
    custom_format = arguments.get("format")  # 새로운 사용자 정의 포맷
    rules = arguments.get("rules") or {}
    lang = (arguments.get("language") or "ko").lower()
    suggestions = arguments.get("suggestions") or 3
    breaking = bool(arguments.get("breaking") or False)
    debug = bool(arguments.get("debug") or False)

    # 사용자 지정 경로 처리: 제공되면 그 경로에서 git 명령을 실행
    path_arg = arguments.get("path")
    if path_arg:
        if not isinstance(path_arg, str):
            return [TextContent(type="text", text="❌ 'path'는 문자열이어야 합니다. 예: path: './' 또는 'subdir/'")]
        candidate = Path(path_arg)
        if not candidate.is_absolute():
            candidate = (Path.cwd() / candidate).resolve()
        if not candidate.exists() or not candidate.is_dir():
            return [TextContent(type="text", text=f"❌ 지정한 경로가 존재하지 않거나 디렉토리가 아닙니다: {candidate}")]
        repo_check_cwd: Optional[str] = str(candidate)
    else:
        repo_check_cwd = None

    # 디버그 정보 수집
    debug_info = []
    if debug:
        debug_info.append(f"🔍 디버그 모드 활성화")
        debug_info.append(f"📂 현재 작업 디렉토리: {Path.cwd()}")
        debug_info.append(f"🎯 모드: {mode}")
        debug_info.append(f"📌 경로 기준: {repo_check_cwd or Path.cwd()}")

    # 규칙 기본값 (Conventional Commit 스타일)
    allowed_types = rules.get("types") or ["feat","fix","docs","refactor","test","chore","build","perf","ci"]
    require_scope = bool(rules.get("require_scope") or False)
    subject_max = int(rules.get("subject_max") or 72)
    allow_emoji = bool(rules.get("allow_emoji") or False)
    scope_enum = rules.get("scope_enum")

    # 1) Git 환경 사전 체크
    git_available, git_message = await _check_git_availability()
    if debug:
        debug_info.append(f"🔧 Git 체크: {git_message}")
    
    if not git_available:
        error_msg = f"❌ Git 설정 문제\\n\\n{git_message}\\n\\n해결 방법:\\n1. Git 설치 확인: https://git-scm.com/\\n2. PATH 환경변수에 git 포함 확인\\n3. 터미널에서 'git --version' 명령 테스트"
        if debug:
            error_msg += f"\\n\\n🔍 디버그 정보:\\n" + "\\n".join(debug_info)
        return [TextContent(type="text", text=error_msg)]

    repo_available, repo_message = await _check_git_repository(cwd=repo_check_cwd)
    if debug:
        debug_info.append(f"📁 Repository 체크: {repo_message}")
    
    if not repo_available:
        error_msg = f"❌ Git Repository 문제\\n\\n{repo_message}\\n\\n해결 방법:\\n1. git repository가 있는 디렉토리로 이동\\n2. 새 repository 초기화: 'git init'\\n3. 기존 repository 클론: 'git clone <URL>'"
        if debug:
            error_msg += f"\\n\\n🔍 디버그 정보:\\n" + "\\n".join(debug_info)
        return [TextContent(type="text", text=error_msg)]

    # 2) Git 변경사항 수집
    if mode == "staged":
        code, out, err = await _run_git_safe("diff", "--staged", "--name-status", cwd=repo_check_cwd)
    elif mode == "working":
        code, out, err = await _run_git_safe("diff", "--name-status", cwd=repo_check_cwd)
    elif mode == "range":
        if not rng:
            return [TextContent(type="text", text="❌ mode=range 인데 range 값이 없습니다. 예: HEAD~3..HEAD")]
        code, out, err = await _run_git_safe("diff", "--name-status", rng, cwd=repo_check_cwd)
    else:
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
