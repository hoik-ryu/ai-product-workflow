# 테스트 시나리오 — /product-design

## 실행 방법

- **스크립트 테스트(자체 완결형)**: `python3 tests/product_design_test.py`
  - 임시 Git 저장소에 테스트용 승인 기획(state.yaml + 01–05)을 만들고, LLM이 쓸 디자인 문서를 테스트 코드가 대신 작성해 스크립트 판정을 검사합니다.
  - state.yaml과 기획 문서는 **테스트 픽스처**이며 실제 `/product-start` 승인 흐름이 아닙니다. 기획 변경(T9 → 재승인)도 픽스처로 재현합니다.
  - 프리뷰 빌드(P17a)는 pnpm과 네트워크가 있을 때만 실행하고, 없으면 SKIP으로 표시합니다.
- **Skill 테스트**: 제품 저장소를 scratch에 로컬 클론하고 `.claude/skills/`에 세 Skill을 링크한 뒤, `claude -p "/product-design" --add-dir <engine>/skills`로 대화를 이어 갑니다(`--resume`). 사용자 답변은 테스트 작성자가 결과를 보고 한 단계씩 입력합니다.

## 스크립트 테스트(`tests/product_design_test.py`)

| ID | 영역 | 시나리오 | 기대 결과 |
|---|---|---|---|
| P01–P05a | 게이트 | state.yaml 없음 / planning 미승인 / 승인 후 기획 수정 / 엔진 저장소 / 미커밋 변경 / 기존 docs/design | 각각 차단, design.json 미생성, 기존 파일 보존 |
| P06 | 시작 | 정상 시작 | `based_on`(해시 5개·커밋), ux_planning `in_progress`, 하위 `locked`, `display_note` |
| P07 | 순서 | UX Planning 확정 전 UX 설계 시작 / 제출 없이 승인 | 거부 |
| P08 | UX Planning | front matter revision 불일치 / 기획에 없는 ID / 주석 속 예시 / 제출 | 거부 / 거부 / 무시 / r1 + 미결 DQ·PF 경고 |
| P09 | 승인 | 제시 후 변경 / 다른 revision / 정상 승인 | `changed_since_submit`·`submitted_modified` / 거부 / ux_spec `not_started` |
| P10 | 재개 | 01만 작성 후 check | 다음 행동(구조 확인) 안내 |
| P11 | 구조 | 라우트 표 불일치 / Must US 화면 없음 / 플랫폼 값 / 통과 / 구조 확인 없이 제출 | 각 오류, 코드 블록·주석 속 헤딩 무시, `structure_not_confirmed` |
| P12 | 추적성 | 상태 6종 누락, 미정의 CMP, FLOW 대안 단계 누락, AC 행 누락, 비UI 사유 없음, Should US 누락, 없는 상태 참조 | 각 오류 감지 / 통과 시 비UI 집계 |
| P13 | 승인 | UX 설계 제출·승인 | preview `not_started` |
| P14 | 해시 | 승인된 02 외부 변경 | `approved_modified`, 해시 재기록 없음, 복원 후 일치 |
| P15, P24 | 백업 | Git clean 파일 / 미커밋 변경 파일 | 백업 없음 / 단일 슬롯 백업 |
| P16 | 프리뷰 경계 | 템플릿 복사, 재복사, 화면 누락, fetch, frontend import(양방향), manifest revision 불일치, 문서에 없는 상태 | 각 감지 |
| P17 | 프리뷰 빌드·승인 | 빌드 없이 제출 / preview-verify / 제출·승인 | 거부 / pnpm install + build 통과 / 전체 approved |
| P18 | 프리뷰 해시 | 승인 후 프리뷰 수정 / 복원 / status | `approved_modified` / 일치(node_modules·dist 제외) / state.yaml 표시 설명 |
| P19 | 무효화 | UX 설계 reopen / 화면 구성이 바뀐 재제출 / 같은 구성 재제출 / 이전 revision manifest | 프리뷰 승인 무효(`locked`) / 구조 확인 다시 필요 / 구조 확인 이어받음 / 불일치 감지 |
| P20 | 참조 | `refs --id UXD-002` | 참조 화면 반환 |
| P21 | 무결성 | 전체 흐름 동안 state.yaml·planning | 불변 |
| P22–P23e | 기획 변경 | T9(design locked) / 재승인 후 / outdated 중 진행 / impact / rebase | 차단·문서 보존 / `design_outdated` / 차단 / 바뀐 US와 참조 SCR·UXD / 확인 후 UX Planning 재검토·하위 잠금 |

### 리뷰 결함 수정 회귀(2026-11-06 추가)

| ID | 결함 | 시나리오 | 기대 결과 |
|---|---|---|---|
| H1–H1b | 상위 단계 무결성 | UX Planning 승인 후 00 변경 → UX 설계 `begin`/`done`/`checkpoint`/`submit`/`approve` (check 실행 없이) | 모두 `upstream_modified` |
| H1c–H1e | 상위 단계 무결성 | UX 설계 승인 후 02 변경 → 프리뷰 `begin`/`preview-verify`/`done`/`submit`/`approve` | 모두 `upstream_modified`, 프리뷰 상태 불변 |
| H1f | 같은 단계 변경 | UX Planning 승인 후 00 변경 → `reopen --stage ux_planning` | 허용(재검토로 해결) |
| M1–M1e | 미응답 질문 영속화 | 라운드 저장 전/후 `pending`, `check`의 `pending_round`(재개 시 동일 원문), 형식 오류 4종(권장안 누락, 라운드와 다른 ID, 기획에 없는 관련 ID, 대기 라운드 2개), 대기 중 제출, 답변 완료 후 | 없음 / 저장 내용 반환 / 같은 원문 + "그대로" 안내 / 각 오류 / `pending_questions` 거부 / 대기 없음 |
| M2, M2a | 확정 사항 C-xx | UXD가 C-02(유효)·C-99(없음) 참조 / PRD의 C-02 문구 변경 후 impact | C-99만 오류 / `changed`에 C-02(C-01 제외), UXD-002 영향 |
| M3–M3d | 프리뷰 격리 | strictPort, 별칭 import, 동적 import(frontend/비문자열), `import.meta.glob`, `require`, vite alias, `server.fs.allow`, tsconfig `paths`·`extends`, 주석·URL 문자열, 제품 설정의 프리뷰 참조 | 각 우회 감지, 주석·문자열 오탐 없음, 제품 쪽 주석 언급 무시 |
| L2–L6 | Low 개선 | 인자 오류·예상 못한 예외 / check·start 기존 파일 판정 / done 시 기획 변경 / backup 경로(`..`, 절대 경로, 정규화 후 이탈, 심볼릭 링크, `./`) / 구조 확인 기록 필드 | JSON 오류 응답 / 같은 판정 / `planning_not_approved` / `invalid_path`·정규화 / 서명만 기록 |

## Skill 테스트(badminton-playbook 승인 기획의 scratch 복사본)

원본 저장소는 읽기 전용 로컬 클론으로만 사용했습니다(planning r2, boilerplate v1.0.0 적용 커밋 `99cd9f7`).

| ID | 사용자 입력 | 기대 결과 |
|---|---|---|
| K1 | `/product-design` | 시작, 기능별 주제 6개 우선순위, 1라운드 질문 2–4개(권장안·근거·관련 ID), 확정 사항은 묻지 않음 |
| K2 | 선택 / 선택지 밖 답 / 위임 / 모름 / 범위 밖 요청(회원 직접 참석 등록) | UXD 확정 / UXD 확정 / 권장안 수용 / DQ / **PF로 분리**(PRD 비목표 근거), 후속 질문 생성 |
| K3 | 모호한 답("a랑 b 중간") | 기록하지 않고 구체적 확인 질문 |
| K4 | 새 세션 `/product-design` | 답한 질문을 다시 묻지 않고 대기 중인 확인 질문부터 재개 |
| K5 | 이전 결정 변경 | 기존 UXD 취소선 + 새 UXD, 영향 화면 확인, 백업 |
| K6 | "나머지는 권장안으로" | 남은 주제 권장안 수용 표시, 요약, 제출, "확정" 요청 |
| K7 | "좋아요" | 승인 아님, 상태 불변 |
| K8 | "확정" | UX Planning 승인 → IA·화면 목록 → 구조 검사 → "구조 확인" 요청 |
| K9 | "구조 확인" | 상세 명세 전체, trace 통과, 체크리스트·기획 피드백, "UX 설계 승인" 요청 |
| K10 | "승인" | 프리뷰 생성, preview-verify 통과, 화면·상태별 주소 안내, 피드백 요청 |
| K11 | 시각 피드백 2건 + 동작 변경 피드백 1건 | 시각은 프리뷰에서 수정·재검증, 동작 변경은 **UX 설계 변경으로 분리**하고 영향 설명 후 확인 요청 |
| K12–K14 | 진행 확인 → 구조 확인 → 승인 | UX 설계 reopen(프리뷰 승인 무효) → r2 → 승인 → 프리뷰 r2 기준 갱신 |
| K15–K16 | 제출 요청 → "시각 디자인 승인" | 프리뷰 제출 → 승인 → 전체 approved, 완료 보고 |
| K17 | (사용자 커밋 후) 새 세션 `/product-design` | 완료 상태 보고, `/product-build` 미구현 명시 |
| K18 | 새 세션 `/product-start` | 교차 검증 통과, 디자인 파일을 건드리지 않음 |
| K19 | 승인된 02 외부 수정 후 `/product-design` | `approved_modified` 차단, 자동 재승인·복구 없음, 선택지 제시 |

## 실행 기록

### 2026-11-06

환경: macOS, Python 3.11.9, Node 20.19.5, pnpm 10.34.5, Claude Code(Skill 테스트는 `--model sonnet` headless), Docker 28.0.4 가동.

| 구분 | 결과 |
|---|---|
| 스크립트 테스트 P01–P24 | **73/73 Pass** (P17a 프리뷰 실제 빌드 포함) |
| Skill 테스트 K1–K19 | **19/19 기대 동작**(아래 관찰 사항 참조). 최종 산출물: 화면 16, 컴포넌트 21, UX 결정 20(대체 1), Must US 18/18, Should US 3/3, FLOW 단계 50/50, AC 61/61(비UI 9), 프리뷰 화면 16·상태 109. 기획 문서·state.yaml은 전 과정에서 불변 |
| 프리뷰 육안 확인 | 헤드리스 Chrome으로 6개 화면을 캡처해 렌더링, 상태 탭, 폭 전환, mock 데이터, 피드백 반영(SCR-014 접힘, SCR-009 토스트 제거)을 확인 |
| `/product-start` 회귀 S01–S19 | **19/19 Pass**. 해시 불일치는 의도한 S09·S11·S17에서만 발생. `/product-start` 파일 변경 없음 |
| `/product-init` 회귀 | 스크립트 **49/49**, Skill K1–K10(실제 GitHub v1.0.0, fe/be/db/smoke 모두 pass) **10/10**. 디자인 산출물 커밋 후 `/product-init check` 통과 |

테스트 중 발견해 수정한 결함과 개선:
- `rebase`의 미커밋 검사가 스크립트 자신이 기록한 `design.json`까지 변경으로 보아 항상 거부되었습니다. 기획 파일과 state.yaml만 보도록 고쳤습니다(P23d).
- 템플릿의 HTML 주석·코드 블록 속 예시 헤딩을 실제 ID로 읽을 수 있었습니다. 파서가 주석과 코드 블록을 무시하도록 고쳤습니다(P08b, P11c).
- 재검토 revision마다 구조 확인을 다시 받아야 해서 작은 수정에도 마찰이 컸습니다. 화면 구성(IA 라우트 표 + 화면 ID)이 이전 확인과 같으면 확인을 이어받도록 했습니다(P19b, P19b2).
- 완료 보고의 권장 커밋 명령에 `.ai-workflow/backup/design/`이 빠져 있어, 커밋 후 `/product-init` 사전 점검이 미커밋 변경으로 멈췄습니다. 명령에 백업 경로를 포함했습니다.
- 재개 시 진행 요약을 먼저 보여 주라는 지시를 SKILL.md에서 표 밖으로 꺼내 강조했습니다(K4에서 요약 없이 질문부터 시작).
- 완료 보고에서 아직 없는 `/product-build`를 실행하라고 안내했습니다. 미구현이라고 명시하도록 지시를 고쳤습니다(K17에서 확인).

관찰 사항(결함 아님, 남은 위험):
- K12–K13은 스크립트 개선 전에 기록된 구조 확인(서명 없음) 때문에 구조 확인을 한 번 더 받았습니다. 새로 시작하는 프로젝트에는 해당하지 않습니다.
- LLM이 UXD의 관련 ID를 의미상 부정확하게 적은 사례가 있었습니다(예: UXD-014가 FLOW-002 참조). 스크립트는 존재 여부만 보므로 이런 오류는 검토 체크리스트와 사용자 승인에 의존합니다. K9에서 LLM이 이를 기획 피드백으로 스스로 보고했습니다.
- K10에서 프리뷰에 02 문서에 없는 안내 문구가 들어갔고, K11에서 사용자 피드백으로 드러나 삭제되었습니다. 프리뷰가 명세 밖 요소를 넣었는지는 스크립트가 검사하지 않습니다.
- Skill 테스트는 headless 모드에서 Sonnet으로 실행했고, 사용자 답변은 테스트 작성자가 입력했습니다.

### 2026-11-06 (리뷰 결함 수정: H1, M1–M3, Low 1–6)

| 구분 | 결과 |
|---|---|
| 스크립트 테스트 | **119/119 Pass**(기존 73 + 신규 46). 기존 P08a는 대기 질문이 있으면 제출이 먼저 거부되도록 바뀌어 `trace`로 검사 대상을 바꿨습니다 |
| 실제 기획 C-xx | badminton-playbook PRD의 C-01~C-12 12개 인식. 복사본에서 C-03 문구를 바꾸면 `impact`가 `changed: [C-03]`과 이를 참조하는 05 문서를 반환 |
| 기존 승인 산출물 회귀 | 이전 Skill 테스트로 승인까지 마친 복사본(UXD 20, 화면 16, 프리뷰 16화면·109상태)이 새 규칙(C-xx 검증, 강화된 격리 검사)에서 `check`·`trace`·`preview-check` 모두 통과 |
| H1 실제 데이터 | 승인 복사본에서 00 수정 → `reopen ux_spec`·`reopen preview`는 `upstream_modified`, `reopen ux_planning`은 허용(하위 단계 무효화) |
| M1 Skill 테스트 | 새 복사본에서 `/product-design` → 질문 4개(R01-Q1~Q4)를 제시 **전에** `답변 대기`로 저장. **새 세션** 재개 시 진행 요약 후 같은 질문을 그대로 제시(`design-notes.md` 바이트 불변). 답변 후 라운드 1 `답변 완료`, 라운드 2 `답변 대기` 저장, UXD 4개 기록 |
| `/product-start` 회귀 S01–S19 | **19/19 Pass**. 해시 불일치는 의도한 S09·S11·S17에서만 발생, 한국어 헤딩 검사 통과. `/product-start` 파일 변경 없음 |
| `/product-init` 회귀 | 스크립트 **49/49**, Skill K1–K10 **10/10**(실제 GitHub v1.0.0, fe/be/db/smoke pass) |

수정 내역:
- H1: 상태를 바꾸는 명령(`begin`, `done`, `checkpoint`, `submit`, `approve`, `reopen`, `preview-scaffold`, `preview-verify`)이 공통 게이트에서 대상 단계보다 앞선 단계의 교차 검증을 스스로 수행합니다.
- M1: `design-notes.md` 라운드 형식(상태, `R0N-Q#`, 선택지, 권장안, 관련 ID)과 `pending` 명령. `check`가 대기 라운드를 반환하고, 대기 질문이 있으면 UX Planning 제출을 거부합니다. 템플릿 `templates/design-notes.md` 추가.
- M2: PRD 확정 사항 표의 `C-xx`를 기획 ID로 파싱(관련 ID 검증, ID 블록 비교, 참조 검색).
- M3: 문자열을 보존하는 주석 제거 후 모든 모듈 경로를 해석해 프리뷰 폴더 이탈을 검사하고, 설정 파일(vite, tsconfig, index.html, package.json)과 제품 쪽 참조까지 검사합니다. 별칭 대신 상대 경로를 쓰도록 했습니다.
- Low: `strictPort: true`, 인자 오류·예외의 JSON 응답, check·start 기존 파일 판정 통일, done의 기획 유효성 검증, backup 경로 정규화·이탈 방지, 해시 필드 정리(프리뷰 승인의 `ux_spec_hashes`를 실제로 대조하고, 쓰이지 않던 구조 확인 `hashes` 제거).

## 디자인 변경 영향 분류(WF-D01, `impact --design`) — `tests/product_design_impact_test.py`

픽스처 저장소에서 실제 명령으로 UX Planning·UX 설계·프리뷰를 승인한 뒤 분류합니다. 고정 사례는 `tests/fixtures/design-change-cases.json`(시험 프로젝트 A/B 실험 D1–D15)입니다. 사례의 프로젝트 고유 정책(배치 규칙, 수치 성격, 토큰 밖 여부)은 사실 값으로만 표현하고, `expected`는 테스트만 읽습니다.

| ID | 시나리오 | 기대 결과 |
|---|---|---|
| I01 | `--design` 없는 `impact` | 커밋된 이전 엔진과 출력이 같음. `--request`만 쓰면 JSON 오류 |
| I02–I03b | D1–D15 | 상태·유형·대안·플래그가 사례 기대값과 같음. 자동 9 · 조건부 4 · 사람 판단 1 · 제외 1. 사실마다 근거와 확인한 문서 |
| I04–I08b | 유형별 영향(세 단계 승인 상태) | ①② → ux_spec(구현됨, 재승인 ux_spec+preview). ③ → 목표 `theme` 미구현 표시, 실제 ux_spec(이유 기록). ④ → 목표 `design_direction` 미구현, 실제 preview. ⑤ → 목표 `render` 미구현, 실제 preview. 명세 위반·접근성·토큰 밖 안내 |
| I09–I12b | 복합·분류 불가 | ①+③ 복합(대표 ①, 재승인 합집합) / 판단 필요 사실이 섞이면 항목 전체 needs_review / 알 수 없는 종류·사실 없음·없는 참조·알 수 없는 속성·이미 있는 토큰 추가 → needs_review / 04에 없는 토큰 값 → ② / 묶음 행 토큰 / 위치 고정 → ①, 최솟값 이상 → ④ |
| I13 | 요청 형식 오류 | `invalid_request` |
| I14–I16 | 파일 차이(기준 HEAD) | 변경 없음 0건 / 04 토큰 값 → ③, 이름 추가 → ②, 묶음 행 값 → ③, 컴포넌트 정의 → needs_review(바뀐 CMP 근거) / 02 → ①(바뀐 SCR 근거) / 00 → ①, 영향 ux_planning부터 / 기획 문서 → 제외 / 무관한 파일 → `unrelated_paths` / 프리뷰 tokens.css 값 → ③, 변수 추가 → ② / 프리뷰 CSS → ④ / 코드 주석만 → ⑤, 코드 변경 → needs_review / package.json → ⑤ / 잘못된 기준 → `invalid_base` |
| I17–I17b | 읽기 전용 | 모든 호출 후 design.json·state.yaml·승인 문서 해시와 작업 트리 불변, check 일치 |
| I18–I18a | 상태별 영향 | UX 설계 제출 상태의 ① → 수정 요청으로 처리(재제출 ux_spec만) / 프리뷰 잠김 상태의 ④ → 재승인 없음 |

### 2026-11-10 (WF-D01)

환경: macOS, Python 3.11.9, Node 20.19.5, pnpm 10.34.5. **Docker 데몬 꺼짐**.

| 구분 | 결과 |
|---|---|
| 기준(구현 전) | `/product-design` 119/119, `/product-init` 48/48(Docker 꺼짐: Docker 가동 시에만 실행되는 I12d·I12f 대신 미가동 I12d) |
| `/product-design` 기존 테스트 | **119/119 Pass**(변경 없음) |
| 영향 분류 테스트 | **62/62 Pass**(프리뷰 실제 빌드·승인 포함) |
| 실제 문서(badminton-playbook 읽기 전용 클론) | D1–D15가 실제 승인 문서 ID·토큰 이름과 대조되어 9 · 4 · 1 · 1로 분류. 04 토큰 표에 이름 추가·값 변경을 넣으면 파일 모드가 ②·③으로 분리하고 ③은 `theme` 미구현 → 실제 `ux_spec`으로 보고. 클론의 상태·문서 해시 불변 |
| `/product-init` | 스크립트 **48/48 Pass**(파일 변경 없음). Skill 테스트(K1–K10)는 이번에 다시 실행하지 않았습니다(이전 scratchpad 하네스가 지워졌고 Docker가 꺼져 있음) |
| `/product-start` 회귀 S01–S19 | **19/19 Pass**(지워진 하네스를 대화 기록의 생성 명령으로 복원해 실행). 해시 불일치는 의도한 S09·S11·S17에서만 발생. S17b에서는 LLM이 T9 적용 전에 변경 계획 확인을 먼저 요청해, 그 시점 planning이 아직 approved였음(파일 안전 규칙상 더 보수적인 순서). S17c에서 r2 제출·백업 일치, S18 재승인 정상 |

수정 내역:
- 실제 문서 확인에서 고정 사례의 컴포넌트 ID 4개(실험 보고서에 ID가 없던 사례)를 임시 값으로 넣었다가 실제 04의 ID(CMP-001·004·006·024)로 바로잡았습니다. 임시 ID일 때는 엔진이 "승인 문서에 없는 참조"로 needs_review 처리했습니다(의도한 안전장치).
- 근거 ID를 바뀐 줄뿐 아니라 바뀐 줄이 속한 헤딩 블록(SCR·CMP·UXD)에서도 모으도록 고쳤습니다(`- **용도**: …`처럼 ID가 없는 줄의 변경).

## 워크플로 v2 상태·전환·무효화(WF-D05) — `tests/product_design_v2_test.py`

| ID | 시나리오 | 기대 결과 |
|---|---|---|
| V0–V0b | v1 불변 | 같은 v1 명령 29개(승인·거부·무효화·재검토·백업·프리뷰 시작)를 커밋된 엔진(HEAD)과 현재 엔진으로 실행 → 종료 코드·출력·최종 design.json 동일(시각·커밋·경로만 정규화). v1 상태에 config·design_direction·theme 없음 |
| V1–V3b | 전환 | 확인 없이 → 계획만(파일 불변) / `--confirm` → config·design_direction(not_started, 승인 없음)·theme 기준 추가, 기존 승인·revision·해시·history 불변, Git clean이면 백업 생략 / 재실행 → `already_v2`(바이트 동일) / 다른 테마 파일로 재설정 거부 |
| V4 | 부분 실패 | 쓰기 뒤 실패(`--simulate-failure`) → 원래 파일로 복원(바이트 동일), `migrate_failed` |
| V5–V5c | 잘못된 상태 | 잘못된 workflow 값 → `invalid_state` / v2 필드 누락 → `invalid_state` + 복구 안내 / `migrate --confirm`이 누락 필드만 복구(처음 전환 기록 유지, `migration_repaired`) |
| V6–V6c | 미구현 단계 | design_direction begin·submit·approve·reopen·done → `stage_not_implemented`, 07 문서는 경고만 / v1에서는 `stage_not_in_workflow` |
| V7–V7a | 승격 금지 | 수동으로 approved가 된 design_direction → 문제로 보고(승인 불인정), 전환·복구도 거부 |
| V8–V8d | ③ 테마 값 | v1: 테마 파일은 승인 대상 아님 / v2: 테마만 변경 → preview만 `theme_changed`, ux_spec 문제 없음 → preview reopen → 검증 → 재승인, ux_planning·ux_spec 승인 기록 처음 그대로 |
| V9–V9c | ⑤ 구현 메모·사용자 판단 | v1: 주석만 바꿔도 approved_modified(기존) / v2: 주석만 → 문제 없음(경고) / v2 코드 변경 → approved_modified + 분류 needs_review + `requires_user_decision`, 상태 자동 변경 없음 |
| V10–V10b | 무효화 연쇄 | v2 ux_spec reopen → design_direction·preview 잠금 / 재승인 → 둘 다 잠금 해제(design_direction은 상태만) / preview 시작 시 미구현 의존성 표시 |
| V11–V12 | v2 영향 분류 | ③(테마 파일 있음) → preview만, ux_spec·design_direction 보존 / ④ → 목표 design_direction 미구현 표시, 실제 preview / ⑤ → 재승인 없음 / conditional → 사용자 판단 / 분류·check 후 승인 기록 불변 |
| V13–V13b | v2 검증 기록 | preview-verify가 의미·테마 해시 기록 / 검증 뒤 주석만 바뀌면 제출 가능 / 제출 뒤 테마 변경 → 승인 거부(`theme_changed`) |
| V14–V16 | 사전 점검·경계 | 승인 산출물이 바뀐 상태는 전환 거부 / 테마 경로(절대·상위·승인 산출물·기획·없는 파일)와 지원하지 않는 버전 거부 / v2라도 04의 토큰 값 변경은 ux_spec approved_modified |

### 2026-11-10 (WF-D05)

| 구분 | 결과 |
|---|---|
| `/product-design` 기존 테스트 | **120/120 Pass**(L2a를 둘로 나눔: 구조가 깨진 상태 파일은 이제 `invalid_state`로 먼저 보고되고, 내부 값 오류는 여전히 `internal_error`) |
| 영향 분류(WF-D01) | **62/62 Pass** |
| v2(WF-D05) | **56/56 Pass**(프리뷰 실제 빌드·승인 포함) |
| `/product-init` | 스크립트 **48/48 Pass**(Docker 꺼짐, 파일 변경 없음) |
| `/product-start` 회귀 S01–S19 | **19/19 Pass**. 해시 불일치는 의도한 S09·S11·S17에서만 발생, 한국어 헤딩 검사 통과 |
| 실제 문서(badminton-playbook 읽기 전용 클론) | 계획 → 전환 → 재실행 `already_v2` → check 일치. 기존 단계 필드·history 전부 동일, design_direction not_started(승인 없음). 테마 파일이 없어 D4(③)는 v1과 같이 ux_spec으로 보고 |

수정 내역(테스트 중 발견):
- `check`가 상태 구조 검증을 거치지 않아 v2 필드가 빠진 상태에서 `internal_error`가 났습니다. `invalid_state`와 복구 안내를 내도록 고쳤습니다.
- 중간에 멈춘 전환을 복구할 때 처음 전환 기록(`migration`)을 덮어써, 사후 검증이 이를 잡고 복원했습니다. 기존 기록은 그대로 두고 history에 `migration_repaired`만 남기도록 고쳤습니다.

## Design Direction·게이트·의미 해시(WF-D02) — `tests/product_design_dd_test.py`

| ID | 시나리오 | 기대 결과 |
|---|---|---|
| S1–S9 | 의미 해시 sem-2 형식별 | .ts 주석·빈 줄·들여쓰기 무시(토큰 사이 공백 변경은 감지) / 템플릿 리터럴·줄 이음·주석 뒤 코드 → 원본 / .tsx(JSX 글자 `//`, 인라인 요소 사이 공백) → 원본 / .css 주석·공백 무시, 문자열 안 공백 감지, `a/**/b`·`ab`·`a b` 구분, 따옴표 없는 url → 원본 / 참조 안 된 .md 제외 / json·html·svg 원본 |
| D01–D03 | 시작 | v1 → `stage_not_in_workflow` / UX 설계 미승인 → 거부 / 승인 후 시작(기준 revision 기록) |
| D04–D05 | 07 검증 | 섹션 누락, 기준 revision 불일치, 후보·미결정 VD, 제외 VD를 렌더에 사용, 없는 화면·상태, 렌더 범위 없음, 04에 없는 토큰(②), 없는 컴포넌트, 잘못된 렌더러, 정책 값 누락, 남은 ①·② CR, 미결 needs_review CR → 각각 오류 / 올바른 문서 통과(기각한 ①, 반영한 ④ 허용) |
| D06–D08c | 제출·승인 | revision 불일치 done 거부 / **후보 VD가 있으면 제출 거부** / 제출 뒤 변경 → 승인 거부 / 다른 revision 거부 / 승인 기록(07·UX 설계 기준 해시, 승인 VD, 렌더러, 테마) |
| D09–D09a | 해시 보호 | 승인된 07 변경 → approved_modified, 재기록 없음 / 게이트 꺼짐이면 프리뷰 진행을 막지 않음 |
| D11–D12 | 상위 변경 | 승인된 UX 설계 변경 → design_direction 명령 차단 / ux_spec reopen → design_direction(last_approved 보존)·preview 무효 / 재승인 후 잠금 해제, 07은 새 기준 revision을 적어야 함 |
| G1–G12 | 게이트 | 기존 v2(프리뷰 승인) 게이트 꺼짐 유지 / 꺼짐에서 DD 승인·reopen이 프리뷰에 영향 없음 / 활성화 계획(파일 불변) / 활성화(기존 승인·해시 불변, gate_enabled) / 재실행 멱등 / 활성화 직후 기존 프리뷰 승인 유지(게이트 이전 승인 표시) / **DD 미승인 시 프리뷰 제출 차단** / 진행 중 프리뷰는 DD 승인으로 무효화되지 않음 / manifest의 DD revision·승인되지 않은 VD 사용 검사 / DD 승인 후 프리뷰 제출·승인(DD revision 기록) / 켜짐에서 DD reopen → 프리뷰 무효 / DD 미승인 시 프리뷰 시작 거부 |
| S10 | 이전 기록 | 알고리즘 표시 없는 의미 해시 기록은 쓰지 않고 원본 비교, 기록 교체 없음 |

### 2026-11-10 (WF-D02)

| 구분 | 결과 |
|---|---|
| `/product-design` 기존 | **120/120 Pass** |
| WF-D01 | **62/62 Pass** |
| WF-D05 | **56/56 Pass**. M1-3 요구로 기대값을 바꾼 항목: V2d(미구현 없음·게이트 표시), V6·V6a(design_direction 시작 가능, 제출 없는 승인 거부; 이전 거부 확인 6개를 2개로), V7(`missing_record`), V7a(v2 조작 상태는 변경 없음 + check 문제 유지), V11b(④ → design_direction + 프리뷰), 의미 해시 보수화로 V9a·V11·V13a를 `.ts` 사례로 옮기고 `.tsx` 확인(V9a2·V11e·V13a0) 추가, v1 상태 끼어든 DD 거부(V7b) 추가 |
| WF-D02(신규) | **61/61 Pass**(프리뷰 실제 빌드·승인 포함) |
| `/product-init` | 스크립트 **48/48 Pass**(Docker 꺼짐) |
| `/product-start` 회귀 S01–S19 | **19/19 Pass**(S17b는 T9 적용 전 확인 요청 순서, S17c·S18 정상) |
| 실제 문서(badminton-playbook 읽기 전용 클론) | v2 전환 → Design Direction 시작 → 실제 SCR-211 상태·04 토큰으로 07 검증 통과 → check 일치(게이트 꺼짐). 원본 불변 |

수정 내역(테스트 중 발견):
- 마이그레이션의 "진행·승인된 design_direction 거부" 규칙이 정상 v2 프로젝트의 게이트 활성화까지 막았습니다. v1 상태에 끼어든 기록에만 적용하도록 고쳤습니다.

## 테마 계약·렌더러 경로(WF-D03·D04) — `tests/product_design_theme_test.py`

빠른 검증(기본)은 pnpm 빌드 없이 실행합니다(픽스처에서 엔진 템플릿 복사만). `PD_FULL=1`이면 프리뷰 빌드·승인(F1–F3)까지 실행합니다.

| ID | 시나리오 | 기대 결과 |
|---|---|---|
| T0–T1 | 적용 대상 | v1 → 적용 대상 아님 / 이전 형식 테마(M1-2) → 계약 미적용 경고만(해시 추적) |
| P1–P5 | 경로 변경 | 그냥 바꾸면 `theme_file_conflict` / 새 파일이 계약 위반이면 거부 / 계획(파일 불변) / 확인 후 변경(theme_history·history, 기존 승인 불변) / 재실행 멱등 |
| C1–C2 | 계약 검사 | 04와 다른 값(출처·적용 기준), 묶음 행 토큰, 테마에 없는 04 토큰은 04 값, 기대 CSS, 프리뷰 없으면 일치 검사 생략 / 새 이름(②)·없는 원시 참조·색 형식·길이 형식·css 경로·변수 규칙 오류 |
| A1–A5 | 승인 영향 | 테마 값만 변경 → UX Spec 승인 보존 / 파일 분류: 값 → ③(preview, ux_spec·design_direction 보존), 이름 추가 → ②, 형식만 → ⑤(재승인 없음) / 04 문서 불변 |
| R0–R8, S1–S3 | 렌더러·tokens.css | figma: 링크 없으면 오류, 있으면 통과 / Figma 한도 → code 전환(사유)으로 정상 진행 / 사유 없는 전환·비-code 전환 오류 / both: 비교 표·figma 링크 필요, code 선택+근거 통과 / code: 06 기록 없어도 통과 / tokens.css 일치·불일치·누락 / 04·07 불변 |
| F1–F3 | 완료 검증 | Code-first 프리뷰 승인 기록(렌더러 계획·사용, 테마 해시, DD revision) / 승인 뒤 테마 값 변경 → preview만 theme_changed / 04·07 해시 불변 |

### 2026-11-10 (WF-D03·D04, M1 완료 검증)

| 단계 | 구분 | 결과 |
|---|---|---|
| 빠른 검증 | WF-D03·D04 | **38/38 Pass**(F1–F3은 이 단계에서 건너뜀) |
| 빠른 검증 | WF-D01 / WF-D05 / WF-D02 | **62/62**, **56/56**, **61/61 Pass** |
| M1 완료 | `/product-design` 전체 | 기존 **120/120**, WF-D01 **62/62**, WF-D05 **56/56**(v1 호환: 커밋된 엔진과 명령 29개 비교 포함), WF-D02 **61/61**, WF-D03·D04 **40/40**(`PD_FULL=1`, 프리뷰 빌드·승인 포함) |
| M1 완료 | `/product-start` 회귀 S01–S19 | **19/19 Pass** |
| M1 완료 | `/product-init` | 스크립트 **48/48 Pass**(Docker 꺼짐, Skill K1–K10은 하네스 부재로 미실행) |
| M1 완료 | 실제 프로젝트(badminton-playbook 읽기 전용 클론) Code-first | 계약 테마로 v2 전환 → theme-check(04와 다른 값을 출처와 함께 보고) → Design Direction(code) 승인 → 게이트 활성화 → 프리뷰 시작 가능 → 테마 값 변경 시 check 일치·분류 ③(preview, UX Spec·DD 보존). 승인된 00–05·기획·state.yaml 해시와 ux_planning·ux_spec 승인 기록 불변. 실제 프리뷰는 만들지 않음 |

수정 내역(테스트 중 발견):
- 06의 '전환 사유: 없음'이 문자열로 승인 기록에 남았습니다. 전환이 없으면 `null`로 기록하도록 고쳤습니다.
- 04 묶음 행(`13 / 16 / … / 32px`)에서 마지막 값에만 붙은 단위를 앞 값에 적용하지 않아, 실제 문서에서 `font.size.body`가 `16`으로 읽혀 테마 `16px`와 다르다고 잘못 보고했습니다. 단위를 앞 값에도 붙여 해석하도록 고쳤습니다.
- 게이트만 켠 경우에도 결과 상태가 `migrated`로 나와 `updated`로 바꿨습니다.


## M1 안정화(모듈 분리·하네스 보존)

### 2026-11-10 (M1 안정화, 진행 중)

| 구분 | 결과 |
|---|---|
| 모듈 분리 | `product_design.py`(CLI) / `pd_core.py` / `pd_theme.py` / `pd_impact.py`. 최상위 정의 196개 전후 동일·원문 동일, 분리 전후 명령 54개 출력·종료 코드·최종 `design.json` 일치, `-I` 실행·심볼릭 링크 설치 정상 |
| `/product-design` 전체 | 기존 **120/120**, WF-D01 **62/62**, WF-D05 **56/56**(v1 명령 29개 비교, v2 마이그레이션·승인 해시 보호 포함), WF-D02 **61/61**, WF-D03·D04 **40/40**(`PD_FULL=1`) |
| `/product-init` | 스크립트 **48/48 Pass**(Docker 꺼짐). Skill K1–K10 하네스는 `tests/harness/product_init/`로 보존했지만 **미실행** |
| `/product-start` 회귀 S01–S19 | 하네스를 `tests/harness/product_start/`로 보존. reg11은 퇴근 전 PHASE C에서 직접 중단. 완료분 S01–S06·S08·S10 Pass, S15는 PHASE B 산출물만 확인. S07·S09·S11–S14·S16–S19 **미완료** |

정정(2026-11-10 WF-D03·D04 M1 완료 검증 표의 `/product-start` 19/19):
- 자동 판정기(`summarize.py`)로 다시 판정한 결과는 **18/19, S07 미검증**입니다.
- 원인은 하네스 픽스처 결함입니다. S07 픽스처가 `artifacts_done: []` 줄 끝 주석을 경로 뒤에 남겨 YAML이 깨졌고, 모델은 손상을 감지하고 멈췄습니다. 엔진 결함은 아닙니다.
- `run_all.sh` PHASE C의 정규식을 고쳤습니다. 수정한 픽스처로 S07을 통과한 실행은 아직 없습니다.
- 같은 판정기로 이전 로그 reg7·reg8·reg9는 19/19였습니다.
- 인수인계: `docs/roadmap/m1-stabilization-handoff.md`

### 2026-11-11 (M1 안정화, `/product-start` 전체 회귀 reg12)

claude 2.1.322, `--model sonnet`, 수정한 하네스(`tests/harness/product_start/run_regression.sh`)로 1회 실행. 로그: 저장소 밖 `ai-product-workflow-test-logs/reg12/`.

| 구분 | 결과 |
|---|---|
| `/product-start` 회귀 S01–S19 | **19/19 Pass**(`summarize.py`), 공통 검사(모든 실행의 기존 파일 해시 불변) OK |
| S07 재검증 | **Pass**. 픽스처 YAML 정상(`s07 fixture replaced 1`), 모델이 03–05를 재개 생성 → planning `awaiting_approval` r1, 02-prd 해시 보존(`02-prd.md: OK`), 01 해시 MATCH, 5개 문서 revision 1·한국어 검사 OK, 추적성 누락 0 |
| 해시 불일치 | 의도한 S09·S11(01)·S17(03)에서만 발생 |
| S14 / S16 | 백업은 01만(S14) / 수정 전 dirty 내용과 백업 일치(S16) |
| S19 | 대화형 실행에서 discovery `in_progress` r0, 허용 목록·센티널 OK |

- 2026-11-10 reg10의 **18/19(S07 미검증)** 기록은 그대로 둡니다. 이번 결과는 픽스처 수정 후의 별도 실행입니다.
- 엔진·Skill 파일 변경 없음(`skills/product-start`, `skills/product-init` diff 없음).
