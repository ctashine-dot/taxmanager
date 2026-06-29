# Firebase RBAC 보안 규칙 (초안)

`backend/database.rules.rbac.json` — OAuth2/JWT(Firebase Auth) 기반 **RBAC + 감사 append-only** 규칙 초안.
현재 운영 중인 `database.rules.json`(개인 작업공간, per-uid)은 **그대로 유지**되며, 본 초안은 사무소 공유·감사 모델로 확장할 때 적용합니다.

## 노드 구조
| 경로 | 접근 | 비고 |
|---|---|---|
| `taxmanager/$uid` | 본인만 읽기/쓰기 | **현행 호환** — 기존 앱 동작 그대로 |
| `office/$officeId/clients` | 읽기: 사무소 소속 / 쓰기: admin·tax_manager·accountant | 거래처 공유 |
| `office/$officeId/payroll` | 위와 동일, `approved` 필드는 admin·tax_manager만 | 급여 |
| `office/$officeId/tax` | 위와 동일 | 세금/원천징수 |
| `office/$officeId/employees/$empUid` | 본인 또는 admin·tax_manager·auditor 읽기 | 직원 본인 명세 열람 |
| `office/$officeId/roles` | 읽기: 소속 / 쓰기: **admin만** | 역할/권한 관리 |
| `audit/$officeId/$logId` | 읽기: admin·auditor / **생성만(append-only)** | 수정·삭제 불가 |

## 역할 (커스텀 클레임)
규칙은 `auth.token.role` 과 `auth.token.officeId` 클레임을 사용합니다. 역할: `admin`, `tax_manager`, `accountant`, `employee`, `auditor`.

클레임은 **서버(Admin SDK)에서만** 설정해야 안전합니다 — 클라이언트에서 설정 불가.

```js
// Cloud Function (관리자만 호출) — 역할/사무소 클레임 부여
const functions = require('firebase-functions');
const admin = require('firebase-admin');
admin.initializeApp();

exports.setUserRole = functions.https.onCall(async (data, context) => {
  if (context.auth?.token?.role !== 'admin') {
    throw new functions.https.HttpsError('permission-denied', 'admin only');
  }
  const { uid, role, officeId } = data; // role ∈ admin|tax_manager|accountant|employee|auditor
  await admin.auth().setCustomUserClaims(uid, { role, officeId });
  return { ok: true };
});
```
> 클레임 변경 후 클라이언트는 `getIdToken(true)`로 토큰을 강제 갱신해야 반영됩니다.

## 감사 로그 append-only 보장
- `$logId` 쓰기는 `!data.exists() && newData.exists()` — **신규 생성만** 허용(수정·삭제 차단).
- `actor === auth.uid` 검증으로 위조 방지. `audit/$officeId` 상위 노드는 쓰기 불가(기본 거부)라 통째 덮어쓰기 불가.
- 클라이언트 측 변조 방지용. 강한 무결성(해시체인/WORM)은 서버 수집 단계에서 추가 권장.

## 적용 방법
```bash
# 검토 후 운영 규칙으로 교체하려면:
cp backend/database.rules.rbac.json database.rules.json
firebase deploy --only database
```
> ⚠️ 본 초안의 `office`/`audit` 모델을 실제로 쓰려면 앱이 해당 경로로 데이터를 읽고/쓰도록 마이그레이션해야 합니다(현재 앱은 `taxmanager/$uid` 사용). 단계적 이행 권장: ①역할 클레임 부여 → ②화면 권한 게이트 → ③공유 노드로 데이터 이전 → ④감사 기록.
