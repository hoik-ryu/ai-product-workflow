# 디자인 변경 영향 분류 (WF-D01, `impact --design`)

디자인 변경 요청이 어느 승인 단계에 영향을 주는지 **결정적으로** 분류합니다. 결과는 읽기 전용 보고이며, 상태 파일과 문서를 바꾸지 않습니다. 실제 재검토는 기존 명령(`reopen`)으로, 사용자 확인을 받은 뒤 합니다.

- 기존 `impact`(기획 변경 영향)는 그대로입니다. `--design`을 붙였을 때만 이 분류가 동작합니다.
- 프로젝트 고유 정책(명세가 위치를 고정하는지, 명세 수치가 최솟값인지 등)은 **엔진에 넣지 않습니다.** 요청의 사실(facts) 값으로 받습니다.

## 1. 다섯 가지 유형

| 키 | 유형 | 예 | 목표 단계(로드맵) | 현재 엔진에 있음 | 지금(v1) 실제로 적용되는 단계 |
|---|---|---|---|---|---|
| `info_behavior` | ① 정보·행동 | 정보 항목 추가·삭제, 행동·상태·흐름, 명세가 고정한 위치 | `ux_spec` | 예 | `ux_spec` |
| `token_semantics` | ② 토큰 의미·이름 | 의미 토큰 이름 추가·삭제·변경 | `ux_spec` | 예 | `ux_spec` |
| `theme_value` | ③ 테마 값 | 이름은 같고 값만 변경, 같은 계열 토큰 값 누락 | 테마 게이트(`theme`, WF-D03) | **아니요** | `ux_spec` — 토큰 값이 04에 있고 v1 규칙 "토큰 변경 = UX 설계 변경" |
| `visual` | ④ 시각 표현 | 반경·굵기·테두리·간격, 명세 범위 안 치수 | Design Direction(`design_direction`, WF-D02) | **아니요** | `preview` — v1은 시각 표현을 프리뷰에서 반영 |
| `implementation` | ⑤ 구현 메모 | 주석, 설정·의존성, 보이는 결과와 무관한 구현 | 렌더 결과(`render`) | **아니요** | `preview` — v1은 프리뷰 트리 전체를 해시하므로 승인된 프리뷰는 다시 승인 필요 |

- 목표 단계가 없으면 결과에 `target_available: false`와 `effective_stage`(실제 적용 단계), `effective_reason`(이유)을 함께 냅니다. 없는 단계를 있는 것처럼 처리하지 않습니다.
- `design.json`의 `config.workflow`가 없으면 v1입니다. v2 규칙은 §5의 워크플로별 표를 따릅니다(WF-D05).

## 2. 판정 상태

| 상태 | 의미 |
|---|---|
| `classified` | 모든 사실이 규칙으로 확정됨 |
| `conditional` | 유형을 정했지만 명세에 없는 조건에 따라 달라짐. `possible_categories`와 사실별 `condition`을 냄 |
| `needs_review` | 자동으로 확정하지 않음(사람 판단). 판단할 수 없는 사실이 하나라도 있으면 항목 전체가 이 상태. 부분 분류와 추정 영향은 참고로 남기고 `primary`는 비움 |
| `excluded` | 변경 요청이 아님(결함 보고, 기획 문서 변경) |

## 3. 입력 A — 변경 요청(사실 목록)

LLM이 사용자 요청을 사실로 정리해 **프로젝트 밖** 임시 파일에 쓰고 `impact --design --request <파일>`로 넘깁니다(프로젝트 안에 두면 미커밋 변경이 생김).

```json
{
  "schema": "design-change-request/v1",
  "items": [
    {"id": "R1", "summary": "예약 추가 버튼을 헤더로", "facts": [
      {"kind": "placement", "component": "CMP-010", "screen": "SCR-211", "from": "오른쪽 아래", "to": "헤더", "spec_rule": "fixed", "refs": ["UXD-026"]}
    ]}
  ]
}
```

공통 필드: `screen`(SCR), `component`(CMP), `refs`(SCR·CMP·UXD·US·AC·FLOW·FR·NFR·C-xx). 승인 문서에 없는 참조가 있으면 `needs_review`입니다.

| `kind` | 필드 | 규칙 |
|---|---|---|
| `info` | `op`(add·remove·reorder·relabel·change) | ① 확정 |
| `behavior` | 행동·상태·흐름 변경 | ① 확정 |
| `placement` | `spec_rule`: `fixed` · `free` · (없음) | fixed → ①, free → ④, 없음 → ① 조건부(대안 ④) |
| `token_name` | `op`(add·remove·rename), `token`/`tokens` | 04 토큰 표와 대조. add인데 이미 있음·remove인데 없음 → `needs_review`, 그 외 ② |
| `token_value` | `token`, `from`/`to`, `op`(`not_updated`=같은 계열 누락) | 04에 있는 이름 → ③, 없는 이름 → ②(새 의미 토큰) |
| `style` | `property`, `within_tokens`(false면 토큰 밖) | 표현 속성(radius, border, shadow, elevation, font_weight, font_size, font_family, line_height, color_usage, spacing, opacity, motion, safe_area, density) → ④ 확정. 구조 표현(icon, grouping, layout, alignment, illustration) → ④ 조건부(대안 ①). 그 외 → `needs_review` |
| `dimension` | `value`, `spec`: `{value, bound: min·max}` 또는 `{values, bound: fixed·enumerated}` | 범위 안 → ④, 범위 밖 → ④ + `spec_conflict`. `bound` 없음 → ④ 조건부(대안 ①) |
| `notation` | 명세 표기 문자열 변경 | 항상 `needs_review`(보이는 글자인지 정보 순서인지 사람이 판단) |
| `implementation_note` | 설명 | ⑤ 확정 |
| `defect` | 결함 보고 | `excluded` |
| 그 밖 | - | `needs_review` |

**플래그**와 안내: `spec_conflict`(명세 값과 다름 — 되돌리거나 ①로 UX Spec 개정), `outside_tokens`(승인 토큰 밖 값), `accessibility_check`(테두리·색·불투명도·글자 크기 — 대비 확인 필요, 자동 검사는 M2), `new_visual_value`(안전 영역·밀도처럼 새 시각 정책 값), `theme_omission`(같은 계열 토큰 누락).

## 4. 입력 B — 파일 차이(파일·토큰 이름 기준)

`impact --design [--base <커밋>]`(기본 `HEAD`)은 기준 커밋과 작업 트리(미추적 파일 포함)의 차이를 파일마다 분류합니다.

| 파일 | 규칙 |
|---|---|
| `docs/planning/*`, `.ai-workflow/state.yaml` | `excluded`. 기존 `impact`(기획 영향)·`rebase` 안내 |
| `04-ui-system.md` | 토큰 표를 이전·현재로 비교: 이름 추가·삭제 → ②, 값만 변경 → ③(묶음 행 `a.b.c / d` 펼침). 토큰 표 밖 내용 변경 → `needs_review`(바뀐 CMP ID를 근거로) |
| `00`–`03`, `05` | ①(바뀐 헤딩 블록·행의 ID를 근거로). 00은 UX Planning 산출물이므로 영향 단계가 `ux_planning`부터 |
| `06-preview-review.md` | ⑤ |
| `design-preview/**/tokens.css` | CSS 변수 이름 추가·삭제 → ②, 값만 변경 → ③, 주석만 → ⑤ |
| `design-preview/**/*.css` | ④ |
| `design-preview/**/*.ts(x)·js(x)` | 주석·공백만 → ⑤, 그 외 → `needs_review` |
| `design-preview/preview.manifest.json` | `needs_review`(화면·상태 목록과 02의 관계) |
| v2 테마 파일(`config.theme_file`) | 계약 파일: 토큰 이름 추가·삭제 → ②, 해석된 값 변경(원시 값 포함) → ③, 해석된 값이 같으면 ⑤. 이전 형식 파일은 ③ |
| 그 밖의 `design-preview/` 파일 | ⑤ |
| 위에 없는 파일 | `unrelated_paths`로만 보고 |

파일이 속한 단계(승인 산출물)는 분류와 관계없이 영향 목록에 들어갑니다.

## 5. 영향과 재승인

유형마다 현재 `design.json` 상태로 계산합니다(읽기만 함).

| 적용 단계 상태 | `action` | 재승인 |
|---|---|---|
| `approved` | `reopen --stage <단계>` | 그 단계 + 승인·제출된 하위 단계(워크플로 단계 순서) |
| `awaiting_approval` | `reopen`(수정 요청) 후 재제출 | 그 단계 + 제출된 하위 단계 |
| `in_progress` | 현재 revision에서 반영 후 done·제출 | 없음 |
| `locked`·`not_started` | 그 단계를 진행할 때 반영 | 없음 |

### 워크플로별 적용 단계(무효화 규칙)

| 유형 | v1 | v2 |
|---|---|---|
| ① 정보·행동 | ux_spec 재검토 → 하위(preview) 무효 | ux_spec 재검토 → 하위(design_direction·preview) 무효 |
| ② 토큰 의미·이름 | ux_spec 재검토 → 하위 무효 | 같음 |
| ③ 테마 값 | ux_spec(토큰 값이 04에 있음) | `config.theme_file`이 있으면 **preview만**(ux_spec·design_direction 보존, `preserved`에 표시). 없으면 v1과 같음 |
| ④ 시각 표현 | preview | design_direction(재검토) + 프리뷰 렌더 영향. 게이트가 켜져 있으면 design_direction 재검토가 preview도 무효화 |
| ⑤ 구현 메모 | preview(트리 해시 때문에 승인된 프리뷰는 재승인) | 의미 해시(sem-2)가 바뀌지 않으면 **재승인 없음**. `.tsx`·`.jsx`는 의미 해시를 쓰지 않으므로 주석만 바뀌어도 preview. 요청만으로 알 수 없으면 재승인 없음 + `render_note` 안내 |

- `conditional`·`needs_review` 항목은 `requires_user_decision: true`이고, 모든 항목은 `auto_apply: false`입니다. 분류는 상태를 바꾸지 않습니다.
- v2 `check`는 승인·제출 후 바뀐 파일에 이 분류를 붙여 보여 줍니다(`classification`, `requires_user_decision`, `resolution`).

## 6. 출력

```json
{"ok": true, "mode": "design", "read_only": true,
 "workflow": {"declared": null, "applied": "v1"}, "engine_stages": ["ux_planning", "ux_spec", "preview"],
 "source": {"mode": "request", "request": "..."} ,
 "items": [{"id", "summary", "status", "categories": [{"key", "no", "label"}], "primary", "possible_categories", "flags",
            "facts": [{"kind", "category", "confidence", "alternative", "condition", "reason", "evidence", "checked_against", "flags"}],
            "impact": [{"category", "target_stage", "target_available", "effective_stage", "effective_reason", "effective_status",
                        "action", "reapproval_required", "reapproval_stages", "invalidates"}],
            "possible_impact": [...], "reapproval_required", "reapproval_stages", "notes"}],
 "unrelated_paths": [], "summary": {"classified", "conditional", "needs_review", "excluded", "by_category", "reapproval_stages"},
 "categories": {...}, "rules_ref": "skills/product-design/reference/change-impact.md", "notes": []}
```

## 7. 사용 순서(Skill)

1. 사용자의 수정 요청이나 프리뷰 피드백을 사실 목록으로 정리합니다. 확인되지 않은 정책(위치 고정 여부, 수치 성격)은 지어내지 말고 필드를 비웁니다(조건부로 나옴).
2. `impact --design --request <프로젝트 밖 파일>`을 실행해 유형·영향·재승인 단계를 사용자에게 보여 줍니다.
3. `needs_review`·`conditional` 항목은 사용자에게 판단을 받습니다. 자동으로 확정하지 않습니다.
4. 재검토가 필요하면 영향(하위 승인 무효화)을 설명하고 확인을 받은 뒤 `reopen`합니다.
