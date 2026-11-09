# 디자인 상태와 승인 (`.ai-workflow/design.json`)

`/product-design`의 상태 기준은 `.ai-workflow/design.json`이며, `scripts/product_design.py`만 이 파일을 씁니다. LLM은 직접 편집하지 않습니다.

## /product-start 상태와의 관계 (표시 정책)

| 파일 | 소유 | `/product-design`이 하는 일 |
|---|---|---|
| `.ai-workflow/state.yaml` | `/product-start` | **읽기만.** planning 승인·해시와 `design` 잠금 여부만 확인 |
| `docs/planning/01–05` | `/product-start` | **읽기만** |
| `.ai-workflow/design.json` | `/product-design` | 디자인 상태의 유일한 기준 |
| `.ai-workflow/boilerplate.json` | `/product-init` | 읽지도 쓰지도 않음 |

- `state.yaml`의 `design: not_started`는 "planning이 승인되어 디자인 단계가 열렸다"는 `/product-start`의 표시입니다. 디자인 진행 상태가 아닙니다.
- 사용자에게 상태를 보고할 때는 항상 `design.json` 기준으로 말합니다. `state.yaml`의 값을 함께 보여 줄 때는 위 의미를 한 줄로 덧붙입니다(`status`의 `display_note`).
- `/product-start`가 T9(기획 재검토)를 적용하면 `state.yaml`의 design이 `locked`가 됩니다. `/product-design`은 이를 "기획 재검토 중"으로 보고 모든 명령을 차단합니다. 디자인 문서는 보존합니다.

## 구조

```json
{
  "based_on": { "discovery_revision": "2", "planning_revision": "2",
                "planning_hashes": { "docs/planning/01-discovery.md": "…", "…": "…" },
                "planning_commit": "<시작 시 HEAD>" },
  "validity": { "status": "valid | outdated" },
  "stages": {
    "ux_planning": { "status": "…", "revision": 0, "artifacts_done": {}, "submitted": null, "approved": null },
    "ux_spec":     { "status": "locked", "structure_confirmed": null, "based_on_ux_planning_revision": null, "…": "…" },
    "preview":     { "status": "locked", "based_on_ux_spec_revision": null, "verification": null, "…": "…" }
  },
  "history": [ { "at": "…", "stage": "…", "event": "…", "revision": 1, "note": "…" } ]
}
```

단계 상태: `locked` → `not_started` → `in_progress` → `awaiting_approval` → `approved`. 전체 유효성: `validity.status`(`valid` | `outdated`).

| 단계 | 산출물 | 승인 이름 |
|---|---|---|
| `ux_planning` | `docs/design/00-ux-decisions.md` (+ 원문 기록 `.ai-workflow/design-notes.md`, 해시 대상 아님) | **UX 결정 확정** |
| `ux_spec` | `docs/design/01`–`05` | **UX 설계 승인** (중간에 **구조 확인** 체크포인트) |
| `preview` | `docs/design/06-preview-review.md` + `design-preview/` 전체 트리 해시 | **시각 디자인 승인** (승인 시점의 UX 설계 승인 해시도 기록해, 이후 UX 설계 승인 해시와 다르면 `stale_preview`) |

## 전이

| # | 이전 | 명령(사용자 행동) | 이후 | 부수 효과 |
|---|---|---|---|---|
| D1 | 상태 파일 없음 | `start` (게이트 통과, 미커밋 변경 없음, 기존 디자인 파일 없음) | ux_planning `in_progress` | `based_on` 기록. ux_spec·preview `locked` |
| D2 | 단계 `in_progress` | `done --path` | 그대로 | 산출물 해시 기록. front matter `revision` = 준비 중 revision |
| D3 | ux_spec `in_progress` | `checkpoint` (사용자 **구조 확인**) | 그대로 | IA·화면 목록 해시, 화면 구성 서명(IA 라우트 표 + 화면 ID), 대상 revision 기록. 재검토 revision에서 화면 구성이 같으면 확인을 이어받고(history `structure_carried`), 달라지면 다시 확인 |
| D4 | 단계 `in_progress` | `submit` (산출물 모두 done + 검사 통과) | `awaiting_approval` | `revision += 1`, 제시한 해시 기록 |
| D5 | `awaiting_approval` | `approve --revision N` (사용자 **명시적 승인**) | `approved` | 승인 해시 기록. 다음 단계 `locked` → `not_started` |
| D6 | `awaiting_approval` | `reopen` (수정 요청) | `in_progress` | history `changes_requested` |
| D7 | `approved` | `reopen` (사용자가 변경 원함) | `in_progress` | **하위 단계 승인 무효화**(`locked`) |
| D8 | `not_started` | `begin` (앞 단계 승인) | `in_progress` | 앞 단계 승인 revision을 `based_on_*`로 기록 |
| D9 | 어느 상태든 | planning 승인 해시가 `based_on`과 다름(자동 감지) | `validity: outdated` | 모든 명령 차단(`impact`, `status`, `rebase` 제외) |
| D10 | `outdated` | `rebase --confirm` (planning 재승인·커밋 후, 사용자 확인) | ux_planning `in_progress`, 나머지 `locked` | 새 `based_on`. 모든 디자인 승인 해제 |

## 공통 게이트(모든 상태 변경 명령)

`begin`, `done`, `checkpoint`, `submit`, `approve`, `reopen`, `preview-scaffold`, `preview-verify`는 `check`를 먼저 실행했는지와 관계없이 스스로 다음을 검증합니다.

1. planning 승인과 01–05 승인 해시(`state.yaml`), `state.yaml`의 design이 `locked`가 아님
2. 디자인 기준(`based_on`)과 현재 planning 승인 해시가 같음(다르면 `outdated`)
3. **대상 단계보다 앞선 단계**의 교차 검증: 승인·제출 후 변경, 누락, 프리뷰 기준 불일치 → `upstream_modified`로 차단
   - 예: UX Planning 승인 후 00이 바뀌면 UX 설계의 `begin`·`done`·`checkpoint`·`submit`·`approve`가 차단됩니다. UX 설계 승인 후 01–05가 바뀌면 프리뷰의 모든 진행·승인이 차단됩니다.
   - 같은 단계의 승인 후 변경은 그 단계의 `reopen`으로 해결하므로 막지 않습니다(제출·승인은 각 명령이 `changed_since_done`/`changed_since_submit`으로 자체 검사).

## 승인 규칙

- 인정하는 표현: "승인", "승인합니다", "approve", "확정"(UX Planning), "구조 확인"(체크포인트), 또는 같은 의미의 선택지 선택.
- 인정하지 않는 표현(다시 묻고 아무것도 실행하지 않음): "좋네요", "괜찮아요", "ok", "다음", "계속", 승인 + 수정이 섞인 응답(수정 요청으로 처리).
- 승인은 방금 제시한 revision에만 적용됩니다. `approve`는 제출 이후 파일이 바뀌었으면 `changed_since_submit`으로 거부합니다.
- 승인된 파일이 바뀌면 `check`가 `approved_modified`로 차단합니다. **해시를 다시 기록하지 않습니다.** 선택지: 재검토(`reopen`) 또는 사용자가 복원.

## 무효화

| 원인 | 영향 |
|---|---|
| UX Planning 재검토(reopen) | UX 설계·프리뷰 승인 무효(`locked`). UX 결정 확정 후 다시 설계·승인 |
| UX 설계 재검토(reopen) | 프리뷰 승인 무효(`locked`). 재승인된 UX 설계 revision으로 프리뷰 manifest를 갱신해야 함 |
| planning 변경(T9 → 재승인) | T9 동안 차단. 재승인 후 `outdated` → `impact`로 영향 확인 → `rebase` |
| 프리뷰 피드백이 UX 설계 변경을 요구 | 프리뷰에서 임의로 반영하지 않음. UX 설계 reopen(프리뷰 승인 무효) 후 반영 |

## 파일 안전

- 시작 시 `docs/design/`, `design-preview/`, `.ai-workflow/design-notes.md`가 이미 있으면 `start`가 거부합니다(덮어쓰지 않음).
- 기존 디자인 파일을 고치기 전에 무엇을 왜 바꾸는지 설명하고 확인을 받습니다. `backup --path`가 백업 필요 여부를 판단합니다(Git 추적 + 미커밋 변경 없음 → 백업 없음, 그 외 `.ai-workflow/backup/design/` 단일 슬롯).
- `/product-design`은 Git 이력을 바꾸는 명령(commit, push, reset, checkout, clean, stash)을 실행하지 않습니다.
