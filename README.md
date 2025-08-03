# MY MCP Server

여러 개의 MCP 도구를 **한 서버에서** 제공하는 개인 스터디용 예제입니다.  

주요 기능:
- `summarize_youtube`: YouTube 자막을 가져와 **요약** 반환
- `transcript_stats`: 자막의 **통계**(세그먼트 수, 길이 등) 반환
- `ping`: 서버 **헬스체크**

> MCP(Model Context Protocol) SDK: `mcp` (Anthropic)  
> Transcript: `youtube-transcript-api`

---

## 디렉터리 구조

```
.
├─ server.py                  # 얇은 엔트리포인트
├─ mcp_server/
│  ├─ __init__.py
│  ├─ core.py                 # MCP 서버 생성/핸들러 + 레지스트리 연동
│  ├─ registry.py             # ToolRegistry (툴 스펙/핸들러 등록/라우팅)
│  ├─ utils/
│  │  ├─ __init__.py
│  │  ├─ youtube.py           # 자막 fetch + dict/객체 호환 + ID 추출
│  │  └─ text.py              # 요약 등 텍스트 유틸
│  └─ tools/
│     ├─ __init__.py          # ALL = [각 툴 모듈]
│     ├─ summarize_youtube.py # 요약 툴
│     ├─ transcript_stats.py  # 통계 툴
│     └─ ping.py              # 핑(헬스체크)
```

---

## 요구사항

- Python 3.10+
- `mcp` (예: `pip install mcp`)
- `youtube-transcript-api`

> 버전 확인:
>
> ```bash
> pip show mcp
> pip show youtube-transcript-api
> ```

---

## 설치 & 실행

```bash
# 1) (선택) 가상환경
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 2) 의존성 설치
pip install mcp youtube-transcript-api

# 3) 실행 (로그 레벨 조정 가능)
LOG_LEVEL=DEBUG python server.py
```

> 이 서버는 **stdio** 기반 MCP 서버입니다. MCP 클라이언트(예: IDE 플러그인, MCP 호환 앱)에서 stdio 서버로 등록해 호출합니다.

---

## 제공 도구(툴)

### 1) `summarize_youtube`

- 설명: YouTube 자막을 가져와 요약을 반환
- 입력(JSON Schema):
  ```json
  {
    "type": "object",
    "properties": {
      "url": { "type": "string", "description": "YouTube 비디오 URL" },
      "language": { "type": "string", "description": "자막 언어 코드(ko, en, ja 등)" }
    },
    "required": ["url"]
  }
  ```
- 출력: `TextContent` (요약 및 기본 정보)

### 2) `transcript_stats`

- 설명: 자막 통계(세그먼트 수, 길이 등)만 반환
- 입력(JSON Schema):
  ```json
  {
    "type": "object",
    "properties": {
      "url": { "type": "string" },
      "language": { "type": "string" }
    },
    "required": ["url"]
  }
  ```
- 출력: `TextContent`

### 3) `ping`

- 설명: 서버 헬스체크
- 입력: 없음

---

## 로깅

- 전역 로그 레벨은 환경변수 `LOG_LEVEL` 로 제어합니다. (`DEBUG` / `INFO` / `WARNING` / `ERROR`)
- 주요 로거
  - `mcp.entry` : 진입점(server.py)
  - `mcp.core` : MCP 서버 시작/중지, call_tool 라우팅/에러
  - `mcp.utils.youtube` : 자막 fetch 단계 로깅

예:
```bash
LOG_LEVEL=DEBUG python server.py
```

---

## 개발 팁

- **툴 추가 방법**
  1. `mcp_server/tools/your_tool.py` 생성
  2. `tool_spec` (mcp.types.Tool), `async def handle(arguments)` 구현
  3. `mcp_server/tools/__init__.py` 의 `ALL` 목록에 모듈을 추가

- **YouTube 자막 주의**
  - `youtube-transcript-api` 버전에 따라 각 세그먼트가 `dict` 또는 `FetchedTranscriptSnippet(객체)` 일 수 있습니다.  
    본 프로젝트는 공통 접근 헬퍼로 두 형태 모두 지원합니다.

---

## Claude(클로드) 데스크톱에 등록하기

Claude Desktop에서 이 MCP 서버를 사용하려면 **데스크톱 설정 파일**에 MCP 서버를 등록해야 합니다.

### 1) 설정 파일 위치
운영체제별 기본 경로는 다음 중 하나입니다.
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **Linux**: `~/.config/Claude/claude_desktop_config.json`

> 파일이 없다면 직접 생성해도 됩니다. JSON 포맷을 반드시 지켜주세요.

### 2) 로컬 파이썬 프로세스로 등록 (권장: 개발용)
서버를 로컬에서 직접 실행하는 방식입니다. `cwd`를 프로젝트 루트로 맞춰주세요.

```jsonc
{
  // 기존 설정이 있다면 병합하세요
  "mcpServers": {
    "my-mcp-server": {
      "command": "python",
      "args": ["server.py"],
      "cwd": "/Users/user/Desktop/DEV/my_mcp_server",
      "env": {
        "LOG_LEVEL": "INFO"
      }
    }
  }
}
```

- `command`는 `python` 또는 `python3`를 사용하세요(환경에 맞게).
- 가상환경을 쓰는 경우 `command`에 가상환경의 파이썬 경로를 지정해도 됩니다. (예: `"/Users/user/Desktop/DEV/my_mcp_server/.venv/bin/python"`)

### 3) Docker 컨테이너로 등록 (배포/격리 실행)
이미지를 빌드한 뒤, Claude가 컨테이너를 **STDIN/STDOUT**로 구동하도록 설정합니다.

```jsonc
{
  "mcpServers": {
    "my-mcp-server-docker": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "-e", "LOG_LEVEL=INFO",
        "my-mcp-server:latest"
      ]
    }
  }
}
```

> `-i` 옵션이 중요합니다(표준입력을 열어 MCP가 통신할 수 있게 함). 필요 시 `--pull=always`를 추가해 최신 이미지를 받도록 할 수 있습니다.

### 4) 적용 방법
1. `claude_desktop_config.json` 수정/저장
2. Claude Desktop을 **재시작**
3. Claude 대화창에서 `@` 또는 사이드패널의 MCP 섹션에서 `my-mcp-server`(또는 설정한 이름)를 확인 후 사용

> 등록 명은 자유롭게 정해도 되지만, README의 예시와 동일하게 쓰면 문서와 일치해 편합니다.

## 트러블슈팅

- **`'FetchedTranscriptSnippet' object is not subscriptable`**
  - 원인: 세그먼트가 dict가 아닐 때 `entry['text']`로 접근
  - 해결: 공통 헬퍼를 통해 `getattr`/`dict.get` 모두 대응 (이미 반영됨)

- **`Server.list_tools() takes 1 positional argument but 2 were given`**
  - 원인: MCP 저수준 `Server`의 데코레이터는 **팩토리 함수**이므로 괄호 필요/불필요 혼동
  - 해결: 현재 코드는 `@self.server.list_tools()` / `@self.server.call_tool()` 형태로 정상 동작하도록 구성

- 자막이 없는 영상 / 지역 제한 / 비공개
  - “사용 가능한 자막을 찾을 수 없습니다” 메시지를 반환합니다. 다른 영상 또는 언어코드로 재시도하세요.

---

## 라이선스

MIT (각 라이브러리의 라이선스는 해당 저장소 참고)