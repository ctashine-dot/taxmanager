# CI/CD 파이프라인 설계 (GitLab)

급여/세금 관리 시스템(FastAPI + PostgreSQL + 정적 프론트엔드)용 GitLab CI/CD.
예시 파이프라인: `backend/gitlab-ci.example.yml` (GitLab 이전 시 루트 `.gitlab-ci.yml`로 사용).

## 파이프라인 흐름
```
[push/MR] → build → test → security → package → deploy
                                                 ├ staging  (main 자동)
                                                 └ production(태그 + 수동 승인)
```
- 단계는 순차 실행, 같은 단계 내 잡은 병렬. `needs:`로 DAG 최적화(불필요한 대기 제거).
- 실패 시 다음 단계 차단(보안 잡은 정책에 따라 `allow_failure` 조정).

## 단계별 실행 순서·도구

### 1) build — 의존성·정적 검증
| 잡 | 도구 | 역할 |
|---|---|---|
| `build:backend` | python:3.12, **ruff**(린트), **mypy**(타입) | venv 구성·의존성 설치·정적 검사, `.venv` 아티팩트 |
| `build:frontend` | node:22 | `index.html` 인라인 스크립트 구문 검사(번들/압축 확장 가능) |

### 2) test — 단위·통합
| 잡 | 도구 | 역할 |
|---|---|---|
| `test:unit` | **pytest** + pytest-cov | 세금 계산 모듈(4대보험·소득세)·파싱 로직(Claude 목) 단위테스트, 커버리지 리포트(JUnit/Cobertura) |
| `test:integration` | pytest + **postgres:16 서비스** | API + DB(RLS 권한) 통합 테스트 |

### 3) security — 취약점·시크릿 검사
| 검사 | 도구 |
|---|---|
| SAST(코드 정적분석) | GitLab **SAST**(Semgrep 기반) 템플릿 |
| 시크릿 유출 | GitLab **Secret-Detection**(Gitleaks) |
| 의존성 취약점 | GitLab **Dependency-Scanning** + `security:pip-audit`(pip-audit) |
> 결과는 MR의 보안 위젯에 표시. 차단 정책은 조직 보안 기준에 맞춰 `allow_failure`/승인 규칙으로 조정.

### 4) package — Docker 이미지 생성·스캔
| 잡 | 도구 | 역할 |
|---|---|---|
| `package:image` | **Kaniko**(데몬리스 빌드) | `backend/Dockerfile`로 이미지 빌드 → **GitLab Container Registry** 푸시(`$IMAGE:$SHA`, `:latest`). `main`/태그에서만 |
| `container_scanning` | GitLab **Container-Scanning**(Trivy) | 빌드된 이미지 취약점 스캔 |
> Kaniko는 Docker 데몬(특권) 없이 K8s 러너에서 안전하게 이미지 빌드.

### 5) deploy — Kubernetes 배포
| 잡 | 도구 | 트리거 |
|---|---|---|
| `deploy:staging` | **Helm** `upgrade --install` | `main` 머지 시 **자동** (namespace `staging`) |
| `deploy:production` | Helm | **태그 푸시 + 수동 승인(manual)** (namespace `production`) |
- GitLab **Environments**로 staging/production 추적, URL·배포 이력·**원클릭 롤백** 제공.
- 시크릿(DB 접속·KMS·레지스트리)은 **GitLab CI/CD Variables(Masked·Protected)** 또는 외부 Vault로 주입.

## 운영 모범사례
- **캐시**: pip 캐시·venv 키 캐싱으로 빌드 단축.
- **DAG(`needs`)**: 프론트/백엔드 병렬, 테스트 통과분만 패키징.
- **불변 태그**: 이미지 태그에 커밋 SHA → 재현·롤백 용이.
- **승인 게이트**: production은 수동 + 보호 브랜치/태그·환경 보호.
- **품질 게이트**: 커버리지 임계·SAST High 차단(정책).
- **롤백**: `helm rollback` 또는 환경 위젯에서 이전 배포로 즉시 복구.

## 현행(GitHub Pages)과의 관계
현재 앱은 GitHub Pages(main 푸시 시 정적 배포)로 운영됩니다. 본 설계는 **백엔드(FastAPI) 도입 시** GitLab으로 이전하거나, GitHub Actions로 동일 단계를 재현(actions: build/test/CodeQL·Trivy/Buildx/`kubectl`)할 수 있습니다. 단계·도구 구성은 동일합니다.
