# 세무사랑 자동화 에이전트

taxmanager 웹앱(`index.html`)의 "🤖 세무사랑 앱에서 자동으로 불러오기" 기능을
지원하는 로컬 프로그램. 브라우저는 보안 샌드박스 때문에 세무사랑 같은
데스크톱 프로그램을 직접 제어할 수 없으므로, **세무사랑이 설치된 바로 그 PC**에서
이 에이전트를 별도 프로그램으로 실행해 둔다. 웹앱은 `http://127.0.0.1:<port>`로
로컬 요청을 보내 에이전트에게 작업을 시키고, 결과 파일을 돌려받아 기존
가져오기 파이프라인(`parseImportFile`)에 그대로 흘려보낸다.

## 동작 모드

- **watch (기본, 권장 시작점)**: 세무사랑에서 사람이 직접 [엑셀저장]을 누르고 나면,
  에이전트가 지정된 폴더(`watch_dir`)에서 방금 생성된 파일을 찾아 웹앱에 돌려준다.
  세무사랑 화면을 직접 조작하지 않으므로 안전하고 버전 변경에도 안 깨진다.
- **automate**: 에이전트가 `pywinauto`로 세무사랑 창의 메뉴를 직접 클릭해
  [엑셀저장]까지 수행한 뒤 결과 파일을 돌려준다. 세무사랑의 정확한 창 제목·메뉴
  이름을 알아야 하며(`inspect_semusarang.py`로 확인), 버전 업데이트 시 메뉴 구조가
  바뀌면 다시 조정해야 한다.

두 모드 모두 실제 "신고서 제출"은 하지 않는다 — 데이터를 불러와 앱에 저장하는
용도로 범위를 한정했다.

## 설치 (세무사랑이 설치된 Windows PC에서)

```bash
cd automation
pip install -r requirements.txt   # watch 모드만 쓸 거면 pywinauto 없이도 동작함
cp config.example.json config.json
```

`config.json`을 열어 아래 항목을 실제 환경에 맞게 수정한다.

| 필드 | 설명 |
|---|---|
| `token` | 웹앱과 에이전트 사이 인증 토큰. 최초 실행 시 자동 생성되며, 웹앱의 "연결 설정"에 그대로 입력하면 된다. |
| `allowed_origin` | taxmanager 웹앱의 실제 접속 주소(예: `https://xxx.web.app`). 이 origin에서 온 요청만 허용한다. |
| `watch_dir` | 세무사랑이 엑셀을 저장하는(또는 사용자가 늘 저장하는) 폴더. |
| `file_patterns` | 자료 종류별로 찾을 파일명 패턴(glob). |
| `max_age_minutes` | 이보다 오래된 파일은 "방금 내보낸 파일"로 인정하지 않는다. |
| `window_title_regex`, `menu_paths` | automate 모드 전용. `inspect_semusarang.py`로 확인 후 채운다. |

`config.json`이 없는 상태로 처음 실행하면 자동으로 생성되고 토큰이 콘솔에
출력된다.

## 실행

```bash
python semusarang_agent.py
```

정상 실행되면 `http://127.0.0.1:5987` 에서 대기한다. 이 창을 켜 둔 채로
taxmanager 웹앱에서 가져오기 모달 → "연결 설정"에 주소/토큰을 입력하고,
"🤖 세무사랑 앱에서 자동으로 불러오기" 버튼을 누르면 된다.

## automate 모드로 전환하려면

1. 세무사랑을 실행한 상태에서:
   ```bash
   python inspect_semusarang.py --list
   ```
   출력된 창 제목 중 세무사랑 창을 찾아 `config.json`의 `window_title_regex`에 반영.

2. ```bash
   python inspect_semusarang.py --title "세무사랑"
   ```
   `control_tree.txt`가 생성된다. 여기서 원하는 메뉴(예: 기초 → 거래처 관리 →
   거래처 현황 → 엑셀)의 정확한 이름을 확인해 `config.json`의 `menu_paths`에
   순서대로 나열한다.

3. `config.json`의 `mode`를 `"automate"`로 변경 후 에이전트를 재시작한다.

메뉴 구조는 세무사랑 화면 구성에 따라 트리뷰/버튼/리본 메뉴 등으로 다를 수
있어, `semusarang_agent.py`의 `automate_semusarang()` 함수(메뉴 클릭 방식)를
실제 화면에 맞춰 조정해야 할 수 있다.

## 보안 설계

- **127.0.0.1(로컬)에만 바인딩** — 외부 네트워크에서 접근 불가. 절대 포트포워딩하지
  말 것.
- **토큰 인증** — 모든 요청에 `X-Agent-Token` 헤더가 필요하며, 다른 웹사이트가
  브라우저를 통해 몰래 이 에이전트를 두드리는 것(로컬 포트 스캔/CSRF)을 막는다.
- **CORS origin 고정** — `allowed_origin`에 지정한 taxmanager 웹앱 주소에서
  온 요청만 허용한다.
- 에이전트는 파일을 **읽기만** 하며(watch 모드), 세무사랑에 데이터를 쓰거나
  실제 국세청 신고를 접수하는 동작은 포함하지 않는다.

## 웹앱과의 통신 규약

- `GET /health` → `{"status":"ok","mode":"watch"}`
- `POST /fetch` (헤더 `X-Agent-Token: <token>`, 바디 `{"type":"clients"|"invoice"}`)
  → `{"filename":"...", "content_base64":"..."}`
  실패 시 `{"error":"..."}` 와 함께 4xx/5xx.
