# 구현 상태와 승인 (`.ai-workflow/build.json`)

`/product-build`의 상태 기준은 `.ai-workflow/build.json`이며, `scripts/product_build.py`만 이 파일을 씁니다. LLM은 직접 편집하지 않습니다.

## 1. 소유권과 읽기·쓰기 경계

| 파일 | 소유 | `/product-build`이 하는 일 |
|---|---|---|
| `.ai-workflow/state.yaml`, `docs/planning/` | `/product-start` | **읽기만.** planning 승인과 승인 해시 확인 |
| `.ai-workflow/design.json`, `docs/design/`, `design-preview/` | `/product-design` | **읽기만.** 판정은 `product_design.py status`(읽기 전용 명령) 결과를 따름 |
| `.ai-workflow/boilerplate.json` | `/product-init` | **읽기만.** 검증 명령 후보로 사용 |
| `.ai-workflow/build.json`, `.ai-workflow/build/`, `docs/build/` | `/product-build` | 쓰기 |

- 스크립트의 쓰기 함수는 위 소유 경로 밖이면 거부합니다. 다른 Skill의 승인 해시·revision을 바꿀 방법이 없습니다.
- `product_design.py check`는 상태를 기록할 수 있어(outdated 표시) 호출하지 않습니다.
- `guard`는 구현 배치(M2.2)에서 바뀐 파일 중 보호 경로를 찾습니다.

## 2. 구조

```json
{
  "schema_version": 1,
  "engine": { "skill": "product-build", "engine_ref": "<엔진 커밋>" },
  "plan": {
    "status": "drafting | awaiting_approval | approved | outdated",
    "revision": 1,
    "submitted": { "revision": 1, "at": "…", "hashes": { "<계획 파일>": "sha256" }, "inputs": { "…": "입력 기준선" }, "summary": {} },
    "approved":  { "revision": 1, "at": "…", "hashes": {}, "inputs": {}, "statement": "<사용자 승인 문장>", "summary": {} },
    "last_approved": null,
    "validity": { "status": "valid | outdated", "changed": [] }
  },
  "batches": { "B0": { "status": "planned", "approval": "auto | user", "approval_reasons": [], "requires_design": true,
                       "design_path": "preview_approved | preview_waiver | planning_only", "waiver": "WVR-001",
                       "depends_on": [], "ac_targets": { "AC-001": "E2" }, "plan_revision": 1 } },
  "waivers": [ { "id": "WVR-001", "kind": "preview", "status": "active | revoked", "reason": "…", "statement": "<사용자 승인 문장>",
                 "scope": { "all_ui": true, "batches": [] }, "basis": { "level": "L2", "ux_spec_revision": 1, "design_direction_revision": 1 },
                 "approved_at": "…" } ],
  "history": [ { "at": "…", "target": "plan | waiver | batch", "event": "…", "revision": 1, "note": "…" } ]
}
```

**계획 해시 대상**은 세 파일입니다: `docs/build/implementation-plan.json`, `docs/build/00-implementation-plan.md`(생성 문서), `docs/build/build-profile.toml`.

## 3. 계획 상태 전이

```
drafting ──submit plan──▶ awaiting_approval ──approve plan(명시적 승인)──▶ approved
   ▲                          │ (내용을 고쳐 다시 submit: revision +1)          │
   └──────reopen plan─────────┴───────────────────────────────────────────────┤
                                                                               ▼
                                              (check가 입력 변경 감지) outdated ──reopen plan──▶ drafting
```

- `submit plan`: 계획을 검증(`plan-validate`와 같은 규칙)하고, 문서를 생성하고, 계획 파일 해시와 **입력 기준선**을 기록합니다. 같은 내용이면 다시 제출하지 않습니다(멱등).
- `approve plan --revision N --note "<승인 문장>"`
  - 제출 이후 계획 파일이나 입력이 바뀌었으면 거부합니다.
  - 승인 시점에 다시 검증합니다(waiver 철회 등).
- 승인 후 계획 파일이 바뀌면 `check`가 `plan_modified`로 멈춥니다. 자동으로 다시 승인하지 않습니다.
- **승인되지 않은 계획으로는 실행 단계에 들어갈 수 없습니다.** `execute-gate`는 아래를 모두 확인합니다.
  - 계획 승인 여부
  - 계획 파일 해시
  - 입력 기준선
  - 선행 배치 조건(`execution.dependency_min`, 기본 verified)
  - 활성 배치 1개 제한
  - 디자인 기준(waiver 유효성 포함)

## 4. 입력 기준선과 무효화

계획 승인 때 다음을 기록합니다.
- **planning**: discovery·planning 승인 revision, `docs/planning/02–05` 승인 해시(state.yaml 기록과 현재 파일 일치를 확인한 값)
- **design**: 준비 수준, ux_planning·ux_spec·design_direction·preview 승인 기록 요약(해시 묶음의 digest), 기준 revision
- **design_files**: 계획이 읽는 디자인 문서(00–05, 07)의 현재 해시

`check`가 승인 기준선과 현재를 비교해 아래 중 하나라도 해당하면 계획을 `outdated`로 기록합니다(이 Skill의 파일만 씀).

| 변화 | 계획 무효 |
|---|---|
| planning 재승인(revision·해시) | 예 |
| ux_planning·ux_spec·design_direction 승인 기록 변경 | 예 |
| 디자인 문서 내용 변경 | 예 |
| 디자인 준비 수준 하락(예: L2 → L1) | 예 |
| 프리뷰가 새로 승인됨(L2 → L3) | **아니요**(기준이 좋아진 것) |
| L3 계획에서 프리뷰 승인 기록 변경 | 예 |

## 5. 디자인 준비 수준과 preview waiver

| 수준 | 조건 | 계획할 수 있는 배치 |
|---|---|---|
| L0 | design.json 없음 | 화면 없는 배치(`non_ui`)만 |
| L1 | UX Spec 미승인·승인 후 변경, 게이트가 켜졌는데 DD 미승인, 디자인 outdated | 화면 없는 배치만 |
| L2 | UX Spec(+게이트 시 DD) 승인, 프리뷰 미승인 | 화면 배치는 **preview waiver**가 포함해야 함 |
| L3 | 프리뷰 승인(일관성 확인) | 모두 |

**화면 배치 판정**: 화면을 소유하거나, `kind`가 `ui`이거나, `fe` 작업이 있으면 화면 배치입니다.

preview waiver는 **프리뷰 승인만** 대신하는 공식 예외 경로입니다.
- **조건**
  - L2에서만 기록할 수 있습니다.
  - 사유, 범위(`--all-ui` 또는 `--batches`), 사용자 승인 문장(`--note`), `--confirm`이 모두 필요합니다.
  - `--confirm` 없이 실행하면 기록할 내용만 보여 줍니다.
- **기준**: 기록할 때의 ux_spec·design_direction 승인 revision을 함께 저장합니다. 그 revision이 바뀌면 waiver는 무효가 됩니다.
- **design.json**: 바꾸지 않습니다. 프리뷰는 `in_progress` 그대로입니다.
- **철회**: `waiver revoke --id --reason`. 그 waiver에 기댄 배치는 `execute-gate`에서 막힙니다.

## 6. 배치 승인 정책(사용자 개입 최소화)

기본 흐름은 **계획 승인 → 배치 자동 구현 → 자동 검증 → 다음 배치**입니다(M2.2·M2.3). 계획 단계에서 배치마다 `approval: auto | user`를 스크립트가 정합니다.

| 사용자 승인이 필요한 이유 | 판정 |
|---|---|
| 위험 태그 | 계획에 적은 `risk_tags` + AC 제목·본문의 키워드 감지(프로필 `approval.risk_keywords`) + `db` 작업(→ `schema_migration`) 중 `approval.user_required_tags`에 있는 것 |
| preview waiver 배치 | 프로필 `approval.waived_ui = "user"`일 때(기본 `auto`: waiver 자체가 사용자의 명시적 결정이고, 시각 확인은 배치 검증 기록으로 남음) |
| 계획에서 지정 | 배치의 `"approval": "user"` |
| 프로필 기본값 | `approval.default = "user"` |

- 위험 배치는 계획에 `"approval": "auto"`라고 적어도 **자동으로 낮출 수 없습니다**(경고와 함께 무시).
- 키워드 감지는 보수적인 신호입니다. 오탐을 줄이려면 프로필에서 키워드를 조정합니다. 도메인마다 뜻이 다른 단어(예: '세션', '토큰')는 기본값에 넣지 않았습니다.
- **AC 목표 증거 수준**: 위험 태그가 감지된 AC는 `evidence.risk`(기본 E3), Must는 `evidence.must`(기본 E2), 그 밖은 `evidence.should`(기본 E1)입니다. 판정은 M2.3에서 합니다.

## 7. 배치 상태

`planned → in_progress → implemented`(M2.2) → `verified` | `verify_failed`(M2.3) → `awaiting_approval → approved`(M2.4)

- M2.4 상태·기록
  - `imported`: 기존 구현 등록(사용자 확인, 구현 이력 아님)
  - `approved`: 최종 사용자 승인(`approvals[]`, 무효화되면 `valid: false`와 사유만 덧붙임)
  - `target_overrides[]`: 사용자 승인 목표 변경(원래 `ac_targets`는 보존)
  - `fi_accepted{}`: AC별 결함 주입 증거 인정(사용자 승인)
- M2.3 상태
  - `verified`: 필수 AC가 테스트 증거로 확인됨. 사용자 승인이 아닙니다.
  - `verify_failed`: AC별 사유가 남습니다. `resume --batch`로 고칩니다.
  - `stale`: 검증 뒤 배치 범위 코드가 바뀜, 회귀, 증거 유실 → 재검증 필요
  - 자세한 내용: `reference/verification.md`
- 무결성 검사(수동 편집 의심 시 `invalid_state`)
  - `implemented` 이상인데 구현 제출 기록이 없음
  - `verified`·`stale`인데 검증 실행 기록(run_id·digest)이 없음

- 곁가지 상태
  - `paused`: 일시 중지, 잠금 해제
  - `failed`: 재시도 한도 초과. 사용자 결정 후에만 재개
  - `blocked`: 차단 정책(M2.4)
  - `outdated` / `reopened`: 승인 후 무효(M2.4)
  - `imported`: adopt 등록, 승인 이력 없음(M2.3)
- **활성 배치는 하나**입니다(`in_progress`·`paused`·`failed` 중 하나라도 있으면 새 배치를 시작하지 않음).
- 선행 배치 조건은 프로필 `execution.dependency_min`(기본 `verified`, M2.3)입니다.
- **`implemented`는 구현 완료일 뿐 검증·승인 완료가 아닙니다.**
- 실행 기록(`batches.<ID>.run`)
  - 시작 기준선: HEAD, 브랜치, 시작 때 미커밋 파일 해시
  - 작업별 상태·파일
  - 체크포인트 포인터
  - 재시도(`attempts`)·실패(`failure`)
  - 사용자 확인(`confirmations`)
  - 잠금 넘겨받기(`takeovers`)
  - 범위 밖·테스트 변경(`findings`)
  - 제출 기록(`submitted`)
- 자세한 규칙: `reference/execution.md`

## 8. 오류와 종료 코드

- 0: 성공
- 2: 차단. 사용자 조치가 필요하며 상태를 바꾸지 않습니다. 예외는 `check`의 outdated 기록입니다.
- 1: 내부 오류. 상태 파일은 원자적으로만 쓰므로 부분 기록이 없습니다.

모든 출력은 JSON입니다.
