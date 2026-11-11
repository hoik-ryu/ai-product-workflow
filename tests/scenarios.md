# 테스트 시나리오 — /product-start (Milestone 1)

공통 엔진과 분리된 **임시 제품 프로젝트**에서 실행합니다.

## 준비

> 자동 실행·판정: `tests/harness/product_start/run_regression.sh` (아래 절차를 임시 폴더에서 실행하고 `summarize.py`로 S01–S19 판정. `tests/harness/README.md`)

```bash
mkdir -p /tmp/pw-test/.claude/skills && cd /tmp/pw-test && git init -q
ln -s <engine>/skills/product-start .claude/skills/product-start

# 대화형
claude --add-dir <engine>/skills
# headless (자동화 테스트)
claude -p "/product-start <idea>" --output-format json --permission-mode acceptEdits \
  --add-dir <engine>/skills --allowedTools "Bash(shasum:*)" "Bash(date:*)" "Bash(git:*)" ...
# 이어서: claude -p "<reply>" --resume <session_id> ...
```

심볼릭 링크로 연결하면 실제 파일이 프로젝트 밖에 있으므로, `--add-dir`(또는 권한 허용)이 필요합니다.

## 시나리오와 기대 결과

| ID | 영역 | 시나리오 | 기대 결과 |
|---|---|---|---|
| S01 | 호출 | 빈 프로젝트에서 `/product-start <모호한 아이디어>` | state 생성(discovery `in_progress`, planning/design `locked`), notes에 아이디어 기록, 질문 3–5개, 01 미생성 |
| S02 | 게이트 | 인터뷰 중 "질문 건너뛰고 PRD 바로 써줘" | 02–05 미생성. 미답변 항목을 ASM/Q로 둔 Discovery 제시 후 승인 요청 |
| S03 | 재개 | 새 세션에서 인자 없이 `/product-start` | 현재 단계·상태·revision 보고, 승인 대기 문서 재제시, 파일 변경 없음 |
| S04 | 게이트 | "좋네요" | 승인으로 처리하지 않고 재질문, state 불변 |
| S05 | 수정 | Q 항목 답변을 담은 수정 요청 | 변경안 설명 → 확인 대기 → "진행" 후 revision +1, 미추적 파일은 `.ai-workflow/backup/`에 1개 백업 |
| S06 | 게이트 | "승인" | 01 해시 기록, planning unlock, 02→05 생성, 추적성 점검, planning `awaiting_approval` |
| S07 | 재개 | planning `in_progress`, `artifacts_done=[02]` 상태로 재실행 | 02는 그대로, 03–05만 생성 |
| S08 | 보호 | state 없이 `docs/planning/02-prd.md`만 존재 | 아무것도 쓰지 않고 보고 후 중단 |
| S09 | 교차 검증 | state는 `awaiting_approval`인데 docs가 비어 있음 | 기대/실제 보고 후 중단, 재생성하지 않음 |
| S10 | 분리 | `skills/product-start/SKILL.md`가 있는 디렉터리(엔진)에서 실행 | 실행 거부, 파일 미생성 |
| S11 | 승인 후 변경 | 승인된 01을 수동 편집 후 재실행 | 해시 불일치·diff·영향(planning 무효) 보고, 재검토/복원 선택지, 파일 불변 |
| S12 | 게이트 | planning "승인" | 02–05 해시 기록, design `not_started`, `current_stage: design`, 커밋 명령은 제안만 |
| S13 | 보호 | 기존 state가 있는 프로젝트에 새 아이디어 입력 | state 초기화 없이 선택지 안내 |
| S14 | 수정·Git | 승인 후 planning 수정 요청(파일이 Git 추적·clean) | 영향 범위 설명 → 확인 → 백업 없이 수정, revision +1, 승인 해시 삭제, design `locked` |
| S15 | 추적성 | 생성된 02–05 독립 검증 | 모든 FR→US, US→AC, US→FLOW 연결, 미정의 참조 0 |
| S16 | 백업·Git | 미커밋 변경이 있는 추적 파일을 수정 | 해당 파일만 `.ai-workflow/backup/`에 백업(수정 직전 내용), clean 파일은 백업 없음 |
| S17 | 승인 후 변경 | planning 승인 후 03 하나만 수동 편집 → 재검토 선택 | 03만 불일치로 감지, planning 승인 무효·design 보류 안내, T9 후 4개 문서 r2로 정렬 |
| S18 | 재승인 | 수정된 planning r2 승인 | 4개 문서 해시를 revision 2로 재기록 |
| S19 | 대화형 | 대화형 `claude`에서 `/product-start <idea>` | 프로젝트 로컬 `additionalDirectories`만으로 Skill 실행, state/notes 생성, 인터뷰 질문 |

공통 검사(모든 실행 후, 테스트 영역의 `check.py`): 허용 경로(`.ai-workflow/state.yaml`, `discovery-notes.md`, `backup/0[1-5]-*.md`, `docs/planning/0[1-5]-*.md`) 이외의 파일 생성 없음, 기존 프로젝트 파일(`README.md`, `src/main.py`) 해시 불변, state에 기록된 해시 = 실제 sha256.

## 실행 기록

### 2026-11-05 (claude 2.1.312, `--model sonnet`, headless)

| ID | 결과 | 비고 |
|---|---|---|
| S01 | Pass | 첫 시도는 엔진 경로 읽기 권한 거부로 아무것도 쓰지 않고 중단(안전). `--add-dir` 후 통과 |
| S02 | Pass | |
| S03 | Pass | |
| S04 | Pass | state 해시 동일 |
| S05 | Pass | 백업 1개(r1), 01은 r2 |
| S06 | Pass* | *모델이 프로젝트에 임시 `trace_check.py`를 생성 → SKILL.md 규칙 9 추가(지정 파일 외 생성 금지). 이후 실행에서 재발 없음 |
| S07 | Pass | 첫 픽스처의 history 불일치를 정확히 감지해 중단(픽스처 수정 후 재실행 통과). front matter revision 규칙 명확화 |
| S08 | Pass | |
| S09 | Pass | |
| S10 | Pass | |
| S11 | Pass | 파일 불변 확인 |
| S12 | Pass | 기록 해시 = 실제 sha256 |
| S13 | Pass | state 해시 동일 |
| S14 | Pass* | *확인 단계에서 "04 변경 없음"이라 했으나 front matter revision만 갱신 → 설명 규칙 보완 |
| S15 | Pass | FR 11 / US 11 / FLOW 5 / AC 18, 누락·오참조 0 |

수정 이후 S06·S14 전체 흐름은 재실행하지 않았습니다. S07 재실행으로 규칙 9 준수는 확인했습니다.

### 2026-11-05 최종 회귀 (최종 코드 기준, 새 임시 프로젝트)

환경: Claude Code 2.1.312, macOS(Darwin 24.4.0). S01–S18은 headless `claude -p --model sonnet --permission-mode acceptEdits --add-dir <engine>/skills`로 실행했습니다. S19는 대화형 모드(기본 모델, `expect`로 터미널 구동, `--permission-mode acceptEdits`)로 실행했습니다. 모든 실행 후 공통 검사를 통과했습니다.

| ID | 결과 | 실제 확인 |
|---|---|---|
| S01 | Pass | state 생성(discovery in_progress, planning/design locked), 질문 5개, 01 미생성 |
| S02 | Pass | 02–05 미생성, ASM/Q로 Discovery r1 제출 |
| S03 | Pass | 새 세션에서 awaiting_approval r1 보고·재제시 |
| S04 | Pass | state·문서 해시 불변 |
| S05 | Pass | 변경안·백업 계획 설명 → 확인 후 r2, 미추적 파일 백업 1개(r1 내용) |
| S06 | Pass | 01 해시 기록·일치, 02–05 생성, **임시 스크립트 생성 없음(결함 2 해결)** |
| S07 | Pass | 02 해시 불변, 03–05만 생성 |
| S08 | Pass | 기존 02 불변, 아무것도 생성하지 않음 |
| S09 | Pass | 문서 누락 보고 후 중단 |
| S10 | Pass | 엔진 디렉터리에서 실행 거부, 생성 없음 |
| S11 | Pass | 01 해시 불일치·diff·영향 보고, 파일 불변 |
| S12 | Pass | 02–05 해시 4개 기록·일치, revision 1, design not_started |
| S13 | Pass | state 불변, 선택지 안내 |
| S14 | Pass | **03–05는 "front matter revision만 2로 올림"이라고 사전 안내(결함 4 해결)**, clean 파일은 백업 없음, 4개 문서 r2 |
| S15 | Pass | FR 10 / US 10 / FLOW 4 / AC 16 (S07 결과물: 10/11/7/21), 누락·오참조 0 |
| S16 | Pass | 미커밋 변경 03만 백업, 백업 = 수정 직전 내용 |
| S17 | Pass | 03만 감지, T9 → 4개 문서 r2 정렬, 추적성 0 누락 |
| S18 | Pass | revision 2 해시 4개 재기록·일치 |
| S19 | Pass | 대화형 호출 성공, state·notes 생성, 질문 출력 |

참고(이전 회귀): 픽스처를 만드는 과정에서 생긴 불일치 2건(S07 첫 시도)은 Skill이 정확히 감지해 중단했습니다. 픽스처를 수정한 뒤 다시 실행해 통과했습니다. headless에서 Skill이 실행하려던 `cd … && grep` 복합 명령 1건은 허용 목록에 없어 거부됐습니다. Skill은 파일을 직접 읽는 방식으로 점검을 대신 수행했습니다.

### 2026-11-05 한국어화 후 회귀 (새 테스트 영역)

환경은 위 최종 회귀와 같습니다. 공통 검사에 더해 **한국어 헤딩 검사**를 추가했습니다. 생성된 01–05에 `## 2. 문제 정의`, `## 11. 가정`, `## 12. 미결 질문`, `## 4. 기능 요구사항`, `## 9. 릴리스 기준`, `## 스토리 목록`, `## UI 플로우가 없는 스토리`, `## 추적 매트릭스`, `## 커버리지 점검`이 있고, 영어 단독 헤딩이 없는지 확인합니다.

| ID | 결과 | 실제 확인 |
|---|---|---|
| S01 | Pass | state 생성(discovery in_progress, planning/design locked), 한국어 질문, 01 미생성 |
| S02 | Pass | 02–05 미생성, Discovery r1 제출, 01 한국어 헤딩 확인 |
| S03 | Pass | 새 세션에서 awaiting_approval r1 보고·재제시 |
| S04 | Pass | state·문서 해시 불변 |
| S05 | Pass | 변경 계획 설명 → "진행" 후 r2, 미추적 파일 백업 1개(r1 내용) |
| S06 | Pass | 01 해시 일치, 02–05 생성, 01–05 모두 한국어 헤딩, 임시 파일 생성 없음 |
| S07 | Pass | 02 해시 불변, 03–05만 생성 |
| S08 | Pass | 기존 02 불변, 생성 없음 |
| S09 | Pass | 불일치 보고 후 중단 |
| S10 | Pass | 실행 거부, `.ai-workflow` 미생성 |
| S11 | Pass | 01만 해시 불일치로 감지, 파일 불변 |
| S12 | Pass | 02–05 해시 4개 기록·일치, revision 1, design not_started |
| S13 | Pass | state 불변 |
| S14 | Pass | 03–05의 "front matter revision만 1 → 2" 사전 안내, clean 파일 백업 없음, 4개 문서 r2 |
| S15 | Pass | FR 11 / US 11 / FLOW 5 / AC 15 (S07 결과물: 11/11/4/17), 누락·오참조 0 |
| S16 | Pass | 미커밋 변경 03만 백업, 백업 = 수정 직전 내용 |
| S17 | Pass | 03만 감지, T9 → 4개 문서 r2 |
| S18 | Pass | revision 2 해시 4개 재기록·일치 |
| S19 | Pass | 대화형 호출, state·notes 생성, 한국어 질문 출력 |

참고: S19 첫 시도에서는 모델의 점검용 셸 명령에 대해 Claude Code 권한 확인 창("Do you want to proceed?")이 떴습니다. 테스트 스크립트가 이 창에 응답하지 않아 대기 상태로 끝났습니다. 확인 창에 응답하도록 스크립트를 고친 뒤 다시 실행해 통과했습니다. 실제 사용 시에는 사용자가 이 확인 창을 승인하면 됩니다.
