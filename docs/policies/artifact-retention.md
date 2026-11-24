# 산출물 분류·보관 정책 (v1)

> 적용 범위: AI Product Workflow를 쓰는 모든 제품 저장소. 이 정책은 **앞으로 생기는 산출물**에 적용합니다.
> 기존 프로젝트의 파일·승인 기록·`state.yaml`·`design.json`·`build.json`은 옮기거나 다시 쓰지 않습니다(마이그레이션 없음).

배경: SMAPSH 튜토리얼(SCR-101~103) 개발 중 Git 변경 파일이 1,460개까지 늘었습니다(정리 후 873개). 대부분은 엔진 명령이 만든 파일이 아니었습니다.
에이전트가 검토용으로 직접 만든 캡처·프레임·보드·측정 JSON(`design-explore/review/**` 약 400개, PNG 484개)이 원인이었습니다.
엔진에는 이런 일회성 결과를 둘 **정해진 저장소 밖 위치**가 없었습니다. 그래서 저장소 안에 임의 폴더가 생겼습니다.
그중 일부를 승인 문서(06·07)가 인용하면서, 임시 파일과 승인 근거가 한 폴더에 섞였습니다.

## 1. 분류 기준

| 분류 | 정의 | 판정 질문 | Git |
|---|---|---|---|
| **A. PRODUCT** | 실제 서비스가 쓰는 자산 | 제품 빌드·런타임이 이 파일을 읽는가? | 추적 |
| **B. APPROVAL** | 승인·재현에 꼭 필요한 자료 | 승인 해시·선택 기록·보존 집합에 들어 있거나 승인 문서가 경로로 인용하는가? | 추적 |
| **C. TEMP** | 일회성 탐색·검증·디버깅 결과 | 같은 명령을 다시 실행하면 만들 수 있고, 어떤 승인 기록도 이 파일을 가리키지 않는가? | 제외(가능하면 저장소 밖) |

애매하면 **B로 봅니다**. 승인 기록이 가리키는 파일을 TEMP로 잘못 분류하면 재현이 깨집니다. TEMP를 B로 잘못 분류하면 파일 수만 늘어납니다.

## 2. 현재 엔진 산출물 지도

| 단계 | 경로(생성 주체) | 분류 | 현재 Git 처리 |
|---|---|---|---|
| 기획·디자인 문서 | `docs/planning/*`, `docs/design/00–07` (Claude 작성, 엔진 해시) | B | 추적 |
| 상태·승인 | `.ai-workflow/state.yaml`, `design.json`, `build.json`, `build/ledger.json` (엔진) | B | 추적 |
| 백업 | `.ai-workflow/backup/**` (엔진, 단일 슬롯) | B(복구용) | 추적(프로젝트 선택) |
| Design Exploration 라운드 | `design-explore/<R>/brief.md`, 선택 시안 `plan.md`·렌더·`critique.md`, `selection/selection.json`, `selection/evidence/*`, `_assets/`(등록 자산 라운드 사본) (Claude 작성 + 엔진 복사) | B(보존 집합·파일별 해시) | 추적 |
| 미선택 시안 | `design-explore/<R>/<미선택>/` | TEMP(해시는 선택 기록에 남음) | `design-explore/.gitignore`(엔진 생성) |
| 탐색 측정 | `design-explore/<R>/shots/<run>/` (report.json·measure-spec.json·스크린샷, `explore-verify`) | TEMP(단, `design.json`이 report 경로·sha256을 기록) | `design-explore/.gitignore`의 `*/shots/` |
| 비교 페이지 | `design-explore/<R>/compare.html`, `compare/` (`explore-compare`) | TEMP(재생성 가능) | `design-explore/.gitignore` |
| 레퍼런스 원본 | `design-explore/references/*/original.*` | TEMP·개인정보(사용자가 `track`한 것만 B) | `design-explore/.gitignore` |
| Design Direction | `docs/design/07-design-direction.md`, `design-profile/theme.json`, 후보 테마(`<R>/<시안>/theme.json`·`tokens.css`), `selection/adoption/*` | B | 추적 |
| 시각 자산 | `design-profile/assets/**` (`explore-asset`) | A·B | 추적 |
| Design Preview | `design-preview/**` (트리 해시 = 프리뷰 승인 해시. `node_modules`·`dist`·`.vite` 제외) | B | 추적(`design-preview/.gitignore`는 빌드 결과만 제외) |
| Preview Review | `docs/design/06-preview-review.md` | B | 추적 |
| Preview Review 캡처 | **엔진 경로 없음** → 에이전트가 `design-explore/review/**` 등에 임의 생성 | TEMP(06이 인용한 파일만 B) | **규칙 없음 ← 파일 증가의 주원인** |
| 브라우저 검증(build) | `.ai-workflow/build/evidence/<B>/runs/<run>/reports/` (`PB_REPORT_DIR`), `attempts/*.log` | TEMP(요약·해시는 build.json에 기록) | `.ai-workflow/build/.gitignore`(엔진 생성) |
| UI 검토 묶음 | `.ai-workflow/build/ui/<B>/brief.json`·`plan.json`·`review.json` | B | 추적 |
| 화면 검증(변경 요청 M1) | `.ai-workflow/changes/<CR>/runs/<run>/`(report.json·measure-spec.json·shots/) | TEMP(run_id·리포트·명세 sha256·판정은 design.json의 CR 검증 기록과 패치에 기록) | 권장 `.gitignore`(`gitignore.recommended`). 엔진은 이 폴더의 `.gitignore`를 만들지 않음 |
| E2E·시각 회귀 도구 기본 출력 | `test-results/`, `playwright-report/` 등 (프로젝트 도구) | TEMP | 프로젝트마다 다름 |
| 시각 회귀 기준 스냅샷 | `*-snapshots/` 등 (프로젝트 테스트) | B(테스트 기준) | 추적 |
| 엔진 내부 임시 | `tempfile.mkdtemp`(UI 피드백 요청 등) | TEMP | 저장소 밖(실행 후 삭제) |

**주의(프리뷰 해시)**: `design-preview/` 안에 캡처를 저장하면 `.gitignore`로 제외해도 프리뷰 트리 해시가 바뀝니다. 그 결과 프리뷰 승인이 무효가 됩니다.
**주의(탐색 오염 검사)**: `design-explore/` 안의 모든 파일은 제품 코드 복사 검사(`pd_guard`)의 색인에 들어갑니다.
→ TEMP는 두 폴더 **밖**에 둡니다.

## 3. TEMP 경로 정책 (구현됨)

엔진 명령이 아닌 작업에서 만드는 일회성 결과는 엔진이 정한 실행 폴더에 씁니다. 검토 캡처, 프레임·보드, 임시 측정 JSON, 테스트 로그, 중간 렌더가 여기에 해당합니다.

```bash
# product-design·product-build 어느 쪽이든 같은 규칙(같은 경로)
python3 -I <engine>/skills/product-design/scripts/product_design.py temp-dir --project . --purpose preview-review
python3 -I <engine>/skills/product-build/scripts/product_build.py   temp-dir --project . --purpose e2e
```

- 루트: `$AI_WORKFLOW_TEMP_ROOT` → `$XDG_CACHE_HOME/ai-product-workflow/temp` → `~/.cache/ai-product-workflow/temp`
- 구조: `<루트>/<프로젝트 키>/runs/<용도>/<실행 ID>/`
  - 프로젝트 키 = `<폴더 이름>-<절대 경로 sha256 앞 10자>` (같은 이름의 다른 저장소와 섞이지 않음)
  - 실행 ID = `YYYYmmdd-HHMMSS-<6자>` (UTC)
  - 각 실행 폴더에 `RUN.json`(형식 `ai-workflow-temp-run/v1`, 용도·시각·`retention_days: null`)이 있습니다. `<프로젝트 키>/PROJECT.json`은 원래 저장소 경로를 기록합니다.
- 저장소 밖에 쓸 수 없으면(샌드박스 등) `.ai-workflow/tmp/`로 대체합니다(출력의 `location: repo_fallback`, `fallback_reason`).
  이 폴더는 스스로를 무시하는 `.gitignore`(`*`)를 만듭니다. 그래서 프로젝트 `.gitignore`를 고치지 않아도 Git 변경 파일이 늘지 않습니다.
  `--location outside|repo`로 강제할 수 있습니다. 루트가 제품 저장소 안이면 거부합니다(`temp_root_inside_project`).
- 오류 재현 자료 보관: 새로 만들 때 `--keep --note "<이유>"`를 주면 `kept/` 아래에 만들고 `KEEP.json`을 남깁니다. 이미 만든 폴더는 `--mark-keep <폴더> --note "<이유>"`로 표시만 합니다(이동 없음).
- 승인 근거 승격: 두 등록 명령 모두 **저장소 밖 파일을 거부**합니다. 그래서 남길 파일만 골라 저장소 안에 둔 뒤 등록합니다. 승인 문서가 TEMP 경로를 직접 인용하지 않습니다.
  - 디자인 탐색 증거(`explore-choose --evidence`, png·jpg·webp만): 엔진이 `selection/evidence/`(추적)로 **복사**해 해시합니다. 원본은 Git 제외 위치여도 됩니다. 증거가 될 캡처는 `temp-dir --location repo`로 받은 폴더(`.ai-workflow/tmp/`)에 두거나 그곳으로 복사해 등록합니다.
  - 수동 증거(`evidence-manual add --file`, 파일 종류 제한 없음): 엔진이 **그 경로를 그대로** 해시로 기록합니다(복사 없음). 그래서 Git이 **추적하는** 위치에 둡니다. `.ai-workflow/tmp/`나 `.gitignore`로 제외된 위치(예: `.ai-workflow/build/` 아래 `*.log`)에 두면 다른 환경에서 파일이 없어 증거가 `stale`이 됩니다. 등록 전에 `git check-ignore -v <파일>`로 확인합니다.
- 이 명령은 상태 파일·승인 해시·기존 산출물 경로를 바꾸지 않고, 아무것도 지우지 않습니다.

**바꾸지 않은 것(호환성)**: `explore-verify`의 `shots/`, `PB_REPORT_DIR`(`.ai-workflow/build/evidence`), `design-explore/.gitignore`·`.ai-workflow/build/.gitignore` 생성 규칙은 그대로입니다.
이 경로들은 `design.json`·`build.json`에 경로·해시로 기록되고 어댑터 계약(`PD_REPORT_DIR`·`PB_REPORT_DIR`)에 묶여 있습니다. 그래서 이번에는 옮기지 않았습니다(§6 후속).

## 4. Git 추적 정책

- 권장 규칙: [`gitignore.recommended`](gitignore.recommended). 프로젝트 `.gitignore` **끝에 블록째 덧붙입니다**. 기존 규칙을 덮어쓰지 않습니다. 시작·끝 표식으로 중복 추가를 막습니다.
- 원칙
  - 제품 이미지·아이콘·JSON(`design-profile/assets`, `frontend/public` 등)은 추적합니다. **이미지 확장자 전체를 무시하지 않습니다.**
  - 승인된 Preview(`design-preview/`), 보존 집합(`design-explore/**` 중 엔진 `.gitignore` 밖), 승인 문서가 인용한 근거는 추적합니다.
  - 임시 스크린샷·테스트 로그·중간 렌더는 저장소 밖 TEMP에 씁니다. 저장소 안에 생기는 도구 기본 출력만 권장 규칙으로 제외합니다.
  - `*.log` 전체는 무시하지 않습니다. 수동 증거로 등록한 로그는 경로·해시로 기록되므로 Git에서 빠지면 안 됩니다. 프로젝트가 이미 `*.log`를 무시하고 있다면 로그 증거는 `.log`가 아닌 이름(예: `.txt`)으로 두거나 `!` 예외 규칙을 둡니다.
  - `.gitignore`는 이미 추적 중인 파일에 영향이 없습니다. 엔진은 `git rm --cached`를 실행하지 않습니다(자동 추적 해제 금지).
- 기존 프로젝트: 권장 블록을 적용할지는 프로젝트 담당자가 정합니다. 적용 전에 `git status --ignored`로 승인 근거가 제외되지 않는지 확인합니다.

## 5. 정리(삭제) 정책 — 문서만, 자동 삭제 미구현

1. **삭제 후보**: TEMP 루트의 `runs/**` 실행 폴더 중 작업(배치·라운드·단계)이 끝난 것.
2. **제외(절대 자동 삭제 안 함)**:
   - `KEEP.json`이 있는 폴더(`kept/**` 전체 포함)
   - 저장소 안 파일 전부. 엔진 정리 기능은 TEMP 루트만 대상으로 합니다.
   - 저장소 안 Git 제외 파일(`shots/`·`evidence/`·미선택 시안)은 별도 정책 전까지 대상 아님
   - 승인 기록(`state.yaml`·`design.json`·`build.json`·`ledger.json`)·승인 문서·보존 집합이 경로나 해시로 가리키는 파일
3. **삭제 전 확인**: 후보마다 위 기록에서 경로·sha256 참조를 찾습니다. 참조가 있으면 후보에서 뺍니다. 해시 검증(`explore-status`·`check`)이 통과한 뒤에만 정리합니다.
4. **보관 기간**: `RUN.json`의 `retention_days`(현재 `null` = 무기한)와 향후 프로젝트 설정(예: `config.temp.retention_days`)으로 정합니다. 기본값은 정하지 않습니다.
5. **실행 절차**: `temp-clean --dry-run`(기본)이 후보·제외 사유·용량을 보여 줍니다. 사용자 승인 문장(`--confirm --note "<사용자 문장>"`)이 있어야만 지웁니다. 지운 목록은 TEMP 루트의 정리 기록에 남깁니다.

## 6. 후속 개선안 (이번 범위 밖)

| 항목 | 내용 | 영향 |
|---|---|---|
| `temp-clean` | §5 절차 구현(dry-run 기본, 참조·해시 검사, 사용자 승인 필수) | 신규 명령 |
| Preview Review 캡처 등록 | 06이 인용할 캡처를 `docs/design/preview-evidence/`로 복사·해시하는 명령(`explore-choose --evidence`와 같은 방식) | 06 형식·프리뷰 승인 기록 확장 → 승인 계약 변경 |
| `explore-verify` 산출물 이동 | `shots/<run>`을 TEMP 루트로 옮기고 선택 시 필요한 증거만 `selection/evidence`로 복사 | `design.json` 측정 기록의 `report` 경로 의미 변경, critique의 `shots/` 참조 규칙 변경 |
| 라운드 자산 사본 중복 | `explore-asset sync`가 등록 자산 전체를 라운드마다 복사(SMAPSH V06–V08 각 78–79개·14–16MB, 실제 참조는 13개). 권장: 실제 참조 자산만 복사. 과제 문서 `docs/roadmap/explore-asset-copy-dedup.md` | 참조만 복사하면 계약 변경 없음. 내용 주소 저장소로 바꾸려면 선택 기록 형식 변경 |
| 수동 증거 보관 위치 | `evidence-manual add`가 TEMP 파일을 받아 `docs/build/manual-evidence/`(추적)로 복사·해시하고, Git 제외 경로의 근거 파일은 경고(`.ai-workflow/build/.gitignore`의 `*.log` 등) | EM 기록 형식 확장 |
| product-init 연동 | 신규 프로젝트 초기화 때 권장 `.gitignore` 블록을 확인 후 추가(표식으로 멱등) | product-init apply 정책 |
| Skill 지시문 강제 | `design-explore/review/` 같은 임의 폴더 생성을 `check`가 경고 | 경고만(차단 아님) |
