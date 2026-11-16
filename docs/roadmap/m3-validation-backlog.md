# M3 실전 검증 백로그 (2026-11-13)

상태: **분석 문서(구현 전)**. 엔진 코드는 바꾸지 않았습니다.
근거: 검증 프로젝트(SMAPSH, `badminton-playbook`)에서 Planning r6 → Design(UX Planning r4·UX Spec r2·Design Direction r2·Preview r1) → Build(계획 r2, B0·B7 verified)까지 실제로 진행한 기록. 프로젝트 사례는 **재현 근거**로만 쓰고, 해결 방향은 프로젝트와 무관하게 적습니다.

검증 프로젝트 기준 커밋: `120a936`(B0), `7846d65`(B7). 엔진 기준 커밋: `0edcd4c`.

## 0. 요약

| ID | 우선순위 | 분류 | 한 줄 |
|---|---|---|---|
| P0-1 | 즉시 | 결함 | 파일 안 아무 `CMP-xxx` 문자열(주석 참조 포함)을 부품 표지로 보고 `duplicate_component`로 차단 |
| P0-2 | 즉시 | 결함 | UI Plan의 설명 문자열에 `design-preview/`가 나오기만 해도 `preview_reuse`로 차단 |
| P1-1 | 설계 검토 | 검증 공백 | 화면을 소유하지 않고 `touches`만 있는 UI 배치의 Brief에 그 화면들의 명세·VD가 없음 |
| P1-2 | 설계 검토 | 검증 공백 | UI Plan 검증이 빈 `screens`를 그대로 통과(검사할 대상이 없음) |
| P1-3 | 설계 검토 | 검증 공백 | UI Review가 화면 증거 0건이어도 `ready` |
| P1-4 | 설계 검토 | 검증 공백 | 배치 AC가 다른 배치 소유(또는 touches) 화면의 상태를 가리키면 UI Plan에서 연결할 방법이 없음 |
| P2-1 | 후순위 | 사용성 | `init`이 만든 `.gitignore`가 실행 시 쓰는 목록과 달라 첫 `batch-start`에서 파일이 바뀜 |
| P2-2 | 후순위 | 사용성 | 검증 단계의 환경 전제(DB 마이그레이션 등)를 표현할 수 없어 `not_run`이 아니라 `failed`가 됨 |
| P2-3 | 후순위 | 사용성 | 기반 정리만 하는 foundation 배치가 `empty_batch`로 막힘 |
| P2-4 | 후순위 | 사용성 | 대응표가 CMP 하나에 파일 하나만 표현(변형별로 나뉜 구현을 담지 못함) |
| P2-5 | 후순위 | 사용성 | 기존 `design-preview/`의 manifest revision을 새 승인 기준으로 올리는 공식 명령이 없음 |

---

## P0 — 즉시 수정할 결함

### P0-1. 주석의 CMP 참조를 중복 부품 표지로 오인

1. **코드 위치**
   - `skills/product-build/scripts/pb_ui.py` `map_problems()` 안 중복 판정(약 319–340행): 대응되지 않은 파일의 앞 4000자에서 `re.findall(r"CMP-\d{3}", txt)` → 대응된 CMP면 `[duplicate_component]` 오류
   - 같은 규칙의 후보 탐지: `pb_scan.py` `component_inventory()`(약 236–245행, 앞 2000자의 `CMP-\d{3}`를 `cmp_markers`로)
   - 차단 지점: `product_build.py` verify의 UI 대응표 차단(약 1994행 `blocking = [... startswith("[duplicate_component]") ...]`), `pb_uiguard.py`(약 51·367행, `duplicate_component` → T2)
2. **재현 조건**: 대응표에 `CMP-021 → components/Sheet.tsx`가 있고, 같은 배치 범위의 다른 파일(예: 보조 훅 `sheetHooks.ts`, 사용처 `EditPerson.tsx`)의 주석에 `CMP-021`·`CMP-045`가 **참조로** 적혀 있음 → `ui-map check --batch`가 오류, 그대로면 `verify`·`ui-guard` 차단. (검증 프로젝트 B7에서 2건 발생, 주석에서 ID를 부품 이름으로 바꿔 우회)
3. **현재 / 기대**: 현재는 ID 문자열만 있으면 "그 CMP를 구현한 파일"로 봄 / 기대는 **구현 표지**와 **참조**를 구분해, 구현 표지가 있을 때만 중복으로 판정
4. **범용 해결 방향**
   - 표지 문법을 정합니다(프레임워크 무관한 텍스트 규칙): 예) 렌더 속성 `data-cmp="CMP-xxx"`, 또는 파일 머리 주석 첫 블록의 `CMP-xxx <PascalName>` 선언 중 하나. 프로필 `[ui] marker`로 프로젝트가 고를 수 있게 하고 기본값은 "선언형 머리 주석 또는 data 속성".
   - 본문 주석·문서 문자열의 ID 언급은 표지가 아니라 **참조**로 분류(오류 아님, 정보).
   - `component_inventory`와 `map_problems`가 같은 판정 함수를 쓰게 통일(현재 2000자/4000자로 범위도 다름).
   - `data-cmp="CMP-xxx"`가 **사용처**(대응 부품을 감싸는 화면)에도 붙는 프로젝트가 있으므로, data 속성은 "그 파일이 대응 부품을 import하지 않고 같은 표지를 렌더"할 때만 중복 후보로 봄.
5. **안전장치 영향**: 중복 생성 방지(§2 ui.md)의 목적은 유지. 판정이 좁아지므로 **진짜 중복을 놓칠 위험**이 생김 → 이름 일치 경고(`possible_duplicate`)와 UI Plan의 `cmp_mapped_rebuilt`·`duplicate_of_mapped`가 2차 방어로 남아 있음을 테스트로 고정.
6. **회귀 테스트 제안**(`tests/product_build_ui_test.py`, `product_build_uiguard_test.py`)
   - 주석 참조만 있는 파일 → 오류 없음(참조 정보만)
   - 머리 선언 `// CMP-021 Sheet`가 있는 비대응 파일 → `duplicate_component`
   - `data-cmp="CMP-021"`을 직접 렌더하고 대응 부품을 import하지 않는 파일 → 오류, import해서 감싸는 파일 → 오류 없음
   - `scan`의 후보와 `ui-map check` 판정이 같은 입력에서 같은 결과
7. **우선순위**: P0(정상 코드가 verify·ui-guard에서 막힘, 우회하려면 추적 주석을 지워야 함)

### P0-2. UI Plan notes의 일반 경로 언급을 preview 재사용으로 오인

1. **코드 위치**: `pb_ui.py` `_preview_refs()`(약 795–807행)가 UI Plan 전체를 재귀로 훑어 **모든 문자열**에서 `PREVIEW_DIR` 부분 문자열을 찾음(예외는 키 `visual_ref`뿐) → `ui_plan_validate`(약 876–877행)에서 `preview_reuse` 오류. 같은 계열: 약 1020행(components의 파일), `product_build.py` 약 1726행(ui-map register 경로)
2. **재현 조건**: UI Plan `notes`에 "프리뷰(design-preview/)는 시각 참고만" 같은 설명을 적음 → `[preview_reuse] notes[2]` 오류, `batch-start`가 `ui_plan_required`로 거부
3. **현재 / 기대**: 현재는 설명 문장도 "제품 코드 입력"으로 판정 / 기대는 **경로로 쓰이는 필드**(tree의 `file`, `data[].mock_file`, `components.*.file`, `states.*.ref` 중 경로형)만 검사하고, 자유 서술 필드(`notes`, `how` 설명 등)는 제외
4. **범용 해결 방향**: 검사를 "경로 필드 화이트리스트" 방식으로 바꿈. 자유 서술 필드에서 프리뷰 경로가 나오면 오류가 아니라 경고(`preview_mentioned`)로 남김.
5. **안전장치 영향**: 프리뷰 코드의 제품 재사용 금지 원칙은 그대로(경로 필드·대응표·verify 범위 검사가 계속 차단). 자유 서술에 실제 경로를 숨기는 우회는 의미가 없음(엔진이 그 문자열로 파일을 읽지 않음).
6. **회귀 테스트 제안**(`tests/product_build_ui_test.py`·`product_build_uiplan_reuse_test.py`): `notes`에 프리뷰 경로 → 통과+경고 / tree `file`·`mock_file`·components `file`에 프리뷰 경로 → 오류 유지 / `visual_ref` → 통과
7. **우선순위**: P0(설명을 쓰면 실행이 막혀, 계획자가 맥락 기록을 피하게 됨)

---

## P1 — 설계 검토가 필요한 검증 정책

공통 배경: 계획 형식은 화면을 한 배치만 **소유**(`screens`)하고 다른 배치는 **영향**(`touches`)만 갖게 합니다. 공통 레이아웃·공통 부품 정비처럼 "여러 화면을 고치되 소유하지 않는" 배치에서 UI 흐름(M3.2–M3.5)의 증거가 비게 됩니다. 아래 네 항목은 같은 뿌리이므로 **한 설계로 함께** 다루는 것을 권장합니다.

### P1-1. touches-only UI 배치의 Brief에서 관련 화면·VD 누락

1. **코드 위치**: `pb_ui.py` `build_brief()`(약 572–650행). 화면별 블록·VD는 `screens`(소유)만 만들고(약 596–613행), `touches`는 이름·상태 목록만(약 614–617행). 전역 VD는 `related`에 SCR·CMP가 **하나도 없는** VD만(약 632–633행) → 재사용 CMP에 묶인 VD도 빠짐
2. **재현 조건**: 계획 배치가 `screens: []`, `touches: [12개]`, `components.reuse: [CMP-021…]`. Brief의 `screens` 비어 있음, VD는 SCR·CMP와 무관한 4개만(정작 구현 대상 VD-021·024·025는 빠짐)
3. **현재 / 기대**: 현재는 구현 기준(VD·레이아웃)을 Brief가 담지 못해 구현자가 원문을 직접 찾아야 함 / 기대는 `touches` 화면의 레이아웃 원문·관련 VD, 그리고 **배치가 재사용·신규로 다루는 CMP에 연결된 VD**를 Brief에 포함(표시는 `scope: touched`)
4. **범용 해결 방향**: Brief에 `touched_screens` 블록 추가(02 레이아웃·상태·VD, 다만 상태의 `required`는 false). VD 선택 규칙을 "소유 화면 또는 touches 화면 또는 배치 CMP와 related가 겹치는 VD"로 확장.
5. **안전장치 영향**: Brief digest 입력이 늘어 touches 화면 명세가 바뀌면 그 배치가 stale이 됨(의도된 동작). Brief 크기 증가.
6. **회귀 테스트**(`tests/product_build_reuse_brief_test.py`): touches-only 배치에 touches 화면 레이아웃·VD가 들어감 / 배치 CMP와 related가 겹치는 VD 포함 / touches 화면 02 블록 변경 → brief stale
7. **우선순위**: P1

### P1-2. UI Plan 검증이 빈 screens 상태를 충분히 검사하지 않음

1. **코드 위치**: `pb_ui.py` `ui_plan_validate`(약 868–1020행). `screen_missing`은 Brief의 소유 화면 기준(약 887–889행)이라 Brief가 비면 검사 대상 0 → 형식만 맞으면 통과
2. **재현 조건**: 위 배치에서 skeleton 그대로(`screens: {}`) 저장 → `ok: true`, 오류·경고 0
3. **현재 / 기대**: 현재는 "UI 배치인데 화면 계획이 하나도 없음"을 알리지 않음 / 기대는 UI 배치에서 `screens`가 비면 최소 경고(`no_screen_plan`), touches 화면이 있으면 그 화면의 **변경 의도**(`touched: {SCR: {changes, states_affected}}`)를 요구하거나 경고
4. **범용 해결 방향**: UI Plan에 `touched` 섹션(선택) 추가. 비어 있으면 경고, 프로필 `[ui] strict_touches = true`면 오류.
5. **안전장치 영향**: 기존 소유 화면 규칙은 그대로. 경고부터 도입해 기존 계획을 깨지 않음.
6. **회귀 테스트**(`tests/product_build_ui_test.py`): 소유 0·touches N인 UI 배치 → 경고 / strict → 오류 / 소유 화면 있는 배치 → 기존과 동일
7. **우선순위**: P1

### P1-3. UI Review가 화면 증거 0건이어도 ready

1. **코드 위치**: `skills/product-build/scripts/pb_uireview.py` 차단 목록 구성(약 100–141행) → `body["ready"] = not blockers`. "필수 상태 E2 미충족"은 Brief의 required 상태 기준이라 소유 화면이 없으면 차단이 생기지 않음. 브라우저 단계가 없으면 `not_configured`(경고만)
2. **재현 조건**: 위 배치 verify 통과 후 `ui-review` → `screens: {}`, `blockers: []`, `ready: true`(시각 증거 0으로 사람 승인 단계까지 감)
3. **현재 / 기대**: 현재는 "볼 것이 없는 검토 묶음"이 승인 가능 / 기대는 UI 배치 검토 묶음에 **화면 증거가 하나도 없으면** 최소 경고, 정책에 따라 차단(예: touches 화면의 대표 상태에 브라우저·수동 증거 1건 이상 요구)
4. **범용 해결 방향**: 검토 묶음에 `coverage.touched_screens`와 증거 수를 넣고, `evidence_empty`를 경고로 추가. 프로필 `[ui] require_visual_evidence = "none|warn|block"`(기본 warn).
5. **안전장치 영향**: 기본 warn이면 기존 흐름을 깨지 않음. block은 브라우저 단계나 EM 기록이 가능한 프로젝트에서만 의미가 있으므로 프로필 선택.
6. **회귀 테스트**(`tests/product_build_uireview_test.py`): 화면 증거 0인 UI 배치 → ready이지만 경고 / block 설정 → ready false / EM 1건 추가 → 해소
7. **우선순위**: P1(승인 품질에 직접 영향)

### P1-4. AC가 touches 화면의 상태를 가리킬 때 UI Plan 연결 불가

1. **코드 위치**: `pb_ui.py` AC 연결 검사(약 995–1005행)는 소유 화면 블록 안의 `acs`만 다룸. verify의 `ac_links`(05 AC→상태 + UI Plan acs)도 소유 화면 기준 → 이 AC의 상태 증거 연결이 비어 "AC는 통과했지만 연결 상태 증거 없음" 같은 신호조차 없음
2. **재현 조건**: 배치 AC가 다른 배치 소유 화면의 상태를 가리킴(예: AC → SCR-101-ST1, SCR-121-ST1). Brief `acs`에는 있으나 화면 블록이 없어 UI Plan에서 상태 연결 불가
3. **현재 / 기대**: 현재는 연결하지 않아도 통과, 연결하려 해도 `screen_unknown` / 기대는 touches 화면 상태에 AC를 연결할 수 있고(`touched.<SCR>.acs`), 연결이 없으면 경고
4. **범용 해결 방향**: P1-2의 `touched` 섹션에 `acs` 허용. verify의 `ac_links` 계산에 touched 연결 포함.
5. **안전장치 영향**: 화면 소유권 규칙(한 화면 한 배치)은 그대로. 상태 증거는 "어느 배치가 낸 증거인지"를 기록해 다른 배치의 증거와 섞이지 않게 해야 함.
6. **회귀 테스트**(`tests/product_build_uiev_test.py`): touched 상태에 AC 연결 → `ac_links`에 표시 / 소유 배치의 상태 증거와 분리 기록 / 연결 없음 → 경고
7. **우선순위**: P1

---

## P2 — 후순위 사용성 개선

### P2-1. init .gitignore 누락

1. **코드 위치**: `product_build.py` `cmd_init`(약 145–147행)이 `evidence/`, `*.log`만 씀. 실행 쪽 `pb_exec.py` `GITIGNORE_LINES = ("evidence/", "*.log", "runs/", "lock.json")`(약 29행)과 `ensure_gitignore()`(약 292–297행)가 `batch-start`·verify 때 나머지를 덧붙임
2. **재현**: `init` 후 커밋 → 첫 `batch-start`에서 `.ai-workflow/build/.gitignore`가 바뀌어 작업 트리가 다시 더러워짐
3. **현재 / 기대**: 두 곳이 다른 목록 / `init`이 `ensure_gitignore()`를 호출해 같은 목록을 씀
4. **해결 방향**: 목록 상수 하나만 쓰기
5. **안전장치 영향**: 없음
6. **회귀 테스트**(`tests/product_build_test.py`): init 직후 `.gitignore`가 `GITIGNORE_LINES` 전체를 포함 / batch-start 후 파일 해시 불변
7. **우선순위**: P2(쉬움, 첫 커밋 경험 개선 — P0와 함께 처리 권장)

### P2-2. 테스트 DB 마이그레이션 사전 조건

1. **코드 위치**: `pb_scan.py` 검증 명령 후보(약 115–174행)가 Makefile 대상 이름만 보고 `requires: ["docker"]`를 붙임. 프로필 단계에는 "환경 준비 상태"를 표현할 필드가 없음
2. **재현**: Docker가 켜져 있지만 테스트 DB가 마이그레이션 전 → `make test-db`가 `failed`(테이블 없음). 프로젝트 README의 전제(`migrate` 먼저)를 엔진이 모름
3. **현재 / 기대**: 환경 준비 부족이 코드 실패와 같은 `failed`로 기록 / 기대는 전제 단계를 선언하고, 전제가 실패하면 그 단계는 `not_run(precondition)`로 구분
4. **해결 방향**: 단계에 `before = ["<프로필 단계 이름>"]`(전제 단계, 실패하면 본 단계 not_run) 또는 `setup = "<명령>"`(승인된 프로필에 함께 기록되므로 임의 명령 아님). `scan`은 Makefile·README에서 `migrate`·`setup` 대상을 찾으면 전제 후보로 제안만 함.
5. **안전장치 영향**: 전제 명령도 승인된 프로필의 일부라 해시 대상(임의 실행 금지 유지). DB를 바꾸는 명령이므로 `requires`·위험 표시 필요.
6. **회귀 테스트**(`tests/product_build_verify_test.py`): 전제 실패 → 본 단계 not_run(사유) / 전제 성공 → 본 단계 실행 / 전제가 프로필에 없으면 기존과 동일
7. **우선순위**: P2

### P2-3. foundation empty_batch

1. **코드 위치**: `skills/product-build/scripts/pb_plan.py` 약 368–369행: AC·화면·`components.new`가 모두 없으면 `empty_batch`
2. **재현**: 기존 부품 대응표 정리·토큰 연결처럼 "새 부품·AC·화면 없이 기반만 확인"하는 foundation 배치 → 오류. 검증 프로젝트는 범위 밖 공통 화면 하나를 소유시켜 통과
3. **현재 / 기대**: foundation의 정당한 작업을 표현 불가 / foundation은 `components.reuse` 또는 비어 있지 않은 `tasks`(docs·test·infra)만 있어도 허용
4. **해결 방향**: `kind == "foundation"`이면 `components.reuse`나 tasks가 있으면 통과, 대신 경고 `foundation_no_outputs`
5. **안전장치 영향**: 빈 배치로 실행 순서를 어지럽히는 위험은 tasks 필수로 막음
6. **회귀 테스트**(`tests/product_build_test.py`): foundation+reuse+tasks → 통과+경고 / ui 배치 빈 것 → 기존대로 오류
7. **우선순위**: P2

### P2-4. CMP 다중 파일 대응

1. **코드 위치**: 대응표 형식 `pb-ui-map/v1`의 `components.CMP: {path, export}`(ui.md §2), 등록 `product_build.py` `cmd_ui_map` register(약 1686–1720행), 판정 `map_problems`(`mapped_paths` 1:1)
2. **재현**: 한 CMP 계약(예: 경기 카드, `context=session|clubMatch`, `audience=ops|member`)이 코드에서 변형별 파일 3개로 나뉜 경우 → 하나만 등록 가능, 나머지는 중복으로 판정될 수 있음
3. **현재 / 기대**: 1 CMP = 1 파일 / 1 CMP = 기본 파일 + 변형 파일 목록(각각 어떤 변형인지)
4. **해결 방향**: `{path, export, variants: [{path, export, variant: "context=session"}]}`. 중복 판정은 variants 경로도 대응된 것으로 봄. 변형 등록도 사용자 확인 문장 필요.
5. **안전장치 영향**: 변형을 남용해 "중복 구현을 합법화"할 수 있으므로 변형 값이 04 CMP 변형 정의에 있어야 등록 가능하게 제한
6. **회귀 테스트**(`tests/product_build_ui_test.py`): 04에 있는 변형으로 등록 → 통과, 없는 변형 → 거부 / variants 파일은 duplicate 아님
7. **우선순위**: P2

### P2-5. 기존 Preview revision 갱신

1. **코드 위치**: `skills/product-design/scripts/product_design.py` `cmd_preview_scaffold`(약 546–567행)는 `design-preview/`가 있으면 `existing_files`로 거부. manifest의 `ux_spec_revision`·`design_direction_revision`·화면 목록을 새 승인 기준으로 맞추는 명령이 없음 → 손으로 수정(엔진 상태 파일은 아니지만 검사 대상)
2. **재현**: UX Spec·Design Direction 재승인 뒤 Preview 재작업 → `preview-check`가 revision 불일치 오류, 공식 갱신 경로 없음
3. **현재 / 기대**: 수동 편집 / `preview-scaffold --refresh-manifest`(또는 `preview-manifest sync`)로 revision과 화면 목록(02 기준 추가·삭제)을 갱신하고, 화면별 `file`·`states`·`vd`는 보존
4. **해결 방향**: 기존 항목은 유지, 02에 새로 생긴 화면만 빈 항목으로 추가, 사라진 화면은 보고만(자동 삭제 없음)
5. **안전장치 영향**: 승인된 프리뷰 이후라면 트리 해시가 바뀌므로 기존 승인 무효화 규칙(`approved_modified`)이 그대로 작동
6. **회귀 테스트**(`tests/product_design_v2_test.py`): 재승인 후 갱신 → revision 일치, 기존 화면 항목 보존 / 승인 상태에서 실행 → 거부 또는 경고
7. **우선순위**: P2

---

## 기타 관찰(이번 백로그 범위 밖, 기록용)

- `product_design.py check`가 기획 변경을 감지하면 `design.json`에 outdated를 **씁니다**. 진단 명령처럼 보이므로 `--dry-run`이나 문서 명시가 필요합니다.
- `product_design impact`는 ID 참조만 따라가서, ID 없이 값만 바뀐 문구(예: 최대 너비 값)는 영향 목록에 나오지 않습니다.
- `product_build init`이 Makefile에서 옮긴 단계 이름과 리포트 설정은 사람이 다시 손봐야 E2 판정이 가능합니다(리포트 없는 단계는 E2 불가). `scan`이 리포트 옵션 후보(vitest junit·pytest junitxml)를 제안하면 좋습니다.

## 엔진 개선 계획 제안

1. **즉시 수정(한 커밋 단위)**: P0-1, P0-2, P2-1. 판정 범위만 좁히는 변경이라 기존 안전장치를 약하게 만들지 않도록 회귀 테스트를 먼저 씁니다.
2. **설계 검토 후 구현**: P1-1~P1-4를 "touches 배치의 UI 증거 모델" 하나의 설계 문서로 묶어 결정합니다(소유권 규칙은 유지, touched 섹션·경고 기본값·프로필 선택지).
3. **후순위**: P2-2(전제 단계), P2-3(foundation), P2-4(변형 대응), P2-5(manifest 갱신).

## 새 빈 프로젝트에서 검증할 시나리오

검증 프로젝트에서 다루지 않았거나 이번 수정의 회귀를 확인할 항목입니다(`docs/build-scenarios.md`·`docs/design-scenarios.md`에 추가 권장).

1. 빈 저장소에서 `/product-init` → `/product-start` → `/product-design`(v2, 게이트 켬) → Preview 승인 → `/product-build` 계획 → B0(새 부품 생성, `--source built`) → 화면 소유 UI 배치 1개 → touches-only 정비 배치 1개.
2. 브라우저 단계(`pb-ui`)를 프로필에 넣고 `browser_pending` → 실행 → 통과로 UI 승인까지.
3. adopt-register(imported) 흐름과 E3 실패 → 통과 기록, 결함 주입 거부.
4. 위험 배치 `--confirm-risk`, pause·resume·take-over, 재시도 한도.
5. waiver(L2) 경로와 UX Spec 재승인 시 waiver 무효화.
6. 이번 P0 회귀: 주석 참조·data 속성·머리 선언이 섞인 부품 폴더에서 `scan`·`ui-map check`·`ui-guard`·`verify` 판정 일치.
