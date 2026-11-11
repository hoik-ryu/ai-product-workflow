---
name: product-design
description: 승인된 기획(PRD, User Stories, User Flows, AC)을 바탕으로 대화형 UX Planning(화면 상세 기획) → UX 설계(IA, 화면 명세, 흐름, 컴포넌트, 추적성) → 정적 UI 프리뷰 → UX·시각 디자인 승인까지 진행합니다. 사용자가 /product-design을 실행하거나 진행 중인 디자인 단계를 재개할 때 사용합니다.
argument-hint: "(인자 없음 — 상태에 따라 시작하거나 재개)"
disable-model-invocation: true
---

# /product-design — 승인된 기획 → UX Planning → UX 설계 → UI 프리뷰 → 승인

사용자의 **제품 저장소**(현재 작업 디렉터리)에서 실행합니다. 이 Skill의 기본 디렉터리를 `$SKILL`로 표기합니다.

- `reference/design-state.md`: 상태·전이·승인·무효화·표시 정책 (**먼저 읽기**)
- `reference/ux-planning.md`: UX Planning 인터뷰 방법
- `reference/ux-spec.md`: UX 설계 문서 순서·ID·추적성 규칙
- `reference/review-checklist.md`: UX·접근성 검토 체크리스트
- `reference/preview.md`: 프리뷰 경계·위치·실행·피드백
- `reference/change-impact.md`: 디자인 변경 영향 분류(`impact --design`, 다섯 유형·입력 형식·영향 계산)
- `templates/00`–`07`: 문서 템플릿(07 Design Direction은 v2), `templates/theme.example.json`: v2 테마 계약 예시, `templates/design-notes.md`: 인터뷰 기록 형식, `templates/preview/`: 프리뷰 앱 템플릿
- `scripts/product_design.py`: 모든 판정·상태 기록 (JSON 출력, 차단 시 종료 코드 2). 같은 폴더의 `pd_core.py`·`pd_theme.py`·`pd_impact.py`를 불러옵니다(직접 실행하지 않음)

호출 형식: `python3 $SKILL/scripts/product_design.py <명령> --project "$PWD" ...`

이번 실행의 사용자 입력: `$ARGUMENTS`

## 반드시 지킬 규칙

1. **상태 판정과 기록은 스크립트로만 합니다.** `.ai-workflow/design.json`을 직접 편집하지 않고, 스크립트의 차단(`"ok": false`)을 우회하지 않습니다.
2. **`state.yaml`과 `docs/planning/`은 읽기만 합니다.** 기획 범위를 바꿔야 하는 내용은 `PF`(기획 재검토 대상)로 기록하고 `/product-start` 재검토를 안내합니다.
3. **planning 게이트가 막히면 실행하지 않습니다.** 차단 사유와 해결 방법만 안내합니다.
4. **명시적 승인만 인정합니다**(`design-state.md`의 승인 규칙). UX 결정 확정, 구조 확인, UX 설계 승인, 시각 디자인 승인은 **각각** 받습니다. "좋네요" 같은 응답은 다시 묻습니다.
5. 승인된 파일이 바뀌었거나 상태와 파일이 다르면 **보고하고 멈춥니다.** 다시 승인하거나 해시를 다시 기록하지 않습니다.
6. 기존 디자인 파일을 고치기 전에 무엇을 왜 바꾸는지 설명하고 확인을 받습니다. 고치기 전에 `backup --path <파일>`을 실행합니다.
7. 이미 기획에서 확정된 사항은 다시 묻지 않습니다.
8. 프리뷰는 `design-preview/`에만 만들고 `frontend/`를 수정하거나 import하지 않습니다. 실제 API·인증·비즈니스 로직을 만들지 않습니다.
9. Git commit, push, reset, checkout, clean, stash를 실행하지 않습니다. 비밀값과 `.env`를 읽거나 만들지 않습니다.
10. 사용자와의 대화와 산출물은 한국어로 씁니다. ID, 파일명, 상태값은 영어로 유지합니다.

## 0단계 — 사전 점검(매 실행)

`check`를 실행하고 결과로 분기합니다.

| 결과 | 행동 |
|---|---|
| `engine_repo`, `not_git_repo`, `no_commits`, `planning_not_approved`, `no_workflow_state` | 사유와 해결 방법을 보고하고 멈춤 |
| `status: not_started`, `existing_paths` 있음 | 기존 파일 목록을 보고하고 멈춤(덮어쓰지 않음) |
| `status: not_started` | 1단계 |
| `design_outdated` | 7단계(기획 변경 대응) |
| `state_mismatch` | `cross_verify.problems`를 그대로 보고(승인 후 변경, 제시 후 변경, 누락 등)하고 선택지(재검토 `reopen` / 사용자 복원)를 제시하고 멈춤 |
| 정상 | `next`와 단계 상태에 따라 2–6단계로 이동 |

**재개할 때(새 세션)는 질문이나 작업 전에 먼저 3–5줄로 진행 요약을 보여 줍니다**: 현재 단계와 revision, 끝난 주제·결정 수, 미결 DQ·PF, 이번에 이어서 할 일.

상태를 보고할 때는 `design.json` 기준으로 말하고, `display_note`의 의미를 한 줄로 덧붙입니다.

## 1단계 — 시작

1. `start`를 실행합니다(미커밋 변경이 있으면 거부됨 → 커밋을 안내).
2. 사용자에게 기준(planning revision, 시작 커밋)과 4단계 진행 순서를 짧게 알립니다.

## 2단계 — UX Planning (화면 상세 기획)

`reference/ux-planning.md`를 따릅니다.

1. 처음이면 분석을 `.ai-workflow/design-notes.md`의 `## 분석`에 쓰고, `templates/00-ux-decisions.md`로 `docs/design/00-ux-decisions.md`를 만듭니다(front matter `revision`은 준비 중 revision). 주제 진행 현황 표를 채웁니다.
2. 우선순위가 가장 높은 미완료 주제로 질문 2–4개를 만들고, **제시하기 전에** `design-notes.md`에 라운드(상태 `답변 대기`, 질문 ID `R0N-Q#`, 선택지, 권장안과 근거, 관련 기획 ID)를 저장한 뒤 `pending`으로 확인합니다. 저장한 내용 그대로 제시하고 멈춥니다(`templates/design-notes.md` 형식).
3. 답을 받으면 라운드를 `답변 완료`로 바꾸고 원문을 적은 뒤, 00 문서를 갱신하고 `done --path docs/design/00-ux-decisions.md`를 실행합니다. 모호한 답은 확인 질문 라운드를, 기획 범위 변경은 `PF`로 처리합니다.
4. **재개할 때는 `check`의 `pending_round`를 먼저 봅니다.** 대기 라운드가 있으면 기록된 질문을 그대로 다시 보여 주고 답을 기다립니다(새로 만들지 않음). 없으면 00의 주제 진행 현황에서 이어 갑니다. 답을 받은 질문을 다시 묻지 않습니다.
5. 끝나면 요약(권장안으로 기록한 항목을 따로 표시)을 보여 주고 `trace --stage ux_planning` → `submit --stage ux_planning` → **"UX 결정 확정"**을 요청하고 멈춥니다. 확정하면 `approve --stage ux_planning --revision N`.

## 3단계 — UX Specification (화면 설계)

`reference/ux-spec.md`를 따릅니다.

1. `begin --stage ux_spec`.
2. 01(IA)과 02(화면 목록 + 최소 필드)를 쓰고 각각 `done`. `trace --stage structure`가 통과하면 IA·라우트 표·화면 목록을 제시하고 **"구조 확인"**을 요청하고 멈춥니다. 확인하면 `checkpoint`.
3. 03 → 02 상세 → 04 → 05 순서로 쓰고 각각 `done`. 화면에는 UX 결정(UXD)을 반영하고 참조합니다.
4. `trace --stage ux_spec`의 오류를 모두 고칩니다. `review-checklist.md`로 자체 점검하고 05에 적습니다.
5. `submit --stage ux_spec` → 요약(화면 수, 커버리지, 주요 결정, 체크리스트 이슈, 기획 피드백)과 함께 **"UX 설계 승인"**을 요청하고 멈춥니다. 승인하면 `approve --stage ux_spec --revision N`.

## 4단계 — UI Preview (시각 디자인 검토)

`reference/preview.md`를 따릅니다.

1. `begin --stage preview` → `design-preview/`가 없으면 `preview-scaffold`.
2. 토큰, mock 데이터, 화면 컴포넌트, registry, manifest를 작성합니다. `templates/06-preview-review.md`로 06 문서를 만들고 `done`.
3. `preview-verify`가 통과할 때까지 고칩니다. 실패를 성공으로 보고하지 않습니다.
4. 실행 명령과 주소(화면·상태별 링크 예시)를 안내하고 **화면별 피드백**을 요청하고 멈춥니다.
5. 피드백은 06의 `FB` 표와 `design-notes.md`에 기록합니다. 반영 전에 피드백을 사실 목록으로 정리해 `impact --design --request <프로젝트 밖 파일>`로 유형과 영향을 확인합니다(`reference/change-impact.md`). 시각 표현은 프리뷰에서 고치고(`preview-verify`, `done` 다시 실행), UX 설계 변경이 필요한 피드백은 영향(프리뷰 승인 무효화)을 설명하고 확인을 받은 뒤 `reopen --stage ux_spec`으로 처리합니다.
6. 피드백이 정리되면 `submit --stage preview` → **"시각 디자인 승인"**을 요청하고 멈춥니다. 승인하면 `approve --stage preview --revision N`.

## 5단계 — 수정 요청과 재검토

- 제출 후 수정 요청: `reopen --stage <s> --reason "<요청 요약>"` → 수정할 파일을 고치고, 그 단계의 **모든 산출물** front matter `revision`을 준비 중 revision으로 올린 뒤 각각 `done` → 다시 제출. UX 설계에서 화면 구성(IA 라우트 표와 화면 ID)이 바뀌지 않았다면 구조 확인을 다시 받지 않아도 됩니다(스크립트가 판단).
- 승인 후 변경: 영향(하위 단계 승인 무효화)을 먼저 설명하고 확인을 받은 뒤 `reopen`.
- 이전 UX 결정 변경: `refs --id UXD-###`로 영향 화면을 보고합니다.
- 디자인 변경 요청은 먼저 `impact --design`으로 분류합니다(① 정보·행동, ② 토큰 의미·이름, ③ 테마 값, ④ 시각 표현, ⑤ 구현 메모). 결과의 `effective_stage`·`reapproval_stages`를 사용자에게 보여 주고, `needs_review`·`conditional` 항목은 사용자 판단을 받습니다. 목표 단계가 아직 없는 유형(`target_available: false`)은 없다고 설명하고, 지금 적용되는 단계로 처리합니다. 분류 결과만으로 `reopen`하지 않습니다(사용자 확인 필요).
- 작업 트리의 디자인 파일 변경은 `impact --design`(기본 기준 `HEAD`)으로 파일·토큰 이름 기준 분류를 볼 수 있습니다.

## 6단계 — 완료 보고

세 단계가 모두 승인되면 보고합니다: 기준 planning revision, 단계별 승인 revision, 화면 수·컴포넌트 수·커버리지, 미결 DQ·PF, 프리뷰 실행 방법, 다음 단계. 다음 단계인 `/product-build`(planning·init·design 승인을 모두 확인하고 구현)는 아직 구현되지 않았으므로, 있다고 말하지 않습니다.

커밋은 사용자가 합니다. 디자인 단계가 만든 백업(`.ai-workflow/backup/design/`)도 함께 커밋해야 커밋 후 미추적 파일이 남지 않습니다(남아 있으면 `/product-init` 사전 점검이 미커밋 변경으로 멈춤). 예:
`git add docs/design design-preview .ai-workflow/design.json .ai-workflow/design-notes.md .ai-workflow/backup/design && git commit -m "docs(design): UX 설계와 UI 프리뷰 승인"` (백업 폴더가 없으면 그 경로는 빼기)

## 7단계 — 기획 변경 대응

1. `impact`로 바뀐 기획 ID와 이를 참조하는 UXD·SCR·CMP를 보고합니다. 디자인 승인이 모두 무효가 되었음을 알립니다.
2. 기획이 재승인·커밋되어 있으면, 사용자 확인 후 `rebase --confirm` → UX Planning부터 바뀐 항목 중심으로 재검토합니다(바뀌지 않은 결정은 다시 묻지 않음).

## 워크플로 v2 전환(WF-D05)

- `config.workflow`가 없으면 v1이며 위 절차가 그대로입니다. v2 전환은 **사용자가 요청하고 명시적으로 승인한 경우에만** 합니다("v2 전환 승인" 같은 명시적 표현).
- 순서: `migrate --to v2 [--theme-file <경로>]`로 계획을 보여 줌 → 기존 승인·해시·revision이 그대로라는 점, design_direction은 승인 없이 추가된다는 점, 테마 파일 효과를 설명 → 승인 → `--confirm`.
- **Design Direction(07, v2만)**: UX 설계 승인 뒤 `begin --stage design_direction` → `templates/07-design-direction.md`로 작성 → `trace --stage design_direction` → `done` → `submit` → **"디자인 방향 승인"** → `approve`. 시각 결정(VD)은 사용자에게 하나씩 결정을 받아 '승인'·'제외'로 정합니다(후보·미결정이 남으면 제출 불가). UX 설계를 바꿔야 하는 요청(①·②)은 07에서 결정하지 않고 CR로 남겨 `reopen --stage ux_spec`을 안내합니다. 승인되지 않은 VD는 프리뷰에 쓰지 않습니다.
- **테마(v2, `design-theme/v1`)**: 렌더링 값은 테마 파일, 토큰 이름·의미는 04입니다. 04 문서를 고쳐 값을 맞추지 않습니다. 테마를 바꾸면 `theme-check`로 확인하고, 프리뷰 `tokens.css`는 `theme-check --print-css`의 기대 CSS로 맞춥니다. 테마에 새 토큰 이름이 필요하면 ②로 UX Spec 개정을 안내합니다. 테마 경로 변경은 사용자 확인 후 `migrate --replace-theme-file`.
- **렌더러(07의 code·figma·both)**: 엔진은 Figma를 호출하지 않습니다. Figma를 쓸 수 없으면 사용자 확인 후 06의 '사용 렌더러'를 code로 바꾸고 사유를 적어 Code-first로 진행합니다. 어느 경로든 최종 승인은 프리뷰입니다.
- **design_direction 게이트**: 이미 v2인 프로젝트는 꺼져 있고(선택 단계), 프리뷰 진행·승인에 영향이 없습니다. 켜기는 사용자 동의 후 `migrate --to v2 --enable-gate design_direction`(계획) → `--confirm`. 켜면 다음 프리뷰 시작·제출·승인부터 Design Direction 승인이 필요하고, 이미 승인된 프리뷰는 그대로 유지된다는 점을 먼저 설명합니다.
- v2 `check`에서 `theme_changed`(테마 값만 바뀜)가 나오면 UX Spec 승인은 유지된다고 설명하고, 확인을 받아 `reopen --stage preview` → `preview-verify` → 재승인합니다.
- `check`의 문제에 `requires_user_decision: true`가 있으면 분류를 사용자에게 보여 주고 판단을 받습니다. 분류만으로 `reopen`하거나 승인하지 않습니다.
- 자세한 규칙: `reference/design-state.md`의 "워크플로 v2", `reference/change-impact.md` §5.

