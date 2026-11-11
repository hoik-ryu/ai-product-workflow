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

## 워크플로 v2 (WF-D05)

`design.json`의 `config.workflow`가 없거나 `"v1"`이면 위의 v1 규칙이 **그대로** 적용됩니다. v2는 사용자가 명시적으로 승인한 전환(`migrate --to v2 --confirm`)으로만 켜집니다.

### 상태 구조 차이

| 항목 | v1 | v2 |
|---|---|---|
| `config` | 없음 | `{"workflow": "v2", "theme_file": "<경로>" \| null, "gates": {"design_direction": true}?}` (게이트는 켤 때만 생김) |
| 단계 순서 | ux_planning → ux_spec → preview | ux_planning → ux_spec → **design_direction** → preview |
| `stages.design_direction` | 없음 | `{status, revision, artifacts: [07], artifacts_done, submitted, approved, based_on_ux_spec_revision}`. 승인 기록에 `ux_spec_revision`·`ux_spec_hashes`·`approved_vds`·`renderer`·`theme_hash` |
| `theme` | 없음 | `{path, baseline_hash, recorded_at}`(전환 시 기준) |
| 프리뷰 승인·제출·검증 기록 | `hashes`(06 + 트리 원본 해시) | v1 필드 + `semantic_tree_hash`·`semantic_algo: "sem-2"` + `theme_hash`. 게이트가 켜진 뒤에는 `design_direction_revision`·`design_direction_hashes` |
| `gate_activations` | 없음 | 게이트를 켠 기록 `{gate, at, preview_status, preview_approved_revision, design_direction_status}` |
| `stages.preview.v2_baseline` | 없음 | 전환 시점에 이미 승인·제출된 프리뷰의 의미·테마 기준(기존 승인 기록은 바꾸지 않고 별도 필드) |
| `stages.preview.review` | 없음 | `null`(M2 검토 기록 자리) |
| `migration` | 없음 | `{from, to, at, backup}` |

### 의존성(`STAGE_DEPS`)

| 단계 | v1 | v2 |
|---|---|---|
| ux_spec | ux_planning | ux_planning |
| design_direction | - | ux_spec |
| preview | ux_spec | ux_spec, design_direction |

- **preview의 design_direction 의존은 게이트(`config.gates.design_direction`)가 켜졌을 때만 적용합니다.** 꺼져 있으면 design_direction은 선택 단계이고, `deferred_dependencies`에 표시됩니다.
- 상위 단계 검증(`upstream_modified`)·무효화·잠금 해제는 단계 순서가 아니라 **적용 중인 의존성**을 따릅니다. v1과 게이트 켜진 v2에서는 단계 순서와 같고, 게이트가 꺼진 v2에서는 design_direction을 다시 열어도 preview가 무효화되지 않습니다.
- ux_spec reopen → design_direction·preview 잠금(둘 다 ux_spec에 의존). ux_spec 재승인 → 적용 중인 의존이 모두 승인된 잠금 단계를 엽니다.
- 상태 파일에서 승인·제출 상태인데 그 기록이 없으면 `missing_record` 문제로 보고하고 승인으로 인정하지 않습니다.

### Design Direction 단계(WF-D02)

명령은 다른 단계와 같습니다: `begin --stage design_direction` → 07 작성 → `trace --stage design_direction`(문서 검증) → `done --path docs/design/07-design-direction.md` → `submit --stage design_direction` → **"디자인 방향 승인"** → `approve --stage design_direction --revision N`. 수정은 `reopen --stage design_direction`.

| 검사(`trace --stage design_direction`, 제출 조건) | 내용 |
|---|---|
| 기준 | UX 설계가 승인되어 있고, 07 front matter `based_on.ux_spec_revision`과 입력의 'UX 설계 기준'이 승인된 revision과 같음 |
| 필수 섹션 | 입력, 디자인 방향, 시각 결정, 정책 값, 렌더링 경로, 렌더 범위, UX Spec과의 차이, 검증 기준 |
| 입력 | 디자인 프로필, 브랜드·시각 방향, 컴포넌트·토큰 매핑, 규칙 출처(없으면 '없음(사유)') |
| VD | `### VD-###` 1개 이상. 상태 승인·후보·미결정·제외. **후보·미결정이 남아 있으면 제출 불가.** 관련 ID는 승인 문서에 있어야 하고, 토큰 이름은 04에 있어야 함(새 의미 토큰은 ②) |
| 정책 값 | density, touch.min, safe_area(프로젝트 값, 엔진 기본값 없음) |
| 렌더러 | code · figma · both(Figma는 검토용, 최종 시각 승인은 프리뷰) |
| 렌더 범위 | 02에 있는 화면·상태만, 적용 VD는 **승인된 VD만** |
| 변경 요청(`### CR-###`) | ①·②가 '기각'이 아닌 상태로 남으면 제출 불가(`reopen --stage ux_spec` 안내). conditional·needs_review가 '미결'이면 제출 불가 |

- 승인 기록: 07 해시, 기준 UX 설계 revision·해시, 승인 VD 목록, 렌더러, 테마 해시. 승인 후 07이 바뀌면 `approved_modified`, UX 설계 승인이 바뀌면 `stale_design_direction`.

### design_direction 게이트 활성화

- 이미 v2인 프로젝트는 **게이트가 꺼진 상태**로 남습니다. 프리뷰 진행·승인 기록은 그대로입니다.
- 켜기: 사용자 동의 후 `migrate --to v2 --enable-gate design_direction`(계획) → `--confirm`. 기존 승인·해시·revision은 바꾸지 않고, `gate_activations`와 history `gate_enabled`를 남깁니다. 재실행은 `already_v2`.
- 켠 뒤:
  - preview `begin`·`submit`·`approve`에 design_direction 승인이 필요합니다(`design_direction_not_approved`). 진행 중인 프리뷰 작업(작성·검증)은 막지 않습니다.
  - 이미 승인된 프리뷰는 승인 유지(`preview_pre_gate_approval: true`로 표시). 다음 개정부터 게이트가 적용됩니다.
  - 프리뷰 manifest에 `design_direction_revision`(승인된 revision)이 있어야 하고, 화면별 `vd` 목록에는 승인된 VD만 쓸 수 있습니다(`preview-check`).
  - design_direction을 다시 열면 preview도 무효화됩니다(사용자가 재검토를 요청했을 때만).
- 끄는 명령은 없습니다(되돌리려면 백업·Git 이력으로 `design.json` 복원).

### 의미 해시(sem-2)

| 형식 | 의미 해시 처리 |
|---|---|
| `.ts`·`.js`·`.mjs`·`.cjs`·`.mts`·`.cts` | 템플릿 리터럴(백틱)·줄 이음이 없을 때만 줄 전체 주석·빈 줄·줄 앞뒤 공백을 무시. 그 밖에는 원본 |
| `.css` | 문자열은 그대로, 주석 제거(두 토큰을 붙여 놓은 주석은 표시를 남김), 문자열 밖 공백은 한 칸. 따옴표 없는 `url(…)`이 있으면 원본 |
| `.md` | 코드에서 파일 이름이 참조되지 않으면 제외, 참조되면 원본 |
| `.tsx`·`.jsx`·`.html`·`.json`·`.svg` 등 | **원본**(JSX 안 `//`는 화면 글자, 인라인 요소 사이 공백·줄바꿈은 렌더 차이) |

- 기록에는 `semantic_algo: "sem-2"`를 남깁니다. 알고리즘 표시가 없는 이전 기록(M1-2)은 다시 계산·교체하지 않고 **원본 트리 해시로 비교**합니다(보수적).

### v2 무효화 규칙(파일 기준)

| 바뀐 것 | v1 | v2 |
|---|---|---|
| 승인된 00–05 | 해당 단계 `approved_modified` | 같음(+ `check`가 변경 영향 분류를 붙이고, 판단이 필요하면 `requires_user_decision`) |
| 테마 파일(`config.theme_file`) | 승인 대상 아님 | 프리뷰만 `theme_changed`. UX Spec·Design Direction 승인 유지. `reopen --stage preview` → `preview-verify` → 재승인 |
| 프리뷰 코드의 주석·공백, 프리뷰 안 `.md` | 프리뷰 `approved_modified`(트리 해시) | 문제 아님(구현 메모 경고). 의미 해시가 같으면 재승인·재검증 불필요 |
| 프리뷰 코드·CSS·설정 | 프리뷰 `approved_modified` | 같음(의미 해시가 바뀜) |
| 06 문서 | 프리뷰 `approved_modified` | 같음 |

- 04 문서에 토큰 값이 있는 한, v2에서도 토큰 값 변경은 04(UX Spec 승인 산출물) 변경입니다. 테마 값을 테마 파일로 옮기는 것은 M1-4(WF-D03)입니다.
- 어떤 경우에도 엔진은 분류 결과로 승인 상태를 자동으로 바꾸지 않습니다. 재검토는 사용자 확인 후 `reopen`으로만 합니다.

### 전환(`migrate --to v2`)

```bash
python3 $SKILL/scripts/product_design.py migrate --project "$PWD" --to v2 --theme-file design-profile/theme.json          # 계획만 출력
python3 $SKILL/scripts/product_design.py migrate --project "$PWD" --to v2 --theme-file design-profile/theme.json --confirm # 사용자 승인 후
```

- **사전 점검**: planning 게이트 통과, outdated 아님, `check` 문제 없음. 하나라도 어긋나면 `migrate_precheck_failed`(쓰지 않음).
- **추가만 합니다**: 기존 승인·제출 기록, revision, 해시, history는 그대로입니다. 쓴 뒤 다시 읽어 기존 필드가 하나라도 다르면 원래 파일로 되돌립니다(`migrate_failed`, `restored: true`).
- **승격 금지**: 기존 승인을 design_direction 승인으로 옮기지 않습니다. design_direction은 ux_spec이 승인돼 있으면 `not_started`, 아니면 `locked`입니다.
- **멱등**: 이미 v2이고 필드가 모두 있으면 `already_v2`(아무것도 쓰지 않음). 중간에 멈춰 필드가 빠진 v2는 빠진 필드만 채우고 history에 `migration_repaired`를 남깁니다.
- **테마 파일**: 프로젝트 안의 존재하는 파일. 승인 산출물(00–07)·기획 문서·`.ai-workflow/`는 불가. 이미 설정된 테마 파일을 전환 명령으로 바꾸지 않습니다(`theme_file_conflict`).
- **백업**: 상태 파일이 Git 추적·clean이면 생략, 아니면 `.ai-workflow/backup/design/design.json.pre-v2`.
- v1으로 되돌리는 명령은 없습니다. 되돌리려면 백업이나 Git 이력에서 `design.json`을 복원합니다.

### 테마 계약(WF-D03)

**우선순위(v2, 테마 파일이 `design-theme/v1` 계약을 따를 때)**

| 무엇 | 기준 |
|---|---|
| 의미 토큰 **이름·의미**와 제약 | 승인된 04 문서(UX Spec). 바꾸려면 ②로 UX Spec 개정 |
| 실제 **렌더링 값** | 테마 파일(`config.theme_file`) |
| 테마에 없는 04 토큰의 값 | 04 값(승인 당시 기준값)으로 렌더 |
| 04 문서의 값 | **승인 당시 기준 기록으로 보존**. 엔진은 04를 자동 수정하지 않습니다 |

- 04 값과 테마 값이 다르면 `theme-check`의 `divergence`에 `{token, approved_04_value, theme_value, applied: "theme"}`와 출처(`sources`: 04의 ux_spec revision·해시, 테마 경로·해시)를 보고합니다. 프리뷰 승인 기록에는 그때의 테마 해시가 남아 변경 이력을 추적할 수 있습니다.
- 계약이 아닌 이전 형식 테마 파일(M1-2)은 해시만 추적합니다(값·tokens.css 검사 없음, 기존 프로젝트를 막지 않음).

**스키마(`templates/theme.example.json`)**

| 키 | 내용 |
|---|---|
| `schema` | `"design-theme/v1"` |
| `name`, `version` | 테마 이름(필수), 버전 |
| `primitives` | 원시 값(브랜드 팔레트 등) `{이름: 값}` |
| `tokens` | 의미 토큰 `{04에 있는 이름: 값 또는 "{원시 이름}"}` |
| `css` | `{file: "design-preview/src/tokens.css", var_pattern: "--{dashed}"}`(기본값, `{dashed}`는 `.`→`-`) |

- 검사(`theme-check`, 프리뷰 검사에도 포함): 이름 형식, 원시 값 참조, 색 값·길이 값 **형식**(값 자체는 엔진이 정하지 않음), 04에 없는 이름(②), tokens.css 변수 누락·값 불일치. `--print-css`는 기대 CSS를 출력만 합니다(파일을 쓰지 않음).
- 승인 영향: 테마 값만 바뀌면 UX Spec·Design Direction 승인은 유지되고, 승인된 프리뷰만 `theme_changed`(다시 검증·승인). 테마에 토큰 이름을 더하거나 빼면 ②(UX Spec).

**테마 파일 경로 변경**: `migrate --to v2 --theme-file <새 경로> --replace-theme-file`(계획) → `--confirm`. 새 파일은 계약 검사를 통과해야 하고, `theme_history`에 `{from, to, from_hash, to_hash, at}`, history에 `theme_file_changed`를 남깁니다. 내용이 같으면 프리뷰 영향 없음, 다르면 승인된 프리뷰가 `theme_changed`. 이전 파일은 지우지 않습니다.

### 렌더러 경로(WF-D04)

| 07 렌더러 | 경로 | 06에 필요한 기록(게이트 켜짐) |
|---|---|---|
| `code`(기본) | UX Spec + 07 + 테마 → React 프리뷰 | 없음 |
| `figma` | … → Figma 디자인 참조 → React 프리뷰 | 렌더 범위 화면마다 '외부 디자인 참조'에 Figma 링크 |
| `both` | 두 경로 결과 비교 → 화면별 선택 → React 프리뷰 | '렌더러 비교'에 화면별 선택(code·figma)과 근거, figma를 고른 화면은 링크 |

- **어느 경로든 최종 승인은 같습니다**: `design-preview/` 트리 해시 + 06(시각 디자인 승인).
- Figma를 쓸 수 없으면(호출 한도 등) 06 '사용 렌더러'를 `code`로 바꾸고 '전환 사유'를 적으면 Code-first로 진행합니다. code가 아닌 다른 경로로 바꾸려면 Design Direction을 다시 엽니다.
- 프리뷰 승인 기록에 `renderer: {planned, used, switched, reason}`을 남깁니다. 엔진은 Figma를 호출하지 않습니다.
