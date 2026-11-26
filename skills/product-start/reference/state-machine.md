# 상태 머신(State Machine)

제품 프로젝트의 `.ai-workflow/state.yaml`이 유일한 기준 원본입니다.
단계나 승인 상태를 대화 기억에 의존해 판단하지 않습니다.

## 단계와 상태

| 단계(stage) | 사용하는 상태 |
|---|---|
| `discovery` | `in_progress` → `awaiting_approval` → `approved` |
| `planning` | `locked` → `not_started` → `in_progress` → `awaiting_approval` → `approved`, 그리고 `outdated` |
| `design` | `locked` → `not_started` (/product-start는 planning 승인 시 잠금 해제만 합니다. 디자인 진행 상태는 `/product-design`의 `.ai-workflow/design.json`이 관리하며, `/product-design`은 `state.yaml`의 design 값을 바꾸지 않습니다. T7·T9 재검토 때는 `locked`로 되돌아갑니다) |

상태의 의미:

- `locked`: 이전 단계가 승인되지 않았습니다. 이 단계를 시작해서는 안 되고 파일도 만들면 안 됩니다.
- `not_started`: 잠금이 해제됐고 아직 아무것도 쓰지 않았습니다.
- `in_progress`: 인터뷰 중(discovery)이거나 파일을 생성·수정 중입니다.
- `awaiting_approval`: 완성된 revision을 제시했고 명시적 결정을 기다리는 중입니다. planning은 제출 스냅샷(`submitted.{revision, at, hashes}`)이 있어야 합니다.
- `approved`: 사용자가 `approved.revision`을 명시적으로 승인했고 파일 해시가 기록됐습니다.
- `outdated`: 이전 discovery revision을 기준으로 생성·승인됐습니다. 승인 전에 다시 생성하거나 재확인해야 합니다.

## 전이

| # | 이전 | 이벤트 | 이후 | 부수 효과 |
|---|---|---|---|---|
| T1 | (상태 파일 없음) | `/product-start <아이디어>` | discovery `in_progress` | `state.yaml`, `discovery-notes.md` 생성. planning `locked`, design `locked` |
| T2 | discovery `in_progress` | 인터뷰 완료, 초안 작성 | discovery `awaiting_approval` | `ps_state.py submit --stage discovery --revision N+1 --confirm`으로만 기록: revision(정확히 +1)·front matter 검증, `revision += 1`, 제출 스냅샷 `submitted.{revision, at, hashes}` 기록, history `submitted`. 상태 직접 편집·`event submitted`는 쓰지 않음 |
| T3 | discovery·planning `awaiting_approval` | 사용자 수정 요청 | 같은 단계 `in_progress` → (수정 후 T2·T6 재제출) `awaiting_approval` | `ps_state.py request-changes --stage <단계> --revision N --note "<사용자 수정 요청 원문>"`으로만 기록: 상태(`awaiting_approval`)·revision(제출된 N) 검증, `in_progress` 전이, history `changes_requested`(요청 원문·제출 해시 앞 8자)를 한 번에 원자적으로 기록. 승인 기록·제출 스냅샷·revision 보존(이전 스냅샷은 승인에 쓰이지 않고 재제출 때 교체). 중복 실행 `already_requested`, 다른 revision `revision_mismatch`, 다른 상태 `not_awaiting_approval`. 상태 직접 편집·`event changes_requested`는 쓰지 않음. 이후 파일 수정(확인 후) → `submit --revision N+1` |
| T4 | discovery `awaiting_approval` | 명시적 승인 | discovery `approved` | `approved.{revision,at,hashes}` 기록. planning `locked` → `not_started` (T7로 이미 `outdated`면 `outdated` 유지) |
| T5 | planning `not_started`/`outdated` | 사용자가 생성 확인 | planning `in_progress` | 02 → 05 순서로 생성. 파일 하나가 끝날 때마다 즉시 `artifacts_done`에 추가 |
| T6 | planning `in_progress` | 파일 4개 완료 + 추적성 점검 | planning `awaiting_approval` | `ps_state.py submit --stage planning --revision N+1 --confirm`으로만 기록: discovery 기준·revision(정확히 +1)·front matter 검증, `revision += 1`, `artifacts_done` 비움, 제출 스냅샷 `submitted.{revision, at, hashes}`(전체 SHA-256) 기록(이전 스냅샷은 덮어씀), history `submitted`. 승인 해시는 쓰지 않음. design `locked` 유지 |
| T7 | discovery `approved` | 사용자가 discovery 변경을 원함 | discovery `in_progress` | discovery `approved` 초기화. planning이 `locked`/`not_started`가 아니면 `outdated`로 바꾸고 planning `approved`도 초기화. design은 `locked`로 되돌림 |
| T8 | planning `awaiting_approval` | 명시적 승인 | planning `approved` | 제출 스냅샷과 현재 문서 비교(다르면 `changed_since_submission`으로 거부, 스냅샷 없으면 `submission_snapshot_missing`). 승인 기록(approved.hashes = 스냅샷), 스냅샷 비움. design `locked` → `not_started`. `current_stage: design`. Planning 단계 완료(다음은 `/product-design`) |
| T9 | planning `approved` | 사용자가 planning 변경을 원함(명시적 확인) | planning `in_progress` | `ps_state.py reopen --stage planning --revision N --confirm`으로만 기록: 승인 기록 검증, planning `approved` 초기화(이전 승인 시각·해시는 history `reopened`에 보존, 해시 재계산 없음), design `locked`, `current_stage: planning`. revision은 유지(다음 제출에서 +1) |

규칙:

- 전이가 일어날 때마다, 그리고 파일을 쓸 때마다 즉시 `state.yaml`을 씁니다. 중간에 중단되더라도 쓰인 파일이 기록되지 않은 상태로 남으면 안 됩니다.
- 모든 전이는 `history` 항목을 하나 추가합니다: `{at, stage, event, revision, note, src}`. 항목은 `scripts/ps_state.py`(`event`·`submit`·`request-changes`·`approve`·`reopen`)로만 추가하고, `at`은 스크립트가 실제 시스템 UTC 시각으로 정합니다(`src: engine`). 이 표지가 없는 기존 항목은 legacy로 그대로 둡니다(고쳐 쓰지 않음).
- `revision`은 해당 단계에서 제출된 버전 수입니다(첫 제출 = 1). 제출된 뒤에는 각 파일의 front matter `revision`이 단계 `revision`과 같아야 합니다.
- planning은 `based_on_discovery_revision`을 기록합니다. 이 값이 discovery `approved.revision`과 다르면 planning은 `outdated`입니다.

## 명시적 승인

제시한 revision에 대한 모호하지 않은 승인만 인정합니다.

- 인정: "승인", "승인합니다", "approve", "approved", "LGTM, approve", 또는 "승인(Approve)" 선택지 선택
- 인정하지 않음(다시 묻고 상태는 그대로): "좋네요", "괜찮은 것 같아요", "ok", "next", "계속", 무응답, 같은 메시지 안의 승인 + 수정 요청("승인, 근데 X만 바꿔줘" → 수정 요청으로 처리)
- 승인은 방금 제시한 revision에만 적용됩니다. 제시한 뒤 파일이 바뀌었으면 다시 제시합니다.

사용자가 다음 단계를 미리 요청하면(discovery 중 "PRD 바로 써줘") 정중히 거절하고, 현재 게이트를 설명한 뒤 승인 대기 중인 항목을 제시하겠다고 제안합니다.

## 재개 시 교차 검증(매 실행)

1. `state.yaml`이 있으면 파싱합니다. 파싱할 수 없으면 보고하고 멈춥니다.
2. `docs/planning/`의 파일을 나열해 상태와 비교합니다.

| 점검 | 불일치 시 처리 |
|---|---|
| 현재 상태에서 존재해야 하는 파일이 있는가: discovery `revision` ≥ 1이면 discovery 파일, planning이 `awaiting_approval` / `approved` / `outdated`이면 모든 planning 파일, planning이 `in_progress`이면 `artifacts_done`의 모든 파일 | 없음 → 보고 후 멈춤. 임의로 다시 생성하지 않습니다. (`artifacts`에 있지만 아직 생성 시점이 아닌 파일은 없는 것이 정상입니다.) |
| planning이 `locked` / `not_started`인데 planning 파일이 존재하지 않는가 | 예상치 못한 파일 → 보고 후 멈춤. 덮어쓰거나 산출물로 편입하지 않습니다. |
| front matter `revision`이 제출·승인된 파일은 단계 `revision`과 같고, `in_progress` 중에 쓴 파일은 단계 `revision + 1`(준비 중인 revision)과 같은가 | 다름 → 수동 편집으로 보고합니다. |
| `approved` 단계의 파일에 대해 현재 `shasum -a 256` 값이 기록된 해시와 같은가 | 다름 → "승인된 문서가 변경됨"으로 보고합니다(아래 참조). |
| `ps_state.py check`가 통과하는가(history·승인 시각이 UTC 형식이고 미래가 아니며 순서가 맞음, 승인 대기 문서가 제출 스냅샷과 같음) | 문제 → 보고합니다. 기존 기록은 고치지 않습니다(사용자에게 알림). |

3. `state.yaml`이 없는데 `docs/planning/`에 파일이 있으면 → 파일 목록을 보고하고 아무것도 쓰지 않은 채 진행 방법을 묻습니다(예: 파일을 다른 곳으로 옮기기, 다른 디렉터리에서 시작하기). 답을 받을 때까지 멈춥니다.

불일치가 있으면 기대한 상태, 실제 상태, 선택지를 보고합니다. 스스로 고치지 않습니다.

### 승인 무결성(제출 스냅샷)

불변식: **승인되는 문서 = 제출된 문서.** `approve`는 `stages.<단계>.submitted.hashes`(제출 시점 전체 SHA-256)와 현재 문서가 모두 같을 때만 승인합니다.

- 기록: T6 `submit`이 `submitted.{revision, at, hashes}`를 `approved` 블록 앞에 씁니다. 재제출(T3·T9 뒤)은 항상 새 스냅샷으로 덮어쓰고, `approve`는 스냅샷 revision이 현재 revision과 같을 때만 씁니다(`submission_snapshot_stale`).
- 비교: `approve`·`check`가 현재 문서와 비교합니다. 내용·front matter 변경과 삭제는 모두 `changed_since_submission`입니다. 선택지: (a) 수정 요청(T3) 후 다시 제출, (b) 제출 시점 내용으로 복원.
- 정리: 승인되면 스냅샷을 비웁니다(같은 전체 해시가 `approved.hashes`에, 앞 8자가 history `submitted`·`approved`에 남음). `approved` 상태에 스냅샷이 남아 있으면 `check`·`reopen`이 문제로 보고합니다.
- 하위 호환: 스냅샷 블록이 없거나 `revision: null`이면 "스냅샷 없음"입니다. 상태 파일은 그대로 읽히며, planning이 `awaiting_approval`이면 `check`는 경고만 하고 `approve`는 거부합니다(`submission_snapshot_missing`). 처리: 사용자 승인 후 `ps_state.py migrate-snapshot --stage planning --revision N --confirm` — history의 마지막 planning 기록이 스크립트(`submit`)가 남긴 같은 revision의 `submitted`이고, 거기 적힌 파일별 제출 해시(앞 8자)가 현재 문서와 모두 같을 때만 현재 전체 해시를 스냅샷으로 기록합니다(`source: migrated`, `at`은 원래 제출 시각, 상태·history는 바꾸지 않음). 확인할 수 없으면(`snapshot_unverifiable`) 수정 요청(T3) 후 다시 제출합니다.
- discovery: 같은 불변식을 적용합니다. T2는 `submit --stage discovery`로 스냅샷을 남기고, `approve`는 스냅샷이 없으면 거부합니다(`submission_snapshot_missing`). 하위 호환: 이미 `approved`인 discovery 기록은 그대로 인정합니다. 스냅샷 없이(상태 직접 편집 등) `awaiting_approval`이 된 discovery는 제출 해시 기록이 없어 마이그레이션할 수 없으므로, 수정 요청(T3) 후 `submit --stage discovery`로 다시 제출합니다(`migrate-snapshot`은 planning 전용).

### 승인된 문서가 변경된 경우(해시 불일치)

영향을 설명하고 사용자가 고르게 합니다.

- 승인 후 discovery가 변경됨 → 현재 내용에 대해 discovery 승인은 더 이상 유효하지 않습니다. planning이 생성돼 있다면 이전 내용을 기준으로 한 것입니다.
  선택지: (a) 재검토: T7을 적용하고 현재 파일을 새 revision으로 제시해 승인을 받습니다. (b) 사용자가 파일을 복원(예: `git checkout -- <file>` 또는 백업에서 복원)한 뒤 재개합니다.
- 승인 후 planning 파일이 변경됨 → planning 승인은 더 이상 유효하지 않고 design 잠금 해제도 보류됩니다.
  선택지: (a) 재검토: T9(`reopen --confirm`, 해시가 달라도 재개 가능하며 바뀐 파일이 history에 표시됨)를 적용하고 추적성을 점검한 뒤 승인을 받습니다. (b) 사용자가 복원합니다.

변경된 승인 문서의 해시를 조용히 다시 기록하지 않습니다.

### 변경 패키지 finalize(`--package`)

`/product-change` 최종 통합 승인 후 finalize만 `ps_state.py reopen|submit|approve --stage planning --package CP-###`를 호출합니다. 스크립트는 `.ai-workflow/change.json`의 그 패키지가 `finalizing`이고 기획 문서 해시가 패키지 제안과 같을 때만 받으며, 승인 note는 `[CP-### 최종 통합 승인 <시각> · 묶음 <digest 앞 12자>] <사용자 최종 승인 원문>`입니다. 단계별 승인 문장을 새로 만들지 않습니다. 사람이 직접 `--package`를 쓰지 않습니다.

