# Milestone 2 — Implementation Workflow (`/product-build`)

- 목표: 승인된 기획·UX·디자인 산출물로 구현 계획을 만들고, Claude가 배치별로 코드를 작성·검증하며, 사용자는 중요한 정책 결정과 (위험) 배치 승인에 집중하는 범용 워크플로입니다.
- 기본 흐름: **계획 생성 → 사용자 계획 승인 → 배치 자동 구현 → 자동 검증 → 다음 배치**. 보안·권한·데이터 손실·승인 명세 변경 같은 중요한 결정만 사용자에게 묻습니다.
- 역할 분리: 코드와 계획 초안은 Claude가 만듭니다. 결정적 스크립트는 상태·검증·승인만 맡습니다.
- 단계: M2.1 계획·배치 생성(**구현됨**) → M2.2 배치 실행·상태(**구현됨**, 2026-11-12) → M2.3 자동 검증·AC 추적(**구현됨**, 2026-11-12) → M2.4 정책·편차·승인 통합(**구현됨**, 2026-11-12: M2.4a 증거 정책·최종 승인·영향 분석, M2.4b 정책·편차 원장·decide·문서 반영 대기열).

## 1. 확정된 설계 결정 (2026-11-11)

| # | 결정 | 반영 위치 |
|---|---|---|
| 1 | 프리뷰 미승인이면 사용자가 명시적으로 승인한 `preview_waiver`로 화면 배치 진입. `design.json`은 바꾸지 않음 | `build-state.md` §5, `waiver` |
| 2 | UX Spec 미승인이어도 승인된 Planning만으로 화면 없는 DB/API 배치 허용 | L0/L1 판정, `scope --draft` |
| 3 | 기본 범위 Must. Should/Could는 계획의 `scope.include`로 선택 | `compute_scope` |
| 4 | Must AC는 E2 이상. 보안·권한·데이터 손실 등 위험 AC는 강화 검증(E3, 프로필 `evidence.risk`) | `ac_targets` |
| 5 | Playwright는 선택 의존성(프로필 `[browser] enabled = false` 기본) | 프로필 |
| 6 | 정책은 blocking / provisional로 분류(M2.4 원장) | 이 문서 §3 |
| 7 | Git commit/push는 사용자만 수행 | SKILL 규칙 8 |
| 8 | 활성 실행 배치는 한 개 | `execute-gate` |
| 9 | 증거 원본 로그는 Git 제외, 요약만 관리 | `.ai-workflow/build/.gitignore` |
| 10 | 구현 순서는 프로젝트 프로필에서 선택(`order_strategy`), mock-first 강제 없음 | 프로필 |
| 11 | 기존 구현 adopt 지원(M2.1은 분석·후보까지) | `adopt` |
| 12 | 배치 승인 최소화: 배치마다 `approval: auto / user`를 스크립트가 판정. 위험 태그가 있는 배치만 사용자 승인이며, 자동으로 낮출 수 없음. waiver 배치 기본 auto | `build-state.md` §6 |

추가로 정한 사소한 설계 선택(M2.1 구현 중)
- `product_design.py check`는 상태를 기록할 수 있어 호출하지 않고, 읽기 전용 `status`만 호출합니다.
- 프리뷰가 새로 승인되는 것(L2 → L3)은 계획 무효화가 아닙니다.
- 위험 감지 기본 키워드에서 도메인 의존 단어('세션', '토큰', '폐기')는 뺐습니다. 실제 프로젝트 문서에서 오탐을 확인했습니다.
- 계획 문서는 JSON(검증 대상)과 생성 Markdown(승인 대상)으로 나눕니다. 승인 해시는 두 파일과 프로필을 함께 씁니다.

## 2. M2.1 구현 결과 요약

- 명령
  - `init`, `check`, `scan`, `scope [--suggest|--draft]`, `plan-validate`
  - `submit plan`, `approve plan`, `reopen plan`
  - `waiver add|revoke`, `status [--all]`, `adopt [--save|--full]`
  - `execute-gate --batch`, `guard`
- 테스트
  - `tests/product_build_test.py`: 가상 제품 2종(도서관 좌석 예약, 의원 진료 예약)과 L1·기획 미승인 경우
  - `tests/product_build_smapsh_check.py`: 실제 프로젝트 복제본
  - 결과는 `tests/build-scenarios.md`에 있습니다.

## 3. M2.2–M2.4 계획(요약)

| 단계 | 내용 | 진입 조건 |
|---|---|---|
| M2.2 배치 실행·상태 | `batch-start`(잠금·시작 기준선) → 작업별 `task-done`·`checkpoint` → `batch-submit`(보호 경로·범위 밖 변경·테스트 약화 탐지) → `resume`·`pause`. POL/DEV는 추가만. adopt 후보를 `imported`로 등록 | 아래 §4 |
| M2.3 자동 검증·AC 추적 | 프로필 명령 실행, 증거 저장(트리 해시), 테스트 리포트 파서(JUnit XML 기본), E0–E3·EM 판정, 브라우저 검사(선택), 배치 완료 판정·자동 진행 | M2.2 |
| M2.4 정책·편차·승인 통합 | 정책 원장(blocking/provisional, 임시값 코드 표지), 편차 원장(WF-D01 ①–⑤ 분류), `decide`, 배치 승인·reopen, 입력 변경 영향 계산, 문서 반영 대기열 | M2.3 |

## 4. M2.2 진입 조건

1. M2.1 결과를 사용자가 검토하고 커밋합니다. 특히 `docs/roadmap/`, `skills/product-build/`, `tests/` 변경입니다.
2. 아래 결정을 확인합니다.
   - 배치 실행 중 Claude가 수정할 수 있는 경로 범위(프로필 `paths.source` 기준으로 할지)
   - 배치 브랜치 권장 여부
   - 재시도 한도 기본값(제안: 3)
3. `/product-init` K1–K10(Docker 필요)은 M1 잔여 항목입니다. M2.2와 독립이지만, 실행 환경을 정하기 전에 상태를 확인하는 것을 권장합니다.
4. 실제 적용 파일럿은 SMAPSH **복제본**에서 합니다. 원본은 다른 세션의 작업이 끝나고 사용자가 승인한 뒤에만 적용합니다.

## 5. M2.2 결과와 M2.3 진입 조건 (2026-11-12)

- **구현**: `batch-start`·`task-done`·`checkpoint`·`check-run`·`batch-submit`·`pause`·`resume`·`guard --batch`(`pb_exec.py`), SKILL 6–8단계, `reference/execution.md`.
- **검증**
  - 스크립트 테스트 57/57
  - SMAPSH 복제본 11/11
  - Claude 대화 검증 7/7(`tests/harness/product_build/`)
  - 자세한 기록: `tests/build-scenarios.md`
- **M2.3 진입 조건**
  1. M2.2 변경을 검토하고 커밋합니다.
  2. 다음을 결정합니다.
     - 테스트 리포트 형식(JUnit XML 기본 + 러너별 JSON)과 E2 태그 규칙(테스트 제목 `[AC-xxx]`)
     - 브라우저 검사(Playwright) 설치 여부
     - 검증 통과 후 `dependency_min`을 `verified`로 올릴지
  3. `check-run` 로그는 지금 재시도 계산용입니다. M2.3에서 증거(트리 해시·리포트)로 격상할지 분리할지 결정합니다.

## 6. M2.3 결과와 M2.4 진입 조건 (2026-11-12)

- **구현**
  - `pb_verify.py`: 리포트 실행·출처 검증(pb-test-report/v1 JSON, JUnit XML), AC 태그(bracket·prefix·명시 필드), E0–E3 판정, 배치 판정, 무효화(stale·회귀·증거 유실), 상태 무결성
  - 명령 `verify`·`ac-report`, `status`의 `needs_reverify`
  - 선행 조건 기본값 `verified`(독립 배치 예외)
  - `reference/verification.md`, SKILL 6단계 검증 흐름
- **검증**: 스크립트 42/42, SMAPSH 복제본(vitest 135 케이스) 6/6, Claude 대화 7/7. 기록은 `tests/build-scenarios.md`.
- **M2.4 진입 조건**
  1. M2.3 변경을 검토하고 커밋합니다.
  2. 다음을 결정합니다.
     - **목표 증거 수준 조정 절차**: 예) 이미 구현된 코드에 E3를 요구할 때의 처리. 지금은 계획 재승인으로만 바꿀 수 있습니다.
     - **사후 실패 재현(구현을 일부러 깨뜨린 E3)을 인정할지**: 인정한다면 기록 방식이 필요합니다.
     - **배치 승인(`user` 배치)과 `verified`의 관계**: 승인 시점, 무효화 시 승인 철회.
  3. **정책·편차 원장(M2.4)이 다룰 입력**
     - 검증 실패 사유(목표 미달 AC)
     - 범위 밖 변경, 테스트 변경 확인 기록
     - 구현 중 임시값(`TODO(POL)`)
     - SMAPSH의 P1–P8·Q1–Q7

## 7. M2.4a 결과와 다음 단계 (2026-11-12)

- **범위 확인**: 로드맵 M2.4(정책·편차 원장, decide, 배치 승인·reopen, 입력 변경 영향 계산, 문서 반영 대기열)와 2026-11-12 요청(E3 증거 정책, 승인·검증 상태 구분, 영향 범위 재검증)은 충돌이 없습니다. 이번에는 요청 범위와 겹치는 승인·영향 계산을 구현했습니다(M2.4a). 원장·decide·문서 반영 대기열은 M2.4b로 남깁니다.
- **구현**
  - E3 증거 유형(fix·regression_fix·fault_injection·test_changed)
  - `adopt-register`(기존 구현 → E2부터)
  - `target`(사용자 승인 목표 변경, 원래 목표 보존)
  - `accept-fault-injection`(AC별 승인)
  - `approve batch`(최종 사용자 승인, 무효화 시 이력 보존)
  - `impact`(관련 배치만 재검증, 전이 후속 차단, 의존성 파일 디렉터리 기준)
  - 상태 무결성 확장
- **검증**: 스크립트 28/28 + M2.3 43/43, 회귀 전체 통과, Claude 대화 7/7, SMAPSH 복제본 16/16(vitest·pytest 실제 실행). 기록은 `tests/build-scenarios.md`.
- **다음 마일스톤(M2.4b) 진입 조건**
  1. M2.2–M2.4a 변경을 검토하고 커밋합니다.
  2. 다음을 결정합니다.
     - **원장 위치**: `build.json` 안 또는 별도 파일(문서 렌더링 포함)
     - **차단 정책이 열린 동안의 범위**: 배치 시작 차단만 할지, 승인도 막을지
  3. **원장 입력**
     - 검증 결과의 untested AC(SMAPSH 명단 6건)
     - 목표 변경·결함 주입 승인 기록
     - 범위 밖 변경, 테스트 변경 확인
     - `TODO(POL)` 표지
     - SMAPSH P1–P8·Q1–Q7

## 8. M2.4b 결과와 M2 완료 조건 (2026-11-12)

- **범위**: 로드맵 §7의 M2.4b(정책·편차 원장, decide, 문서 반영 대기열)와 요청이 일치합니다. 진입 조건 2의 결정 사항이 요청으로 정해졌습니다.
  - 원장: `state.yaml`과 분리된 별도 파일(`.ai-workflow/build/ledger.json`)
  - 차단 범위: 배치 시작과 최종 승인 모두
- **구현**
  - `pb_ledger.py`: 원장 4유형(policy·deviation·evidence_gap·target_change), 원문 digest 보존, 사람용 보기
  - 명령: `ledger add|list|sync|dismiss`, `decide`, `doc-proposal list|approve|reject|apply-check`
  - 차단 정책 적용: 시작·재개·최종 승인 차단, 실행 중 배치는 체크포인트에서 일시 중지, 독립 배치는 진행
  - `reference/ledger.md`, SKILL 9단계
- **검증**
  - 스크립트 35/35, 회귀 전체 통과
  - Claude 대화 9/9
  - SMAPSH 복제본 12/12
  - 기록: `tests/build-scenarios.md`

### M2 완료 조건(엔진 기준, 2026-11-12 개정)

`ai-product-workflow`는 특정 프로젝트 전용이 아닌 범용 엔진입니다. M2 완료는 **엔진 기준**으로만 판단합니다.
SMAPSH는 통합 검증용 사례 프로젝트이며, 그 정책 결정과 원본 적용은 M2 완료 조건이 아닙니다(아래 '사례 프로젝트 적용' 참고).

1. ~~M2.2–M2.4b 변경 커밋~~ — 완료(4d05b33).
2. 엔진 회귀 전체 통과(product-design·product-init·product-build 전체, 범용성 검사 `tests/engine_generality_test.py` 포함).
3. `/product-init` K1–K10 통과. 2026-11-12 실행 결과 9/10(판정기 수정 후 재판정), **K7(fe·be·db·smoke 검증)만 Docker 미가동으로 미검증** → Docker 가동 후 K7·K8 재실행이 남았습니다.
4. 동시성 결함 수정: `/product-init verify` 동시 실행 시 단계 기록 덮어쓰기 → 상태 잠금(`state_busy`)과 테스트 I12g–I12i로 수정 완료.
5. 정책 원장·decide·배치 차단·검증·승인이 사례 프로젝트와 무관한 가상 프로젝트(도서관 좌석 예약·의원 진료 예약 픽스처)에서 통과 — 완료(L1–L31 등).

### 사례 프로젝트 적용(M2 완료 조건 아님)

- SMAPSH의 P2·P7·Q5 등 정책의 의미와 결정은 SMAPSH 프로젝트가 소유합니다. 엔진은 상태·차단 여부·영향 범위·승인 이력만 관리합니다.
- `tests/fixtures/smapsh-policies.json`은 시범 등록용 테스트 입력이며 실제 결정 원장이 아닙니다.
- 원본 적용 계획: `docs/roadmap/smapsh-adoption-plan.md`(다른 세션 작업 커밋 후, 사용자 승인 지점마다 확인).
- (선택) 테스트 함수 단위 비교의 비Python 지원, 문서 적용 확인의 내용 비교는 다음 마일스톤 후보입니다.
