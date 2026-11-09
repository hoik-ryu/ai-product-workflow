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

