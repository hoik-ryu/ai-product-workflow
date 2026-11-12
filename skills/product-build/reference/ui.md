# Design-to-Code: UI 대응표·토큰·UI Brief·UI Plan (M3.1·M3.2)

승인된 UX Spec(02·04·05), Design Direction(07, v2), 테마 계약을 **제품 UI 코드**와 기계적으로 대조합니다.
엔진은 프레임워크·UI 라이브러리를 모릅니다. 파일 경로, 내보낸 이름(문자열), ID, CSS 변수, 프로젝트 명령의 JSON 출력만 다룹니다.

## 1. 기록 위치와 소유

| 기록 | 위치 | 작성 |
|---|---|---|
| UI 대응표 | `docs/build/ui-map.json` (`pb-ui-map/v1`) | `ui-map` 명령만(직접 편집 금지). 계획 승인 해시 대상이 아니므로 바꿔도 계획이 무효가 되지 않음 |
| UI Brief | `.ai-workflow/build/ui/<배치>/brief.json` (`pb-ui-brief/v1`) | **엔진**(`ui-brief`). 직접 고치면 `brief_modified` |
| UI Plan | `.ai-workflow/build/ui/<배치>/plan.json` (`pb-ui-plan/v1`) | **Claude**(Brief의 skeleton에서 시작) |
| UI Plan 검증 기록 | `.ai-workflow/build/ui/<배치>/validation.json` | 엔진(`ui-plan-validate`) |

- 화면별 문서를 새로 만들지 않습니다. 사람용 요약은 기존 구현 계획 문서와 대화 보고로 충분합니다.
- `design-preview/`는 **시각 참고만** 합니다. 대응표·토큰 출력·UI Plan(시각 참고 필드 `visual_ref` 제외)에 프리뷰 경로가 있으면 거부합니다.

## 2. UI 대응표(CMP ↔ 코드 부품)

```json
{ "format": "pb-ui-map/v1",
  "components": {
    "CMP-001": { "source": "existing", "path": "frontend/src/components/Button.tsx", "export": "Button", "note": "<사용자 확인 문장>" },
    "CMP-002": { "source": "built", "path": "...", "export": "SeatMap", "built_by": "B0" },
    "CMP-003": { "source": "library", "package": "<라이브러리@버전>", "export": "DataTable", "note": "..." } },
  "tokens": { "format": "css-vars", "file": "frontend/src/styles/tokens.css", "var_pattern": "--{dashed}", "aliases": { "color.primary": "--brand" } },
  "exceptions": { "tokens": [ { "token": "radius.md", "reason": "...", "note": "..." } ],
                  "audit":  [ { "path": "src/legal/*", "value": "#FF0000", "reason": "...", "note": "..." } ] },
  "history": [ ... ] }
```

**A. 기존 디자인 시스템이 있는 프로젝트**
1. `ui-map candidates`: 컴포넌트 경로(`[ui].component_roots` 또는 `paths.components`)에서 파일 속 `CMP-xxx` 표지나 파일 이름 = CMP 이름인 후보를 보여 줍니다(후보일 뿐).
2. 사용자에게 후보를 보여 주고 확인받은 것만 `ui-map register --cmp CMP-001 --path <파일> --export <이름> --note "<사용자 문장>"`(라이브러리는 `--source library --package`).
3. `ui-map tokens --file <기존 토큰 CSS> [--alias 토큰=--변수] --note`로 토큰 출력을 지정합니다. CSS 변수가 아닌 형식은 `--format command --export-cmd "<토큰 이름→값 JSON을 출력하는 프로젝트 명령>"`.

**B. 새 프로젝트**
1. 대응표가 비어 있습니다. 공통 부품은 계획의 B0(foundation) `components.new`로 만듭니다.
2. B0 실행 중 부품을 만든 뒤 `ui-map register --cmp CMP-001 --source built --batch B0 --path <파일> --export <이름>`(계획의 신규 목록·배치 범위 안만 허용).
3. 토큰 출력 파일은 `token-check`의 `expected_css`로 만들고 `ui-map tokens --file ... --note`로 지정합니다.

**중복 생성 방지**
| 단계 | 검사 | 코드 |
|---|---|---|
| 계획(`plan-validate`·`submit`·`approve`) | 대응표의 기존·라이브러리 부품, 또는 다른 배치가 만든 부품을 `components.new`에 넣음 | `cmp_already_mapped` (대응표가 있을 때만) |
| 계획 | 같은 CMP를 두 배치가 신규 생성 | `cmp_new_duplicate`(M2) |
| 배치 완료 후(`ui-map check`) | 끝난 배치의 `components.new`가 대응표에 없음 | `new_not_registered` |
| 코드(`ui-map check --batch`) | 배치 범위 파일이 이미 대응된 CMP의 표지를 가짐 / 대응된 부품과 같은 이름 파일 | `duplicate_component` / 경고 `possible_duplicate` |
| UI Plan | 대응된 CMP를 로컬로 새로 만듦, 다른 이름 사용, 대응된 이름과 같은 로컬 부품 | `cmp_mapped_rebuilt`, `cmp_part_mismatch`, `duplicate_of_mapped` |

## 3. 토큰 대응(`token-check`)과 직접 값 감사(`token-audit`)

- 기준: v2 테마 계약이 있으면 테마 적용값(+테마에 없는 04 값), 없으면 04 토큰 표. 계산은 `/product-design`의 읽기 전용 함수를 씁니다.
- `css-vars`: 변수 이름 = 별칭 또는 `var_pattern`(기본 `--{dashed}`: `color.primary` → `--color-primary`). 같은 파일 안 `var(--x)` 참조를 풀고, 색 표기(`#fff` = `#FFFFFF`)·공백·대소문자를 정규화해 비교합니다.
- 결과: `missing`·`mismatch`(차단, 종료 코드 2), `excepted`(프로젝트 예외와 사유), `extra`(승인 토큰이 아닌 프로젝트 변수, 정보), `expected_css`.
- 예외: `ui-map except --token <이름> --reason "<사유>" --note "<사용자 문장>"`(같은 토큰이면 변경), 삭제는 `ui-map unexcept --token <이름> --reason --note`. 추가·변경·삭제 모두 사유와 사용자 문장이 필요하고, `exceptions.log`에 이전 기록과 함께 남습니다(지우지 않음).
- 예외가 바뀌면 토큰 기준이 바뀝니다. 그 기준으로 검증된 UI 배치는 무효(`check` → stale)가 되어 `verify`로 다시 검사합니다(명령 출력의 `invalidated_batches`).
- `token-audit [--batch Bxx]`: 배치 범위(없으면 `paths.source`) 파일의 직접 색 값(설정 시 길이 값)을 찾습니다. 기본은 경고(`[ui.audit] mode = "block"`이면 차단). 예외는 `ui-map except --audit-path <경로 패턴> [--value <값>] --reason --note`.
- 새 토큰 이름이 필요하면 코드에서 만들지 않고 `/product-design`의 ②(UX Spec 04 개정)로 안내합니다.

## 4. UI Brief(엔진)와 UI Plan(Claude)

1. `ui-brief --batch Bxx`(승인된 계획, 디자인 L2·L3, 입력 변경 없음): 배치 화면의 02 블록(목적·역할·플랫폼·경로·상태 표·행동·입력·정보·컴포넌트), 05의 AC→상태, 04 CMP 필드, 07의 **승인된** VD, 승인 토큰, 대응표, 배치 작업·선행 배치의 API 작업, 계약 파일, test_plan을 묶습니다. Must 화면의 정의된 상태는 `required: true`입니다.
2. UI Plan이 없으면 결과의 `skeleton`을 `.ai-workflow/build/ui/Bxx/plan.json`으로 저장해 채웁니다.

```json
{ "format": "pb-ui-plan/v1", "batch": "B1", "brief_digest": "<Brief digest>",
  "screens": { "SCR-001": {
      "tree": [ { "part": "SeatStatusPage", "local": true, "file": "<배치 범위 파일>", "children": [ { "part": "SeatMap", "cmp": "CMP-002" } ] } ],
      "states": { "SCR-001-ST2": { "how": "route|query|prop|story|test|other", "ref": "<재현 방법>" } },
      "interactions": [ { "action": "<02 행동 열 그대로>", "trigger": "...", "result": "...", "to_state": "SCR-001-ST2 또는 SCR-002", "acs": ["AC-001"] } ],
      "data": [ { "name": "seats", "source": "api|mock|local|props", "contract": "GET /api/seats", "task": "B1-T1", "mock_file": "<배치 범위>" } ],
      "acs": { "AC-001": { "states": ["SCR-001-ST1"], "tests": ["unit"] } },
      "visual_ref": "design-preview/... (시각 참고만, 선택)" } },
  "components": { "CMP-001": { "action": "reuse|new", "part": "Button" } } }
```

3. `ui-plan-validate --batch Bxx`가 통과한 뒤 구현합니다.

| 오류 코드 | 의미 |
|---|---|
| `brief_stale` / `brief_modified` | 승인 문서·계획·대응표가 바뀌어 Brief가 낡음 / Brief를 엔진 밖에서 고침 |
| `screen_missing`·`screen_unknown` | 배치 소유 화면 누락·남의 화면 |
| `state_missing`·`state_unknown`·`state_how` | 02의 정의된 상태 누락, 없는 상태, 재현 방법 없음 |
| `tree_missing`·`tree_format`·`unknown_cmp`·`cmp_unplanned` | 트리 없음·형식, 04에 없는 CMP, 대응표·신규 목록에 없는 CMP |
| `cmp_mapped_rebuilt`·`cmp_part_mismatch`·`duplicate_of_mapped`·`cmp_new_not_planned` | 중복 생성 방지(§2) |
| `out_of_scope_file`·`mock_out_of_scope`·`preview_reuse` | 배치 범위 밖, 프리뷰 경로 사용 |
| `action_missing`·`action_unspecified`·`interaction_state` | 02 행동 누락, 명세 밖 행동(원장 ID 없으면 거부), 잘못된 전이 |
| `data_format`·`data_contract_missing`·`data_task_unknown` | 데이터 출처, API·Mock 계약 식별자, 관련 없는 작업 |
| `ac_unlinked`·`ac_not_in_batch`·`ac_state_unknown` | 화면에 연결된 AC 누락, 배치 밖 AC, 없는 상태 |

경고: `contract_not_found`(계약 파일에서 못 찾음), `ac_no_test_plan`, `new_unused`.

## 5. 화면 상태 증거(M3.3)

UI Brief를 만든 배치(`.ai-workflow/build/ui/Bxx/brief.json`)만 대상입니다. 만들지 않은 배치는 M2 판정(AC 증거) 그대로입니다.
`verify --batch Bxx`가 기존 실행·리포트 검증을 그대로 쓰고, 그 결과에서 상태 증거를 판정해 `build.json`의 `verification.ui`에 기록합니다.

- 태그: AC와 같은 규칙입니다. 테스트 이름 `[SCR-001-ST2] …`(묶음 `[SCR-001-ST1, SCR-001-ST3]`), pb-json 케이스의 `states` 필드, JUnit property `state`/`states`, `tag_style = "prefix"`이면 `SCR-001-ST2 / AC-001:` 머리. 이름에 ID만 적힌 것은 E1(언급)입니다.
- 판정: `verified`(E2: 유효한 실행에서 태그된 테스트·브라우저 결과 통과) · `failing` · `not_run` · `untested`(E0/E1) · `manual_only`(EM만) · `invalid_run`.
- 목표: Must 화면의 정의된 상태(Brief `required: true`)는 **E2 필수**, 나머지는 경고. 필수 상태가 E2가 아니면 verify가 실패합니다.
- 기록: 상태마다 증거의 출처(`test`·`browser`·EM ID), 단계, 케이스, 실행 ID·시각, 코드 버전(`code_tree`), 결과. AC ↔ 상태 연결(`ac_links`: 05의 AC→상태 + UI Plan `acs`)과 "AC는 통과했지만 연결 상태 증거 없음" 경고.
- verify가 함께 확인하는 것: UI Brief가 현재 입력과 같은지(`brief_stale`), UI Plan이 현재 Brief로 검증됐는지(`ui_plan_not_validated`), `token-check`(불일치·누락 차단, 예외는 사유와 함께 기록), `token-audit`(프로필 mode대로).
- 무효화: 화면별 입력 기준(02 화면 블록·연결된 05 AC 행·관련 VD·화면 CMP의 04 내용과 대응·UI Plan의 그 화면) + 토큰 기준(승인 토큰·출력 설정·예외) + UI Plan 컴포넌트 목록. 바뀌면 그 배치는 stale이 되고 `ui-evidence`가 영향받은 화면·상태를 보여 줍니다. 승인 문서 자체가 바뀌면 M2 규칙대로 계획 전체가 outdated입니다.

### 수동 증거(EM)
```
evidence-manual add --batch Bxx --state SCR-002-ST3 [--ac AC-003] --check "<무엇을 어떻게 확인>" \
  --method keyboard|screen_reader|visual|device|exploratory|other --result passed|failed [--file <근거 파일>] [--by <확인자>] --note "<사용자 확인 문장>"
evidence-manual list [--batch Bxx]
evidence-manual revoke --batch Bxx --id EM-001 --reason "<사유>" --note "<사용자 문장>"
```
- 사용자 확인 문장이 없으면 거부합니다(Claude가 대신 확인했다고 기록하지 않음). 구현 제출 이후, 실행 중 배치가 없을 때만 기록합니다.
- 기록: 대상(상태·AC), 확인 내용·방법·결과, 근거 파일 해시(스크린샷은 `kind: screenshot` 첨부), 확인자·시각, 코드 버전(배치 범위 해시·HEAD), 화면 입력 기준.
- EM은 실행 증거와 따로 표시합니다. **필수 상태의 E2를 대신하지 않고**(`manual_only`), AC 판정에도 반영하지 않습니다(`ac-report`에 표시만). 실패한 EM은 그 상태를 `failing`으로 만듭니다.
- 코드·화면 입력·근거 파일이 바뀌면 EM은 `stale`입니다. verified·approved 배치에 EM을 추가·철회하면 그 배치는 재검증 대상(stale)입니다.

## 6. 브라우저 검증(M3.4)

엔진은 브라우저 도구를 설치·호출하지 않습니다. 프로필의 검증 단계가 낸 리포트 형식과 판정만 다룹니다.

```toml
[[verify.steps]]
name = "browser"
stage = "browser"                 # browser 또는 e2e
run = "<프로젝트 명령>"
requires = ["browser"]            # verify --available browser일 때만 실행, 아니면 not_run
report = { format = "pb-ui", file = "ui.json" }   # 실행별 폴더($PB_REPORT_DIR)만. 고정 경로(path)는 거부
```

```json
{ "format": "pb-ui-report/v1", "run_id": "<$PB_RUN_ID 그대로>", "tool": "...", "status": "completed|not_run", "reason": "...",
  "results": [ { "screen": "SCR-001", "state": "SCR-001-ST1", "viewport": "mobile", "rendered": true, "console_errors": 0,
                 "a11y": {"critical": 0, "serious": 1}, "overflow": false, "touch_target_violations": 0, "acs": ["AC-001"],
                 "interactions": [ {"name": "좌석 선택", "passed": true, "core": true, "acs": ["AC-003"]} ],
                 "screenshot": "shots/SCR-001-ST1-mobile.png" } ] }
```

| 판정 | 항목 |
|---|---|
| 차단 | `rendered: false`, 콘솔 오류 1개 이상, 접근성 critical, 핵심 상호작용 실패(02 행동은 `core: false`로 낮출 수 없음) |
| 보고(경고) | 접근성 serious, `overflow`·`clipped`, 터치 영역 위반, 핵심이 아닌 상호작용 실패, 접근성 미검사, 프로필 `browser.viewports`에 없는 뷰포트, 배치 밖 화면·정의되지 않은 상태 |
| 리포트 거부(`report_invalid`) | 잘못된 JSON·형식, `run_id`가 이번 실행과 다름(오래된 결과), 결과 없음, `rendered` 없이 스크린샷만, 스크린샷이 실행 폴더 밖·없음 |
| 그 밖(M2 그대로) | 시간 초과 `timeout`, 실행 전에 만들어진 리포트, 리포트 없음, 종료 코드와 리포트 불일치 |
| 미실행(`not_run`) | `requires` 환경 없음, 또는 도구가 `status: "not_run"` 보고 |

- 통과한 결과는 그 상태의 E2 근거, `acs`는 AC 증거(M2 판정)로 들어갑니다. 결과는 화면 상태 ID·AC·실행 ID·코드 버전과 함께 기록됩니다. 스크린샷은 실행 폴더(`.ai-workflow/build/evidence/`, Git 제외)에 해시와 함께 남깁니다.
- 필수 단계(`optional` 아님)가 `not_run`이면 M2 규칙대로 verify가 실패하고, `verification.ui.final_approval_blockers`에 남깁니다(최종 UI 승인 차단은 M3.5에서 사용). 선택 단계의 `not_run`은 경고로 기록합니다.
- 선택형 어댑터 예시: `templates/ui-adapters/react-vite-playwright/`(엔진 코드 아님, 설치는 사용자 결정).

`ui-evidence --batch Bxx`(읽기 전용): 상태별 증거·AC 연결·브라우저 판정·토큰 결과·EM 상태와, 지금 기준으로 영향받은 화면·상태.

## 7. UI 검토·수정 요청·최종 승인(M3.5)

### UI 배치의 필수 조건
- **UI 배치** = 프로필에 `[ui]`가 있는 프로젝트에서 계획상 `kind = "ui"`인 배치. foundation·non_ui 배치와 `[ui]`가 없는 M2 프로젝트는 그대로입니다.
- UI 배치는 `batch-start` 전에 현재 입력 기준 UI Brief와 검증된 UI Plan이 있어야 합니다(`ui_plan_required`). verify도 UI 흐름으로 판정합니다.

### 브라우저 미실행(`browser_pending`)
- UI 배치에서 필수 브라우저 단계(`pb-ui`, optional 아님)가 `not_run`이면 그 사유만으로는 verify를 실패시키지 않습니다. 비UI 배치에서는 필수 단계 미실행이 verify 실패(M2 규칙)이고, 선택 단계 미실행만 기록합니다. 다른 검증이 모두 통과하면 `verified` + `browser: "browser_pending"`입니다.
- 브라우저 실패·잘못된 리포트·시간 초과·필수 상태 E2 미충족·토큰 불일치는 그대로 verify 실패입니다.
- `browser_pending`인 UI 배치는 최종 UI 승인이 막힙니다. 브라우저를 실행해(`verify --available browser`) 통과하면 풀립니다.

### 검토 묶음(`ui-review --batch Bxx`)
화면별 상태 증거(출처: test·browser·EM)·브라우저 결과(뷰포트·차단·경고·스크린샷)·연결 AC 판정·토큰 검사(검증 때와 지금)·컴포넌트 대응·수동 증거 상태·수정 요청과 **승인 차단 항목**을 한 묶음으로 보여 주고 `.ai-workflow/build/ui/Bxx/review.json`에 남깁니다. 묶음 ID(`review_id`)는 내용 digest입니다.

승인 차단 항목: verified가 아님, 증거 stale(코드·UI Plan·화면 입력·토큰 기준·토큰 출력 파일), `browser_pending`, 필수 상태 E2 미충족, UI Plan 미검증, 지금 기준 토큰 불일치, stale 수동 증거, 해결되지 않은 수정 요청.

### 최종 UI 승인
```
approve batch --batch Bxx --review <review_id> --by "<승인 주체>" --note "<사용자 승인 문장>"
```
- 사용자가 화면을 직접 검토한 뒤에만 기록합니다(Claude가 대신 승인하지 않음). 차단 항목이 있거나 `review_id`가 지금 묶음과 다르면 거부합니다.
- 승인 기록: 시각, 승인 주체, 문장, 검토 묶음 ID, 코드 버전(HEAD·코드 트리·배치 범위 해시), UI 증거 digest, UI Brief digest, UI Plan 해시, 토큰 기준.
- 승인 뒤 범위 코드·UI Plan·화면 입력·토큰(예외·출력 파일)·수동 증거가 바뀌면 `check`가 stale로 기록하고 승인은 무효 표시합니다(기록은 남음). 같은 코드·같은 UI 증거로 재검증하면 승인이 유지되고, 증거가 달라지면(예: browser_pending) 다시 승인받습니다.
- 비UI 배치의 최종 승인은 M2 그대로입니다.

### 수정 요청(`ui-feedback`)
```
ui-feedback add --batch Bxx --summary "<요약>" --fact '<JSON>' [--fact ...] [--screen SCR-001] [--state ...] [--by ...] [--review <id>] --note "<사용자 원문>"
ui-feedback list [--batch]
ui-feedback decide --batch Bxx --id FB-001 --route code_fix|design_change --note "<사용자 결정>"     (미확정 분류만)
ui-feedback resolve --batch Bxx --id FB-001 --note "<확인 문장>"  |  --withdraw --reason "<사유>" --note
```
- `--fact`는 `/product-design`의 변경 사실 형식(`reference/change-impact.md` §3)입니다. 승인 명세와 다르게 구현된 것이면 `{"kind": "defect"}`.
- 분류는 `/product-design impact --design`(읽기 전용)을 그대로 씁니다. 엔진은 디자인·기획 상태를 바꾸지 않습니다.

| 분류 | 경로 | 하는 일 |
|---|---|---|
| 결함, ⑤ 구현 메모, 재승인이 필요 없는 ④ | `code_fix` | 이 배치만 `resume --batch` → 수정 → `batch-submit` → `verify` → `ui-review`. 기획·디자인·계획 승인은 그대로 |
| ①·②·③, 재승인이 필요한 ④ | `design_change` | 코드로 바꾸지 않음. `/product-design impact --design`으로 영향을 보여 주고 사용자 확인 후 `reopen` → 재승인 → 계획 갱신 → 재구현·재검증 |
| conditional·needs_review | `needs_decision` | 사용자가 `decide`로 경로를 정함(확정된 분류는 바꿀 수 없음) |

- 승인된 배치에 수정 요청이 들어오면 승인은 무효 표시되고 배치는 `verified`로 돌아갑니다. 열린 요청이 있으면 승인할 수 없습니다.
- 해결 조건: `code_fix`는 요청 뒤 배치 코드가 바뀌고 다시 검증되어야 합니다. `design_change`는 재승인 단계의 승인 revision이 바뀌어야 합니다. 거둘 때는 `--withdraw`(사유·문장). 모든 이력은 남습니다.

## 8. 아직 하지 않는 것(M3.6 이후)

실전 PoC 실행(M3.6), Figma 입력·시각 비교(M3.7).

## 9. 일상 개발 경량 검사(`ui-guard`)

T0~T2 변경(SKILL.md "일상 개발")에서 배치·구현 계획·커밋 없이 실행하는 **읽기 전용** 검사입니다. 상태 파일·승인 문서·대응표를 쓰지 않고, `GIT_OPTIONAL_LOCKS=0`으로 Git index도 갱신하지 않습니다.

**사전 조건**(없으면 exit 2): Git 저장소 루트·커밋 1개 이상(기존 preflight), 기획 승인(`require_planning`), 대응표(`no_ui_map`), 토큰 출력 설정(`tokens_not_configured`). 프로필이 없거나 `[ui]`가 없으면 기본값으로 검사하고 경고합니다.

**모드**(하나만): 기본 = base(기본 `HEAD`, `--base <ref>`) 이후 변경 파일 / `--path <파일>`(반복) = 지정 파일 / `--all` = 소스 전체 감사. `--strict`는 경고도 실패로 처리합니다.

**변경 감지**(기본 모드): `git diff --name-status --no-renames <base>`(staged·unstaged·삭제), `diff --cached`·`diff`(상태 구분), `ls-files --others --exclude-standard`(untracked). 모두 `-z`라서 한글·공백 경로가 그대로입니다. rename은 삭제 + 추가로 보입니다. 상태: `staged`, `unstaged`, `both`(stage 뒤 재수정 → 작업 트리 기준 검사, 경고), `untracked`, `deleted`, `committed`(base..HEAD 커밋). `.gitignore`에 걸린 파일·심볼릭 링크·1MB 초과 파일은 검사하지 않습니다(뒤 둘은 경고). Git 조회가 실패하면 빈 목록으로 통과시키지 않고 `git_failed`·`bad_base`.

**스냅샷**: 대상 파일과 판정 입력(대응표·토큰 CSS·테마·design.json·state.yaml·04·프로필)을 읽어 판정한 뒤, HEAD·변경 목록·내용 해시를 다시 읽어 같을 때만 결과를 냅니다. 다르면 최대 3회 다시 하고, 그래도 다르면 `snapshot_unstable`(바뀐 경로)입니다.

**검사 규칙**

| 구분 | 규칙 | 심각도 |
|---|---|---|
| 전역 | 디자인 수준 L2 이상(`design_info`). L0·L1이면 `design_not_current`(검사 결과는 참고로 함께 출력) | 오류 |
| 전역 | 토큰 CSS ↔ 승인 정본(`token_check`: v2 테마 적용값, 없으면 04 표) 불일치·누락 `token_mismatch`. 등록된 예외는 `excepted` | 항상 오류 |
| 전역 | 대응표 무결성(`map_problems`: path·export 실존, 04에 없는 CMP, 프리뷰·보호 경로) | 오류 |
| 변경 | 테마(정본) 파일 변경 `theme_changed`(T4). `/product-design` v2는 테마 값 변경을 프리뷰 재검증으로만 다루므로(UX Spec·Design Direction 승인 유지) ui-guard가 직접 막습니다 | 오류 |
| 변경 | 보호 경로(`docs/planning/`·`docs/design/`·`design-preview/`) 변경 `protected_path_changed`. 승인 기록의 해시와 같으면 `approved_change`(정보). 프리뷰 단계가 승인 전이면 프리뷰 변경은 `preview_changed` 경고 | 오류 |
| 변경 | 워크플로 상태 파일(state.yaml·design.json 등) 변경 `workflow_state_uncommitted`(소유 Skill이 쓴 것인지 확인) | 경고 |
| 대상 | 직접 값(`audit_text`, 프로필 `[ui.audit]` kinds·mode) `raw_value` | mode=warn → 경고, block → 오류 |
| 대상 | 대응표에 없는 부품(component_roots 안 새 파일·새 export) `unregistered_component` | 경고(`--strict` 실패) |
| 대상 | 이미 대응된 CMP 표지를 다른 파일에 구현 `duplicate_component` | 오류 |
| 대상 | 대응된 부품과 같은 이름 `possible_duplicate`, 04에 없는 CMP 표지 `unknown_cmp_marker`(T4) | 경고 |
| 정보 | 대상 파일이 쓰는 대응 부품(`components.reuse`) | — |

**레거시 분리**(기본 모드): 직접 값은 base 대비 새로 생기거나 바뀐 줄의 것만, 표지·중복·미등록 부품은 base에 없던 것만 이번 변경의 위반입니다. base에 이미 있던 위반은 `legacy`로 따로 보고하고 실패시키지 않습니다. 전역 검사는 레거시 구분 없이 항상 적용합니다. `--path`·`--all`은 레거시 구분 없이 모두 현재 위반으로 봅니다.

**출력**(`pb-ui-guard/v1`): `ok`, `error`, `mode`, `base{ref,sha,head}`, `snapshot{digest,attempts}`, `design`, `files[{path,state,status,kind}]`, `checks{protected,tokens,audit,map,components}`, `errors`, `warnings`, `info`, `legacy`, `route_hint[{code,type(T0~T4),next}]`, `counts`, `browser{status: not_run}`, `read_only`.

**종료 코드**: 0 통과(경고 가능) / 2 위반(`guard_failed`), 디자인 무효(`design_not_current`), 사전 조건·Git·스냅샷 차단 / 1 내부 오류.

**역할 분리**: ui-guard는 정적 검사(토큰·직접 값·대응표·보호 경로·표지)만 합니다. 모바일·PC 레이아웃(overflow·잘림·터치 영역·콘솔·접근성)은 `verify` 또는 프로젝트 브라우저 명령의 `pb-ui-report/v1` 판정 몫입니다.
