# ai-product-workflow

요구사항에서 디자인, 구현, 검증까지 이어지는 AI 기반 제품 개발 워크플로입니다.

Claude Code Skill로 자연어 제품 아이디어를 **Product Discovery → 사용자 승인 → Product Planning(PRD, User Story, User Flow, Acceptance Criteria) → 사용자 승인**까지 연결합니다.

> 현재 범위: **`/product-start`(아이디어 → PRD)**, **`/product-init`(승인된 기획 → 공통 보일러플레이트 적용·검증)**, **`/product-design`(승인된 기획 → 화면 기획·UX 설계·정적 UI 프리뷰 → 승인)**, **`/product-build`(승인된 기획·디자인 → 구현 계획·배치 → 계획 승인 → 배치별 코드 구현 → AC 기반 자동 검증 → 최종 사용자 승인, 정책·편차 원장·decide·문서 반영 대기열)**.

## 특징

- `/product-start` 단일 진입점: 신규 시작, 중단 후 재개, 승인 처리를 모두 이 명령 하나로 합니다.
- 명시적 승인 게이트: Discovery 승인 전에는 Planning 문서를 만들지 않습니다. Planning이 승인돼야 Design 단계가 열립니다.
- 상태 파일 기반 재개: `.ai-workflow/state.yaml`과 실제 파일(존재 여부, revision, 승인 해시)을 매번 교차 검증합니다.
- 사실과 가정 분리: 사용자가 확인하지 않은 내용은 `ASM-`(가정)이나 `Q-`(미결) ID로 별도 관리합니다.
- 요구사항 추적성: `GOAL → FR → US → FLOW → AC` 추적 매트릭스와 누락 점검을 제공합니다.
- 파일 보호: 기존 파일은 설명과 확인 없이 덮어쓰지 않습니다. Git으로 보호되지 않는 파일만 단일 슬롯에 백업합니다.

## 저장소 구조

```
skills/product-start/
  SKILL.md                 진입점(절차·게이트·규칙)
  reference/               state-machine, file-safety, id-conventions, interview-guide
  templates/               state.yaml, 01-discovery … 05-acceptance-criteria
skills/product-init/
  SKILL.md                 진입점(사전 점검·적용 승인·충돌·검증)
  reference/               apply-policy, verify, manifest-schema
  scripts/product_init.py  결정적 보조 스크립트(Python 3.11+, 표준 라이브러리만)
  templates/               boilerplate.manifest.example.toml
skills/product-design/
  SKILL.md                 진입점(UX Planning → UX 설계 → UI 프리뷰 → 승인)
  reference/               design-state, ux-planning, ux-spec, review-checklist, preview
  scripts/product_design.py  결정적 보조 스크립트 진입점(CLI, Python 3.11+, 표준 라이브러리만)
  scripts/pd_core.py · pd_theme.py · pd_impact.py  공통(상태·승인·해시·검증) · 테마·렌더러·프리뷰 계약 · 변경 영향 분류
  templates/               00-ux-decisions … 06-preview-review, preview/(Vite+React 프리뷰 앱)
skills/product-build/
  SKILL.md                 진입점(범위 → 계획 초안 → 검증 → (preview waiver) → 계획 승인, adopt 분석)
  reference/               build-state, planning, execution, verification, ledger, adopt
  scripts/product_build.py  결정적 보조 스크립트 진입점(CLI, Python 3.11+, 표준 라이브러리만)
  scripts/pb_core.py · pb_inputs.py · pb_scan.py · pb_plan.py · pb_adopt.py · pb_exec.py · pb_verify.py · pb_ledger.py  상태·기준선 · 입력 모델 · 스택·코드 탐지 · 계획 검증·렌더링 · adopt 분석 · 배치 실행(잠금·체크포인트·범위) · AC 검증(리포트·증거 수준) · 정책·편차 원장
  templates/               build-profile.toml, implementation-plan.example.json
docs/architecture.md       설계
tests/scenarios.md         /product-start 테스트 시나리오와 실행 기록
tests/init-scenarios.md    /product-init 테스트 시나리오와 실행 기록
tests/product_init_test.py /product-init 스크립트 테스트(자체 완결형): python3 tests/product_init_test.py
tests/design-scenarios.md  /product-design 테스트 시나리오와 실행 기록
tests/product_design_test.py /product-design 스크립트 테스트(자체 완결형): python3 tests/product_design_test.py
tests/product_design_impact_test.py /product-design 디자인 변경 영향 분류(impact --design) 테스트
tests/product_design_v2_test.py /product-design 워크플로 v2 상태·전환·무효화 테스트
tests/product_design_dd_test.py /product-design Design Direction 단계·게이트·의미 해시 테스트
tests/product_design_theme_test.py /product-design 테마 계약·렌더러 경로 테스트(PD_FULL=1이면 프리뷰 빌드·승인 포함)
tests/build-scenarios.md   /product-build 테스트 시나리오와 실행 기록
tests/product_build_test.py /product-build 스크립트 테스트(자체 완결형, 가상 제품 2종)
tests/product_build_smapsh_check.py 실제 프로젝트 복제본 적용 확인(원본 경로는 거부)
tests/product_build_exec_test.py /product-build 배치 실행 테스트(M2.2, 자체 완결형)
tests/product_build_smapsh_exec_check.py 배치 실행을 실제 프로젝트 복제본에서 확인
tests/product_build_verify_test.py /product-build AC 기반 자동 검증 테스트(M2.3, 자체 완결형)
tests/product_build_smapsh_verify_check.py AC 검증을 실제 프로젝트 복제본(vitest JUnit)에서 시도
tests/product_build_approval_test.py /product-build 증거 정책·최종 승인·영향 분석 테스트(M2.4)
tests/product_build_smapsh_m24_check.py M2.4를 실제 프로젝트 복제본(vitest + pytest)에서 확인
tests/product_build_ledger_test.py /product-build 정책·편차 원장·decide·문서 반영 대기열 테스트(M2.4b)
tests/product_build_smapsh_ledger_check.py 원장 시범 등록을 실제 프로젝트 복제본에서 확인(fixtures/smapsh-policies.json)
tests/engine_baseline.py   회귀 비교용 고정 기준 엔진 추출(v1 엔진 b83907b, scripts 디렉터리 전체)
tests/fixtures/           테스트 고정 사례(디자인 변경 분류 D1–D15, SMAPSH 실제 배치 비교 기준)
tests/harness/            LLM 회귀 하네스(/product-start S01–S19, /product-init K1–K10)와 자동 판정기
```

## 설치(제품 프로젝트에서 사용)

엔진 저장소와 제품 프로젝트는 분리해서 사용합니다. 엔진 저장소 안에서는 실행되지 않습니다.

**A. 프로젝트 단위(권장, 전역 설정 변경 없음, 검증 완료)**

제품 프로젝트 루트에서 실행합니다. `ENGINE`은 이 저장소의 절대 경로입니다.

```bash
ENGINE=/path/to/ai-product-workflow
mkdir -p .claude/skills
ln -s "$ENGINE/skills/product-start" .claude/skills/product-start
```

심볼릭 링크로 연결하면 Skill의 `reference/`와 `templates/`가 프로젝트 밖에 있게 됩니다. 그래서 엔진 경로 읽기를 허용해야 합니다. `.claude/settings.local.json`(개인 로컬 설정)에 다음을 추가합니다.

```json
{
  "permissions": {
    "additionalDirectories": ["/path/to/ai-product-workflow/skills"]
  }
}
```

- 처음 실행하면 폴더 신뢰 확인 창에 "이 폴더가 작업 공간에 디렉터리 1개를 추가한다"는 경고가 표시됩니다. 경로를 확인한 뒤 **Yes, I trust this folder**를 선택합니다.
- 링크와 로컬 설정은 각자의 머신 경로를 담고 있으므로 커밋하지 않습니다. 예를 들어 `.git/info/exclude`에 `.claude/skills/product-start`와 `.claude/settings.local.json`을 추가합니다.
- headless(`claude -p`)에서는 위 설정 대신 `--add-dir /path/to/ai-product-workflow/skills` 옵션을 사용할 수 있습니다.

**B. 사용자 전역**: 모든 프로젝트에서 사용할 수 있습니다. `~/.claude`를 변경합니다.

```bash
ln -s /path/to/ai-product-workflow/skills/product-start ~/.claude/skills/product-start
```

이 경우에도 엔진 경로 읽기 허용(`additionalDirectories`)이 필요합니다. 프로젝트별 `.claude/settings.local.json`에 추가하거나 `~/.claude/settings.json`에 추가합니다.

## 사용법

```text
/product-start 배드민턴 동호회 로테이션을 학습하는 플랫폼을 만들고 싶어요
```

1. 질문에 답합니다. "모르겠다", "알아서 해줘"도 괜찮습니다. 답하지 않은 항목은 가정이나 미결 항목으로 남습니다.
2. Discovery 요약을 검토하고 **승인** 또는 **수정 요청**을 합니다.
3. 승인하면 `docs/planning/02`~`05`가 생성됩니다. 검토 후 다시 **승인** 또는 **수정 요청**을 합니다.
4. 중단했다면 인자 없이 `/product-start`를 실행하면 이어서 진행합니다.

제품 프로젝트에 생성되는 파일:

```
.ai-workflow/state.yaml            상태(기준 파일)
.ai-workflow/discovery-notes.md    인터뷰 원문 기록
.ai-workflow/backup/               (필요할 때만) 덮어쓰기 전 백업
docs/planning/01-discovery.md
docs/planning/02-prd.md
docs/planning/03-user-stories.md
docs/planning/04-user-flows.md
docs/planning/05-acceptance-criteria.md
```

산출물은 AI가 생성한 초안입니다. 승인 전에 반드시 사람이 검토해 주세요. 외부에 공유하기 전에는 기밀 정보나 개인정보가 들어 있지 않은지 확인해 주세요.

## `/product-init`: 보일러플레이트 적용

Planning이 승인된 제품 저장소에 공통 보일러플레이트(예: fullstack-boilerplate)를 **태그와 커밋 SHA로 고정**해서 **추가 전용**으로 적용하고 검증합니다.

**사전 준비**
- 보일러플레이트 저장소 루트에 `boilerplate.manifest.toml`이 있고(스키마: [manifest-schema.md](skills/product-init/reference/manifest-schema.md)), SemVer 태그(예: `v1.0.0`)가 푸시되어 있어야 합니다.
- 제품 저장소에서 Planning이 승인돼 있고, 커밋되지 않은 변경이 없어야 합니다.
- Skill 연결은 `/product-start`와 같은 방식입니다: `ln -s "$ENGINE/skills/product-init" .claude/skills/product-init`. 엔진 경로 읽기 허용도 같습니다. 보조 스크립트 실행에는 `python3`(3.11 이상)가 필요합니다.

**사용법**
```text
/product-init git@github.com:<owner>/fullstack-boilerplate.git v1.0.0
```
1. 출처(태그 → 커밋 SHA)를 확인하고, 프로젝트 이름(slug)과 제목을 정합니다.
2. 적용 계획을 검토합니다. 추가 / 동일 / 충돌 / 제외 / 보호 경로와 필수 설정 누락이 표시됩니다. **적용 승인**을 하고, 필요하면 전용 브랜치 생성도 승인합니다.
3. 충돌 파일(README.md, .gitignore 등)은 덮어쓰지 않습니다. 파일별로 승인한 경우에만 병합합니다.
4. FE / BE / DB / Smoke 검증을 단계별로 확인한 뒤 실행합니다. Docker 검증은 `<slug>-init-verify`라는 별도 Compose 프로젝트로 실행하고, 정리할 때 볼륨을 지우지 않습니다.
5. 중단됐다면 인자 없이 `/product-init`을 실행하면 이어서 진행합니다. 결과는 직접 검토한 뒤 커밋합니다.

제품 저장소에 생성·변경되는 것:
```
.ai-workflow/boilerplate.json    출처(저장소·태그·SHA), 계획, 승인, 적용 파일 SHA-256, 병합, 검증 결과
(보일러플레이트 파일)             추가 전용 — 기존 파일·.ai-workflow/state.yaml·docs/planning/은 변경하지 않음
```

`boilerplate.json`에는 스냅샷과 검증 로그의 로컬 임시 경로가 기록됩니다. 보일러플레이트를 로컬 경로로 지정했다면 그 경로도 기록됩니다. 커밋 전에 공유해도 되는 내용인지 확인해 주세요.

## `/product-design`: 화면 기획 → UX 설계 → UI 프리뷰

Planning이 승인된 제품 저장소에서 화면 단위 기획과 설계를 진행하고, 실제 화면을 정적 프리뷰로 확인한 뒤 승인합니다.

**사전 준비**
- 제품 저장소에서 Planning이 승인돼 있고 커밋되지 않은 변경이 없어야 합니다. `/product-init` 적용 여부와는 무관합니다(병행 가능).
- Skill 연결: `ln -s "$ENGINE/skills/product-design" .claude/skills/product-design` (엔진 경로 읽기 허용은 다른 Skill과 같음)
- 프리뷰 빌드에 Node 20.19 이상과 pnpm이 필요합니다(의존성 설치에 네트워크 사용).

**사용법**
```text
/product-design
```
1. **UX Planning**: 기획에서 아직 정해지지 않은 화면 기획 항목을 기능별로 2–4개씩 묻습니다. 질문마다 권장안과 근거가 있습니다. "알아서 해줘", "모르겠어요"도 괜찮습니다. 기획 범위를 바꾸는 요청은 결정하지 않고 기획 재검토 대상(PF)으로 남깁니다. 끝나면 **UX 결정 확정**.
2. **UX 설계**: IA와 화면 목록을 먼저 보여 주고 **구조 확인**을 받은 뒤, 화면별 명세(상태 6종 포함)·화면 흐름·컴포넌트·추적성을 만들어 **UX 설계 승인**을 받습니다.
3. **UI 프리뷰**: `design-preview/`에 mock 데이터 기반 정적 프리뷰를 만듭니다. `pnpm --dir design-preview dev` → http://localhost:55180/ 에서 화면·상태·폭별로 확인하고 화면별 피드백을 줍니다. 끝나면 **시각 디자인 승인**.
4. 중단했다면 `/product-design`을 다시 실행하면 이어서 진행합니다. 결과는 직접 검토한 뒤 커밋합니다.

제품 저장소에 생성되는 것:
```
.ai-workflow/design.json        디자인 상태(기준). state.yaml의 design: not_started는 "디자인 단계가 열림" 표시일 뿐입니다
.ai-workflow/design-notes.md    인터뷰·피드백 원문
.ai-workflow/backup/design/     (필요할 때만) 수정 전 백업
docs/design/00-ux-decisions.md … 06-preview-review.md (v2: 07-design-direction.md)
design-preview/                 정적 프리뷰(제품 코드 아님, 실제 API·인증 없음)
```

프리뷰는 시각 확인용이며 최종 제품 코드가 아닙니다. 실제 구현은 이후 `/product-build` 단계에서 `frontend/`에 합니다. Figma 파일은 자동으로 만들지 않으며, 필요하면 06 문서에 링크만 기록할 수 있습니다.

## `/product-build`: 구현 계획 → 계획 승인 → 배치 구현 → AC 검증 (M2.1–M2.3)

승인된 기획(US·AC)과 UX 설계(화면·컴포넌트)를 읽어 구현 범위를 계산하고, 배치(작업·의존성·순서·수정 범위·승인 정책)로 나눈 구현 계획을 만들어 승인받은 뒤, Claude가 배치별로 코드를 작성합니다. 배치를 구현하면 `verify`가 프로필의 테스트를 직접 실행해 AC별 증거 수준(E0–E3)을 판정하고 `verified`/`verify_failed`로 기록합니다. **배치 승인·정책 원장(M2.4)은 아직 없습니다.**

**사전 준비**
- Planning 승인(필수). 화면 배치는 UX Spec 승인(게이트가 켜졌으면 Design Direction 포함)이 필요합니다.
- 프리뷰가 승인되지 않았으면 사용자가 명시적으로 승인한 **preview waiver**로 화면 배치를 계획할 수 있습니다(`design.json`은 바꾸지 않음).
- UX Spec이 승인되지 않았으면 화면 없는 DB/API 배치만 계획할 수 있습니다.
- Skill 연결: `ln -s "$ENGINE/skills/product-build" .claude/skills/product-build`. 디자인 상태 판정에 같은 엔진의 `product-design` 스크립트를 쓰므로 두 Skill이 같은 엔진 경로에 있어야 합니다.

**사용법**
```text
/product-build            # 상태에 따라 재개(초기화 → 계획 → 승인)
/product-build status     # 기획·디자인·보일러플레이트·구현 계획 통합 상태
/product-build adopt      # 기존 구현 코드의 후보 분석(읽기 전용)
```
1. 프로필(`docs/build/build-profile.toml`)의 경로·검증 명령(탐지값)을 확인합니다. Docker를 전제하지 않습니다.
2. Claude가 범위 골격을 바탕으로 계획(`docs/build/implementation-plan.json`)을 쓰고, 스크립트가 AC·화면 중복·누락, 순환 의존, 디자인 준비, 승인 정책을 검증합니다.
3. 생성된 `docs/build/00-implementation-plan.md`를 검토하고 **구현 계획 승인**을 합니다. 배치마다 자동 진행/사용자 승인 필요(보안·권한·데이터 손실·스키마 변경 등)가 표시됩니다.
4. 승인 이후 기획·디자인 승인이 바뀌면 계획은 outdated가 되고 실행 진입이 막힙니다.
5. 계획 승인 뒤에는 배치를 이어서 구현합니다(`/product-build execute`). 작업마다 묻지 않고, 다음 경우에만 확인을 요청합니다: 보안·권한·개인정보·되돌리기 어려운 스키마·데이터 삭제 배치 시작, 기존 테스트의 삭제·약화, 다른 세션·사용자 변경과의 충돌, 재시도 한도 초과.
6. 중단되면 `/product-build resume`으로 이어 갑니다. 잠금·체크포인트로 끝난 작업은 다시 하지 않고, 그 사이의 외부 변경은 덮어쓰지 않고 보고합니다. `/product-build pause`로 일시 중지할 수 있습니다.
7. 코드는 배치의 수정 범위(`paths`) 안에서만 쓰고, 승인 문서·다른 Skill 상태는 바꾸지 않습니다. 커밋은 사용자가 합니다(배치별 브랜치 권장).
8. **AC 검증**: 테스트에 AC 태그(`[AC-001] …`, 또는 프로필 `tag_style = "prefix"`의 `AC-001 / AC-002: …`)를 붙이고, 검증 단계가 표준 JSON(`pb-test-report/v1`)이나 JUnit XML 리포트를 쓰게 합니다(`reference/verification.md`).
   - E2: 태그된 테스트가 유효한 실행에서 통과
   - E3: 실패→수정→통과 기록(보안·권한·데이터 손실 AC의 기본 목표)
   - 이름에 AC 번호가 있을 뿐인 테스트는 E1(언급)입니다.
   - 검증 뒤 코드가 바뀌면 재검증 필요(stale)가 되고, 선행 배치가 검증되지 않으면 의존 배치를 시작하지 않습니다.
   - Playwright는 선택입니다.
9. **증거 정책·승인(M2.4)**
   - 정상 코드를 일부러 깨뜨렸다 되돌린 이력은 E3가 아니라 '결함 주입' 유형입니다. AC별 사용자 승인이 있을 때만 인정됩니다.
   - 기존 구현은 `adopt-register`로 등록해 E2부터 검증합니다. 목표 변경은 사용자 승인으로만 하며, 원래 목표는 보존됩니다.
   - `verified`(자동 검증)와 `approve batch`(최종 사용자 승인)는 별개입니다.
   - 코드·의존성이 바뀌면 관련 배치만 재검증합니다(`impact`). 승인 이력은 지우지 않고 무효 표시만 합니다.
10. **정책·편차 원장(M2.4b)**
    - 원장: `.ai-workflow/build/ledger.json`. 보기는 `docs/build/10-decisions.md`입니다.
    - 정책 미결정·구현 편차·검증 증거 부족·목표 변경을 구분합니다.
    - 차단 정책(보안·권한·외부 계약·명세와 다른 행동)이 미결이면 그 배치의 시작·최종 승인을 막고, 실행 중 배치는 체크포인트에서 멈춥니다.
    - `/product-build decide`로 영향을 보고 사용자 결정을 원문 그대로 기록합니다(이전 결정은 이력으로 남음).
    - 문서 변경은 제안 → 사용자 승인 → 소유 Skill이 개정·재승인 → 적용 확인 순서이며, 승인된 원본을 직접 고치지 않습니다.

제품 저장소에 생성되는 것:
```
.ai-workflow/build.json            구현 상태(계획 revision·해시·입력 기준선·waiver·배치)
.ai-workflow/build/.gitignore      증거 원본 로그 제외(evidence/, *.log)
docs/build/build-profile.toml      프로젝트 프로필(사람이 편집)
docs/build/implementation-plan.json  계획(Claude 작성, 스크립트 검증)
docs/build/00-implementation-plan.md 계획 문서(스크립트 생성, 승인 대상)
.ai-workflow/build/ledger.json      정책·편차 원장(Git 추적) / docs/build/10-decisions.md 원장 보기(생성 문서)
.ai-workflow/build/lock.json        실행 잠금(실행 중에만, Git 제외)
.ai-workflow/build/runs/<배치>/      체크포인트·시작 때 테스트 사본(Git 제외)
.ai-workflow/build/evidence/        검증·재시도 실행 원본(run.json·리포트·로그, Git 제외. 요약은 build.json)
```

