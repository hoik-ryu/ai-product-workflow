# 구현 계획 작성과 검증

역할 분리: **Claude가 계획 초안을 쓰고 다듬습니다. 스크립트는 구조·참조·중복·누락·의존성·디자인 준비·승인 정책을 검증하고 문서를 생성합니다.** 엔진은 도메인 규칙을 모릅니다(ID 형식과 문서 표·헤딩만 읽음).

## 1. 입력과 범위(`scope`)

| 입력 | 읽는 것 |
|---|---|
| `docs/planning/02-prd.md` | FR 표(우선순위 열) |
| `docs/planning/03-user-stories.md` | `### US-xxx` 블록과 `우선순위`, `추적 대상`의 FR |
| `docs/planning/05-acceptance-criteria.md` | `### AC-xxx` 블록, `추적 대상`의 US(없으면 상위 `## US-xxx` 섹션) |
| `docs/design/01-information-architecture.md` | 라우트 표(경로·셸 열) |
| `docs/design/02-screens.md` | `## SCR-xxx` 블록(경로·역할·플랫폼·추적·상태·컴포넌트) |
| `docs/design/04-ui-system.md` | `### CMP-xxx` |
| `docs/design/05-design-traceability.md` | AC → 화면·상태 또는 `비UI: 사유`, US → 화면 |

- 취소선 헤딩·행(`~~US-017~~`)은 **폐기**로 보고 범위·참조에서 제외합니다.
- **범위**
  - 기본은 우선순위 Must인 US와 그 US를 추적하는 AC입니다. 프로필 `scope.priorities`, 계획의 `scope.priorities`로 바꿉니다.
  - Should/Could는 계획의 `scope.include`에 US(또는 AC) ID를 넣어 더합니다.
  - AC 우선순위는 추적하는 US 중 가장 높은 우선순위입니다.
- **필수 화면**: 범위 안 AC(미룬 것 제외)가 가리키는 화면입니다.
- **선택 화면**: 범위 US를 추적하지만 AC가 가리키지 않는 화면입니다(배정하지 않으면 경고).
- **범위 밖 화면**(`SCR_outside`): 어느 쪽에도 연결되지 않은 화면입니다(예: 공통 오류 화면). 필요하면 배정합니다.
- UX Spec 문서가 없으면 화면 범위를 계산하지 않습니다. 그때는 화면 없는 배치만 계획할 수 있습니다.

## 2. 초안 골격(`scope --draft`) — 출발점일 뿐 정답이 아님

1. **화면 묶음**
   - IA 라우트 표의 셸 열로 묶습니다.
   - 묶음이 `batching.max_screens`보다 크면 경로 접두사(1–3단)로 나눕니다.
   - `batching.min_screens`보다 작은 묶음은 US가 가장 많이 겹치는 묶음에 합칩니다(같은 셸 우선).
2. **공통 컴포넌트**: 둘 이상의 묶음이 쓰는 CMP는 `B0`(foundation)에서 새로 만들고, 나머지 배치는 B0에 의존합니다.
3. **AC 배정**
   - 화면이 있는 AC는 그 화면을 가장 많이 가진 묶음에 배정합니다.
   - 비UI AC는 그 US의 화면이 있는 묶음(세로 슬라이스)에 배정합니다.
   - 둘 다 없으면 `non_ui` 배치에 배정합니다.
   - `order_strategy`가 `api-first`·`backend-first`면 `non_ui` 배치를 앞에, 그 밖에는 뒤에 둡니다.
4. **작업 골격**: fe(화면), be(비UI 규칙), test(AC)만 둡니다. Claude가 실제 작업으로 바꿉니다.

**Claude가 다듬을 것**
- 배치 제목·목표
- 작업 분해: fe/be/db/api/test/infra/docs
- 배치·작업 의존성: 인증·권한·셸이 먼저, 데이터(DB) → API → 화면(전략에 따라)
- 재사용 컴포넌트: `scan`의 컴포넌트 목록과 `CMP-xxx` 대응을 먼저 확인
- 위험 태그, 완료 기준, 테스트 계획
- 큰 배치 나누기
- 미룰 항목(`deferred`, 사유 필수)

## 3. 계획 형식(`docs/build/implementation-plan.json`)

```json
{
  "plan_format": 1,
  "scope": { "priorities": ["Must"], "include": [] },
  "order_strategy": "vertical",
  "batches": [
    {
      "id": "B1", "title": "가입·승인", "goal": "…", "kind": "ui | non_ui | foundation",
      "screens": ["SCR-001"], "touches": ["SCR-201"], "stories": ["US-001"], "acs": ["AC-001"],
      "components": { "reuse": ["CMP-001"], "new": ["CMP-024"] },
      "depends_on": ["B0"],
      "tasks": [ { "id": "B1-T1", "layer": "fe | be | db | api | test | infra | docs", "title": "…",
                   "refs": ["SCR-001", "AC-001"], "depends_on": ["B0-T1"] } ],
      "risk_tags": ["permission"], "approval": "auto | user",
      "done_criteria": ["…"], "test_plan": [ { "ac": "AC-001", "kind": "unit | integration | e2e | browser | manual" } ]
    }
  ],
  "deferred": [ { "id": "AC-0xx 또는 US-0xx 또는 SCR-0xx", "reason": "…" } ]
}
```

- 배치 목록 순서가 **실행 순서**입니다.
- 화면은 한 배치만 **소유**(`screens`)합니다. 다른 배치가 고치면 `touches`에 둡니다.
- `risk_tags`: `security`, `permission`, `data_loss`, `schema_migration`, `external_contract`, `privacy`, `spec_change`.

## 4. 검증 규칙(`plan-validate`, `submit plan`·`approve plan`도 같은 규칙)

| 코드 | 오류 |
|---|---|
| `plan_format`, `batch_id`, `task_id`, `batch_kind`, `task_layer` | 형식 |
| `duplicate_batch`, `duplicate_task` | ID 중복 |
| `unknown_ref` | 기획·디자인에 없거나 폐기된 ID 참조 |
| `ac_duplicate` | 한 AC가 두 배치에 배정됨 |
| `ac_missing` | 범위 안 AC가 어느 배치에도 없고 `deferred`에도 없음 |
| `ac_out_of_scope` | 범위 밖 AC 배정(`scope.include` 필요) |
| `ac_both` | 배정과 `deferred`에 동시에 있음 |
| `deferred_no_reason` | 미루는 사유 없음 |
| `scr_duplicate`, `scr_missing`, `scr_in_non_ui` | 화면 소유 중복, 필수 화면 미배정, `non_ui` 배치의 화면 소유 |
| `dep_unknown`, `dep_self`, `dep_cycle`, `order_violation` | 배치 의존성(순환, 뒤 배치에 의존) |
| `task_dep_unknown`, `task_dep_cross`, `task_dep_cycle` | 작업 의존성(다른 배치 작업에 의존하면 배치 의존도 필요) |
| `cmp_new_duplicate`, `cmp_dep_missing` | 같은 컴포넌트를 두 배치가 새로 만듦, 다른 배치가 만드는 컴포넌트를 쓰면서 그 배치에 의존하지 않음 |
| `empty_batch`, `no_tasks` | 빈 배치 |
| `design_not_ready` | 화면 배치인데 디자인 준비 수준이 부족함(`build-state.md` §5) |
| `risk_tag`, `approval` | 알 수 없는 위험 태그, 승인 값 |

**경고**(제출은 가능)
- 배치 크기 상한 초과
- 선택 화면 미배정
- AC의 화면이 그 배치에 없음
- 위험 배치의 `approval: auto` 요청 무시

## 5. 생성 문서(`docs/build/00-implementation-plan.md`)

`submit plan`이 계획 JSON과 검증 결과로 만듭니다. 문서에는 다음이 들어갑니다.
- 요약(범위 수, 배치 수, 자동/사용자 승인 수, 전략, 디자인 수준)
- waiver
- 배치 목록(실행 순서)
- 배치별 상세(작업 표, AC별 목표 증거 수준, 감지된 위험)
- 미룬 항목
- 증거 수준 기준

이 파일을 직접 고치면 승인 해시가 달라집니다. 고칠 때는 JSON을 고치고 다시 제출합니다.
