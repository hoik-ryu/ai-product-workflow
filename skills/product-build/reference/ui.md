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
- 예외: `ui-map except --token <이름> --reason "<사유>" --note "<사용자 문장>"`. 사유와 사용자 문장이 모두 필요합니다.
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

## 5. 아직 하지 않는 것(M3.3 이후)

상태 증거(상태 ID 태그·E2 판정), 수동 증거(EM) 기록, 브라우저 검증 리포트, UI 검토·수정 요청 루프, UI 배치 사용자 승인 기본값 적용, Figma 입력·시각 비교(M3.7).
