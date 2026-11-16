# M3 P1 설계: 화면을 소유하지 않는(touches) UI 배치의 명세·계획·증거

상태: **구현됨**(엔진 `product-build`). 근거: `m3-validation-backlog.md` P1-1~P1-4. 프로젝트 사례는 재현 근거일 뿐이며, 규칙은 프로젝트·프레임워크와 무관합니다.

## 1. 문제(현재 구현 분석)

계획은 화면을 한 배치만 **소유**(`screens`)하고, 다른 배치는 **영향**(`touches`)만 갖게 합니다(이 규칙은 유지). UI 흐름(M3.2–M3.5)은 소유 화면만 다뤘습니다.

| 명령 | 소유 화면 | touches 화면(변경 전) |
|---|---|---|
| `ui-brief` | 02 블록·상태·행동·AC·VD(화면·화면 CMP 관련)·레이아웃 | 이름·상태 ID 목록만. VD·레이아웃·AC·배치 CMP와의 관계 없음 |
| `ui-plan-validate` | 화면별 tree·states·interactions·data·acs 필수 | 검사 대상 없음 → `screens: {}`로 통과 |
| `verify`(UI 증거) | 정의된 상태별 판정, Must 화면 상태는 E2 필수 | 판정 없음. 브라우저 결과는 "소유 화면 아님(증거로 쓰지 않음)" |
| `ui-review` | 필수 상태 미충족 등이 차단 | 볼 것이 없어도 `ready: true` |
| `evidence-manual` | 소유 화면 상태만 | 기록 불가(`unknown_state`) |

전역 VD는 SCR·CMP 관련이 **하나도 없는** VD만이라, 배치가 재사용·정비하는 CMP에 연결된 VD는 touches 배치 Brief에서 빠졌습니다.

## 2. 정책 판단

| | ① 기본 경고 + strict 차단 | ② 신규 touches 배치 기본 차단 + 기존 계획 호환 예외 |
|---|---|---|
| 공백 해소 | 기본값에서는 해소되지 않음(경고를 무시하면 증거 0으로 승인까지 감) | 기본값에서 해소 |
| 기존 프로젝트 | 영향 없음 | 예외 경로가 정확해야 함 |
| 우회 위험 | 프로필 한 줄(strict 끄기)로 원상태 | 예외는 원장 결정(사용자)만 |

**선택: ②.** 백로그의 공백(P1-2·P1-3)은 "경고를 남기고 통과"가 바로 원인이었습니다. 기존 프로젝트 영향은 아래 호환 규칙으로 막습니다(시각 기준이 아니라 데이터 기준).

호환 규칙
- **Brief digest 불변**: touches 명세는 새 블록 `touched`에 담고, `layout`처럼 Brief digest 계산에서 제외합니다(자체 digest로 무결성 확인). 원천 문서(02·04·05·07·계획·대응표)의 해시는 이미 `sources`에 있어, 명세가 바뀌면 digest는 여전히 바뀝니다. → 기존 Brief·UI Plan 검증 기록이 이 변경만으로 낡지 않습니다.
- **이미 시작·완료된 배치**(상태가 시작 이후)이고 UI Plan에 `touched` 키가 없으면 **legacy**: touches 계획 규칙은 경고(`touched_plan_legacy`)로만 보고합니다.
- **아직 시작하지 않은 touches 배치**: `batch-start`가 검증 기록의 규칙 버전(`rules: touched-v1`)을 요구합니다. 이전 엔진으로 검증된 기록이면 다시 `ui-plan-validate`해야 시작할 수 있습니다(새 규칙 적용).
- **기존 verified 배치**: 상태를 바꾸지 않습니다. 무효화 기준(`verification.ui.basis`)에 새 키 `touched`를 넣되, 이전 기록에 그 키가 없으면 비교하지 않습니다. UI 검토(`ui-review`)는 touches 증거 판정이 없는 이전 검증에 대해 차단하지 않고 경고(`touched_not_evaluated`)만 합니다. 다시 `verify`하면(사용자의 명시적 실행) 새 판정이 적용됩니다.
- 화면을 소유만 하는 배치(touches 없음)는 동작·digest·판정이 모두 이전과 같습니다.

## 3. 데이터 구조

### UI Brief(`pb-ui-brief/v1`, 선택 블록 `touched`, touches가 있는 배치만)

```json
"touched": {
  "screens": { "SCR-003": {
      "name": "...", "route": "...", "owner": "B2", "priority": "Must",
      "states": [ { "id": "SCR-003-ST1", "label": "...", "behavior": "...", "defined": true } ],
      "components": ["CMP-001", "CMP-003"],
      "affected_via": ["CMP-001"],          // 배치가 다루는 CMP(reuse·new) ∩ 화면 CMP = 실제 수정 영향 후보
      "referenced": ["CMP-003"],            // 화면에 있지만 이 배치가 다루지 않는 CMP(참조)
      "acs": [ { "id": "AC-005", "states": ["SCR-003-ST1"], ... } ],   // 이 배치 AC 중 이 화면 상태를 가리키는 것
      "vd": [ { "id": "VD-004", "via": "CMP-001" }, { "id": "VD-001", "via": "screen" } ],
      "layout": "<02 레이아웃 원문 또는 null>" } },
  "component_vd": [ { "id": "VD-004", "cmps": ["CMP-001"] } ],   // 배치 CMP와 related가 겹치는 VD(화면 무관)
  "rules": "touched-v1", "digest": "..."
}
```
전역 VD(`visual_decisions_global`)는 기존 정의(SCR·CMP 관련 없음) 그대로이며, 화면·부품에 묶인 VD는 `via`로 구분합니다.

### UI Plan(`pb-ui-plan/v1`, 선택 섹션 `touched`)

```json
"touched": {
  "SCR-001": { "changes": "공통 버튼 높이 44→48", "via": ["CMP-001"],
               "states": { "SCR-001-ST1": { "how": "route", "ref": "/seats" } },
               "acs": { } },
  "SCR-002": { "changes": "공통 버튼 높이", "via": ["CMP-001"], "covered_by": "SCR-001" },
  "SCR-003": { "changes": "공통 버튼 높이", "via": ["CMP-001"], "states": { "SCR-003-ST1": {...} },
               "acs": { "AC-005": { "states": ["SCR-003-ST1"] } } },
  "SCR-009": { "changes": "...", "via": ["layout"], "exempt": "POL-002" }
}
```
`via` 값: 배치 CMP(Brief `components`), `layout`(공통 레이아웃·패턴), `screen`(그 화면 고유 코드 변경).

## 4. 검증 정책(대표 화면 규칙)

모든 touches 화면이 같은 변경을 받는 경우(공통 부품 정비) 화면마다 증거를 강제하지 않습니다. 대신 **변경 경로(via)마다 대표 화면**에서 증거를 냅니다.

1. 각 touches 화면은 계획 항목이 있어야 합니다(`touched_missing`). `changes`(무엇이 바뀌는지)와 `via`가 필요합니다.
2. 화면은 셋 중 하나입니다.
   - **대표**: `states`에 그 화면의 정의된 상태 1개 이상(how·ref). 이 상태들이 증거 대상입니다.
   - **위임**: `covered_by`에 같은 배치의 대표 touches 화면 또는 소유 화면. 대상과 `via`가 하나 이상 겹쳐야 합니다(소유 화면은 그 화면 CMP 또는 `layout`).
   - **예외**: `exempt`에 결정된 원장 항목(policy·deviation, `ledger add → decide`). 공식 예외 절차이며 검토 묶음에 표시됩니다.
3. 위임할 수 없는 화면(대표여야 함): `via`에 `screen`이 있음(그 화면만의 변경), 또는 이 배치의 AC가 그 화면 상태를 가리킴(그 AC를 `acs`로 연결).
4. `touches`만 있고 소유 화면이 없는 UI 배치가 대표 화면을 하나도 두지 않으면(전부 예외) 경고 `no_representative`.
5. UI 배치인데 소유·touches 화면이 모두 없으면 경고 `no_screen_plan`.

증거 판정(`verify`)
- 대표 touches 상태는 **E2(태그된 테스트·브라우저 통과) 또는 EM(사용자 확인 수동 증거)** 이면 충족입니다(`touched_required`). 소유 Must 상태의 E2 필수 규칙은 그대로입니다.
- 미충족은 verify를 실패시키지 않고(소유 화면 규칙과 다른 이유: 시각 변경은 브라우저·수동 확인이 주된 증거이고, EM은 구현 제출 후에만 기록 가능) **최종 UI 승인 차단**(`final_approval_blockers`)과 이유를 남깁니다.
- 브라우저 결과는 touches 화면도 증거로 씁니다. `evidence-manual`은 touches 화면 상태도 받습니다.
- AC 연결(`ac_links`)에 touched 연결을 포함합니다. 상태 증거는 이 배치가 낸 것만 씁니다(다른 배치의 증거와 섞지 않음: 판정은 이번 실행·이 배치 EM만 봄).

UI 검토(`ui-review`)
- 화면별 묶음에 touches 화면(대표·위임·예외)을 표시합니다.
- 화면 증거가 하나도 없는 UI 배치는 경고 `evidence_empty`(모든 배치). touches 배치는 위 대표 규칙이 차단을 담당합니다.

## 5. 기존 프로젝트 영향

| 대상 | 영향 |
|---|---|
| 소유 화면만 있는 배치 | 없음(Brief digest·검증·판정·검토 동일) |
| touches가 있고 아직 시작 안 한 배치 | `ui-brief` 재실행 불필요(digest 같음). `batch-start` 전에 `ui-plan-validate` 재실행 필요, UI Plan에 `touched` 섹션 작성 필요 |
| touches가 있고 시작·완료된 배치 | 상태 유지. UI Plan을 다시 검증해도 `touched`가 없으면 경고만. 재검증(verify)하면 새 판정이 적용되고 그 결과는 최종 UI 승인 조건에만 영향 |
| 승인 해시·계획 승인·기존 게이트 | 변경 없음 |

## 6. 한계

- 대표 화면 선택이 적절한지(같은 via라도 화면마다 깨질 수 있음)는 엔진이 판단하지 않습니다. 사람이 검토 묶음에서 확인합니다.
- `via: layout`의 범위(어떤 화면이 공통 레이아웃을 쓰는지)는 텍스트 명세에서 추론하지 않습니다. 계획자가 적고 검토에서 확인합니다.
- ui-guard(경량 경로)는 touches 계획을 보지 않습니다(정적 검사 역할 유지).
