# 급여/세금 관리 시스템 — 현대화 아키텍처 설계

> 현재: 단일 `index.html`(SPA) + Firebase Auth/RTDB.
> 목표: **웹 클라이언트 + FastAPI 백엔드(PDF 파싱·세금 계산) + PostgreSQL** 의 계층형 구조.

## 1. 아키텍처 다이어그램 (텍스트)

```
┌──────────────────────────────────────────────────────────────────────┐
│  CLIENT (브라우저 / 모바일)                                            │
│  - SPA(현 index.html → 점진적으로 컴포넌트화) : 화면·RBAC 게이트       │
│  - PDF 업로드, 급여/신고 입력, 결과·명세서 표시                        │
└───────────────┬──────────────────────────────────────────────────────┘
                │ HTTPS (JWT Bearer)
                ▼
┌──────────────────────────────────────────────────────────────────────┐
│  API GATEWAY / Reverse Proxy (Nginx · Traefik)                         │
│  - TLS 종단, 라우팅, Rate-limit, JWT 서명·만료 1차 검증, CORS          │
└───────────────┬──────────────────────────────────────────────────────┘
                │
   ┌────────────┼───────────────────────────┬───────────────────────────┐
   ▼            ▼                           ▼                           ▼
┌────────┐ ┌──────────────────┐ ┌────────────────────────┐ ┌──────────────────┐
│ Auth   │ │ Core API         │ │ PDF Parsing Service     │ │ Tax Calc Service │
│ Service│ │ (FastAPI)        │ │ (FastAPI)               │ │ (FastAPI/모듈)   │
│OAuth2  │ │ - 거래처/급여/   │ │ - 업로드 수신           │ │ - 4대보험        │
│+JWT    │ │   세금 CRUD      │ │ - 텍스트추출→OCR        │ │ - 간이세액/소득세│
│RBAC    │ │ - 권한(RBAC)검증 │ │   (Tesseract)           │ │ - 부가세/원천세  │
│발급/검증│ │ - 비즈니스 규칙  │ │ - 키워드검증·chunking   │ │ - 순수함수 모듈  │
└───┬────┘ │ - 감사 인터셉터  │ │ - Claude 검토 호출      │ │   (단위테스트)   │
    │      └───────┬──────────┘ │ - 결과 병합             │ └────────┬─────────┘
    │              │            └──────┬───────┬─────────┘          │
    │              │                   │       │                    │
    │              │     (대용량/지연)  │       │ Claude API         │
    │              │      비동기 큐 ───►│       ▼ (외부)            │
    │              │   ┌──────────────┐ │  ┌──────────────┐         │
    │              │   │ Worker (RQ/  │ │  │ Anthropic    │         │
    │              │   │ Celery)      │◄┘  │ Claude API   │         │
    │              │   └──────┬───────┘    └──────────────┘         │
    ▼              ▼          ▼                                      ▼
┌──────────────────────────────────────────────────────────────────────┐
│  DATA LAYER                                                            │
│  ┌───────────────┐  ┌──────────────┐  ┌─────────────┐  ┌───────────┐ │
│  │ PostgreSQL    │  │ Redis        │  │ Object Store│  │ KMS / HSM │ │
│  │ users·payroll │  │ 캐시·큐·     │  │ (S3/MinIO)  │  │ 암호화 키 │ │
│  │ tax_records   │  │ 세션 denylist│  │ 원본 PDF·   │  │ (봉투암호)│ │
│  │ audit_logs    │  │              │  │ 명세서 산출 │  │           │ │
│  │ (RLS·암호화)  │  │              │  │             │  │           │ │
│  └───────────────┘  └──────────────┘  └─────────────┘  └───────────┘ │
└──────────────────────────────────────────────────────────────────────┘
        ▲ 관측: 구조화 로그 · 메트릭(Prometheus) · 추적(OpenTelemetry)
```

## 2. 계층별 역할

### ① Client (Presentation)
- 현 `index.html` SPA를 유지하되 API 호출 기반으로 전환(직접 Firebase 쓰기 → REST 호출). 장기적으로 컴포넌트화(React/Vue) 가능.
- **역할**: 입력·표시·화면 RBAC 게이트(서버 권한의 UX 보조). 신뢰 경계 밖 — 모든 검증은 서버가 재수행.

### ② API Gateway
- TLS 종단, 라우팅, **JWT 1차 검증**, Rate-limit, CORS, 요청 로깅. 서비스 위치를 클라이언트로부터 은닉.

### ③ Auth Service
- **OAuth2 Authorization Code + PKCE**, **JWT(RS256)** 발급, **refresh rotation**, **RBAC**(역할→권한). 토큰 폐기 denylist(Redis). (상세: 보안 설계 문서)

### ④ Core API (FastAPI)
- 거래처·급여·세금·신고 **CRUD + 비즈니스 규칙**. 요청마다 RBAC + **PostgreSQL RLS**(행 단위, 본인/부서 범위) 적용. 모든 변경을 **감사 인터셉터**가 `audit_logs`에 append.

### ⑤ PDF Parsing Service (FastAPI) — `tax_review.py` 확장
- **텍스트 추출 → 없으면 OCR(Tesseract) → 부실하면 Claude 비전** 3단계.
- **필수 키워드 검증**(유형 판별) → **토큰 chunking** → **Claude 검토 호출** → **결과 병합**.
- 대용량/지연 작업은 **비동기 큐(Worker)** 로 위임, 진행상태 폴링/웹훅.

### ⑥ Tax Calc Service / 모듈 (Python)
- **순수 함수 모듈**: 4대보험(국민연금·건강·장기요양·고용), 간이세액/종합소득세 누진, 부가세, 원천세, 지방소득세.
- 부수효과 없는 계산 로직 → **단위 테스트로 정확도 보증**(세율은 설정/버전 관리). Core API·PDF 서비스가 라이브러리로 호출하거나 독립 서비스로 분리.

### ⑦ Data Layer
- **PostgreSQL**: 정규화 스키마(users·payroll·tax_records·audit_logs), **RLS**(권한), 민감컬럼 **봉투암호화(KMS)**, 주민번호 **검색용 해시**.
- **Redis**: 캐시, 비동기 큐 브로커, 토큰 denylist, rate-limit 카운터.
- **Object Store(S3/MinIO)**: 원본 PDF, 생성 명세서/청구서. DB엔 메타데이터·참조만.
- **KMS/HSM**: 암호화 마스터키, 자동 회전.

### ⑧ Cross-cutting
- **보안**: OAuth2/JWT/RBAC/RLS + 전송·저장·필드 암호화(보안 설계 문서).
- **감사**: append-only + 해시체인 + WORM(법정 보존).
- **관측성**: 구조화 로그, 메트릭(Prometheus/Grafana), 분산추적(OpenTelemetry).

## 3. 핵심 데이터 흐름

### (A) 신고서 AI 검토
```
Client ──PDF업로드──► Gateway ─JWT검증─► PDF Service
  → Object Store에 원본 저장 → 텍스트추출/OCR → 키워드검증 → chunking
  → Claude API 검토 → 결과 병합 → tax_records/julgae 반영(Core API)
  → 감사로그 기록 → Client에 결과 카드 반환 (지연 시 작업ID로 폴링)
```

### (B) 급여 계산
```
Client ──급여입력──► Core API ─RBAC검증─► Tax Calc 모듈
  (기본급/수당 → 4대보험·소득세·지방세 자동계산) → payroll 저장(트랜잭션)
  → 감사로그 → 명세서 PDF 생성(Object Store) → Client 반환
```

## 4. 기술 스택 요약
| 계층 | 기술 |
|---|---|
| Client | 기존 SPA(점진 컴포넌트화), TS/React 옵션 |
| Gateway | Nginx/Traefik |
| Backend | **Python FastAPI**, Pydantic, Uvicorn |
| 비동기 | Celery/RQ + Redis |
| PDF/OCR | pdfplumber·PyMuPDF·Tesseract |
| AI | Anthropic Claude (claude-opus-4-8) |
| DB | **PostgreSQL** (+RLS, pgcrypto) |
| 캐시/큐 | Redis |
| 스토리지 | S3 / MinIO |
| 키관리 | AWS KMS / HashiCorp Vault |
| 배포 | Docker Compose → Kubernetes(확장 시) |
| 관측 | Prometheus·Grafana·OpenTelemetry·Sentry |

## 5. 현재 → 목표 이행 로드맵 (점진적·무중단)
1. **백엔드 분리 1단계**: PDF 검토를 FastAPI(`tax_review.py`)로 이전 — 브라우저는 API 호출. (Firebase는 그대로 사용)
2. **세금 계산 모듈화**: 4대보험·소득세 계산을 Python 모듈로 추출 + 단위테스트.
3. **데이터 마이그레이션**: Firebase RTDB → PostgreSQL(거래처·급여·세금). 듀얼라이트 기간 후 전환.
4. **인증 전환**: Firebase Auth → OAuth2/JWT + RBAC/RLS, 또는 Firebase 유지 시 Custom Claims로 RBAC.
5. **암호화·감사 강화**: 민감컬럼 KMS 암호화, 감사 해시체인.
6. **관측성·컨테이너화**: Docker화 → 필요 시 K8s.

> 각 단계는 독립 배포 가능하며, 1·2단계만으로도 “AI 검토 정확도·세금 계산 신뢰성”이 크게 개선됩니다(서버 OCR·키워드검증·테스트 가능 계산).
