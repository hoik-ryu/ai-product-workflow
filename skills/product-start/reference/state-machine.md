# 상태 머신(State Machine)

제품 프로젝트의 `.ai-workflow/state.yaml`이 유일한 기준 원본입니다.
단계나 승인 상태를 대화 기억에 의존해 판단하지 않습니다.

## 단계와 상태

| 단계(stage) | 사용하는 상태 |
|---|---|
| `discovery` | `in_progress` → `awaiting_approval` → `approved` |
| `planning` | `locked` → `not_started` → `in_progress` → `awaiting_approval` → `approved`, 그리고 `outdated` |
| `design` | `locked` → `not_started` (Milestone 1은 잠금 해제만 하고 실행하지 않음) |

상태의 의미:

- `locked`: 이전 단계가 승인되지 않았습니다. 이 단계를 시작해서는 안 되고 파일도 만들면 안 됩니다.
- `not_started`: 잠금이 해제됐고 아직 아무것도 쓰지 않았습니다.
- `in_progress`: 인터뷰 중(discovery)이거나 파일을 생성·수정 중입니다.
- `awaiting_approval`: 완성된 revision을 제시했고 명시적 결정을 기다리는 중입니다.
- `approved`: 사용자가 `approved.revision`을 명시적으로 승인했고 파일 해시가 기록됐습니다.
- `outdated`: 이전 discovery revision을 기준으로 생성·승인됐습니다. 승인 전에 다시 생성하거나 재확인해야 합니다.

## 전이

| # | 이전 | 이벤트 | 이후 | 부수 효과 |
|---|---|---|---|---|
| T1 | (상태 파일 없음) | `/product-start <아이디어>` | discovery `in_progress` | `state.yaml`, `discovery-notes.md` 생성. planning `locked`, design `locked` |
| T2 | discovery `in_progress` | 인터뷰 완료, 초안 작성 | discovery `awaiting_approval` | `revision += 1`, history `submitted` |
| T3 | 모든 `awaiting_approval` | 수정 요청 | 같은 단계 `in_progress` → `awaiting_approval` | 파일 수정(확인 후), `revision += 1`, history `changes_requested` + `submitted` |
| T4 | discovery `awaiting_approval` | 명시적 승인 | discovery `approved` | `approved.{revision,at,hashes}` 기록. planning `locked` → `not_started` (T7로 이미 `outdated`면 `outdated` 유지) |
| T5 | planning `not_started`/`outdated` | 사용자가 생성 확인 | planning `in_progress` | 02 → 05 순서로 생성. 파일 하나가 끝날 때마다 즉시 `artifacts_done`에 추가 |
| T6 | planning `in_progress` | 파일 4개 완료 + 추적성 점검 | planning `awaiting_approval` | `revision += 1`, history `submitted` |
| T7 | discovery `approved` | 사용자가 discovery 변경을 원함 | discovery `in_progress` | discovery `approved` 초기화. planning이 `locked`/`not_started`가 아니면 `outdated`로 바꾸고 planning `approved`도 초기화. design은 `locked`로 되돌림 |
| T8 | planning `awaiting_approval` | 명시적 승인 | planning `approved` | 승인 기록. design `locked` → `not_started`. `current_stage: design`. Milestone 1 완료 |
| T9 | planning `approved` | 사용자가 planning 변경을 원함 | planning `in_progress` | planning `approved` 초기화. design은 `locked`로 되돌림 |

규칙:

- 전이가 일어날 때마다, 그리고 파일을 쓸 때마다 즉시 `state.yaml`을 씁니다. 중간에 중단되더라도 쓰인 파일이 기록되지 않은 상태로 남으면 안 됩니다.
- 모든 전이는 `history` 항목을 하나 추가합니다: `{at, stage, event, revision, note, src}`. 항목은 `scripts/ps_state.py`(`event`·`approve`)로만 추가하고, `at`은 스크립트가 실제 시스템 UTC 시각으로 정합니다(`src: engine`). 이 표지가 없는 기존 항목은 legacy로 그대로 둡니다(고쳐 쓰지 않음).
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
| `ps_state.py check`가 통과하는가(history·승인 시각이 UTC 형식이고 미래가 아니며 순서가 맞음) | 문제 → 보고합니다. 기존 기록은 고치지 않습니다(사용자에게 알림). |

3. `state.yaml`이 없는데 `docs/planning/`에 파일이 있으면 → 파일 목록을 보고하고 아무것도 쓰지 않은 채 진행 방법을 묻습니다(예: 파일을 다른 곳으로 옮기기, 다른 디렉터리에서 시작하기). 답을 받을 때까지 멈춥니다.

불일치가 있으면 기대한 상태, 실제 상태, 선택지를 보고합니다. 스스로 고치지 않습니다.

### 승인된 문서가 변경된 경우(해시 불일치)

영향을 설명하고 사용자가 고르게 합니다.

- 승인 후 discovery가 변경됨 → 현재 내용에 대해 discovery 승인은 더 이상 유효하지 않습니다. planning이 생성돼 있다면 이전 내용을 기준으로 한 것입니다.
  선택지: (a) 재검토: T7을 적용하고 현재 파일을 새 revision으로 제시해 승인을 받습니다. (b) 사용자가 파일을 복원(예: `git checkout -- <file>` 또는 백업에서 복원)한 뒤 재개합니다.
- 승인 후 planning 파일이 변경됨 → planning 승인은 더 이상 유효하지 않고 design 잠금 해제도 보류됩니다.
  선택지: (a) 재검토: T9를 적용하고 추적성을 점검한 뒤 승인을 받습니다. (b) 사용자가 복원합니다.

변경된 승인 문서의 해시를 조용히 다시 기록하지 않습니다.
