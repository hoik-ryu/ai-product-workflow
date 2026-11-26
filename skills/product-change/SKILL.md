---
name: product-change
description: 이미 승인된 제품(기획·디자인·구현 계획·배치)의 변경을 하나의 변경 패키지(Change Package)로 묶어, 사용자 승인 2회(변경 계약 → 최종 통합)로 기획·디자인·구현에 반영합니다. ID 단위 영향 분석(간접 전파 포함), 계약 범위 안 승인 승계, 최종 통합 승인 후 finalize·재개, 공식 빌드·배포 게이트를 제공합니다. 사용자가 /product-change를 실행하거나 승인된 제품의 요구사항 변경(AC 폐기·수정 등)을 요청할 때 사용합니다.
argument-hint: "(변경 요청 설명 — 예: AC-164 취소 복원 기능을 폐기)"
disable-model-invocation: true
---

# /product-change — 승인된 제품의 변경 패키지

사용자의 **제품 저장소**(현재 작업 디렉터리)에서 실행합니다. 이 Skill의 기본 디렉터리를 `$SKILL`로 표기합니다.

- `reference/change-package.md`: 상태·계약 형식·영향 분석 규칙·승인 결합·finalize·복구·한계 (**먼저 읽기**)
- `scripts/product_change.py`: 모든 판정·상태 기록(JSON 출력, 차단 시 종료 코드 2). `pc_graph.py`(ID 그래프·영향 분석)를 불러옵니다.

호출 형식: `python3 $SKILL/scripts/product_change.py <명령> --project "$PWD" ...`

이번 실행의 사용자 입력: `$ARGUMENTS`

## 언제 쓰는가

- 기획·디자인·구현 계획이 **이미 승인된** 제품에서 요구사항을 바꿀 때(AC 폐기·수정·추가, 정책 변경).
- 신규 제품의 첫 기획·디자인·구현은 기존 Skill(`/product-start`·`/product-design`·`/product-build`)의 단계별 승인 경로를 그대로 씁니다. 이 Skill은 그 경로를 바꾸지 않습니다.
- 기능을 켜지 않은 프로젝트(`enable` 전)는 기존 재개정 경로 그대로입니다.

## 반드시 지킬 규칙

1. **상태 판정과 기록은 스크립트로만 합니다.** `.ai-workflow/change.json`·`state.yaml`·`design.json`·`build.json`을 직접 편집하지 않습니다. 차단(`"ok": false`, 종료 코드 2)을 우회하지 않습니다.
2. **사용자 승인은 두 번입니다: 변경 계약(`approve-contract`)과 최종 통합(`approve-final`).** 두 경우 모두 사용자가 이번 대화에서 한 승인 문장을 **그대로** `--note`로 전달합니다. 단계별 승인 문장을 만들어 내거나, 한 번의 승인 문장을 여러 단계 승인으로 나눠 쓰지 않습니다(각 Skill의 공식 기록은 finalize가 최종 승인 원문과 묶음 digest를 붙여 남깁니다).
3. **계약 밖으로 나가면 멈춥니다.** `check`·디자인 `change verify`·`snapshot-planning`·`snapshot-plan`이 `escalated`/`contract_scope_exceeded`를 내면, 변경을 사용자에게 설명하고 `amend-contract` → 다시 `approve-contract`를 받습니다. 개정된 계약에 이전 승인을 재사용하지 않습니다(엔진이 거부).
4. **영향 분석을 줄이지 않습니다.** `plan`·`open`이 보고한 간접 영향(직접 참조가 없어도 화면·결정·프리뷰 파일을 통해 이어지는 것)과 보수적 확대(`widened`)를 계약에서 빼려면, 바꾸지 않는 이유를 `review --unit <ID> --reason`으로 남깁니다. "직접 참조 없음"은 "영향 없음"이 아닙니다.
5. **기존 미커밋 작업을 보호합니다.** `open`은 열 때의 작업 트리(패키지 전 미커밋 변경)를 스냅샷·백업합니다. `git reset --hard`, `git clean`, 조건 없는 `git restore`·`checkout`으로 되돌리지 않습니다. 되돌릴 때는 `abandon --restore`만 쓰고, 엔진이 안전하지 않다고 하면 멈추고 보고합니다.
6. **공식 빌드·배포 전에는 `gate`를 확인합니다.** 진행 중·finalize 중인 패키지가 있으면 종료 코드 2입니다. 계약 범위 안의 임시 빌드·테스트는 할 수 있습니다.
7. Git staging·commit·push·reset·clean·stash를 실행하지 않습니다. 비밀값과 `.env`를 읽거나 만들지 않습니다.
8. 사용자와의 대화와 산출물은 한국어로 씁니다. ID·파일명·상태값은 영어로 유지합니다.

## 절차

### 0. 사전 점검

`status`를 실행합니다. `change_disabled`이면 `enable`(계획만 보여 줌) → 사용자 동의 문장 → `enable --confirm --note "<원문>"`. 디자인 v2 프로젝트는 디자인 변경 요청 기능도 같은 동의로 켜집니다. **기획 문서를 고치기 전에 켭니다**(기획이 승인본과 다르면 디자인 쪽 기능을 켤 수 없음).

진행 중인 패키지가 있으면(`executing`·`escalated`·`awaiting_final_approval`·`finalizing`) 새 패키지를 열지 않고 `resume --id`로 이어 갑니다. 동시에 하나만 진행합니다.

### 1. 영향 분석(읽기 전용)

1. 사용자 요청을 ID로 옮깁니다. 기획을 이미 고쳤으면 `plan`(승인 기획 대비 현재 차이), 아니면 `plan --ids '{"remove":["AC-164"],"modify":[...]}'`.
2. 결과의 `impact`를 사용자에게 요약합니다: 직접·간접 영향(경로 `path`와 이유 `why`), 영향 화면과 검토 화면(`review_screens`), 디자인 단위, 프리뷰 파일, 배치, 코드 언급, 폐기 ID의 남은 유효 참조(`dangling_refs`)와 이력 참조(`historical_refs`), 보수적 확대(`widened`), 다시 승인할 필요가 없는 단계(`stages_inherited`).

### 2. 변경 계약 → 1차 승인

1. 계약 초안 JSON을 **프로젝트 밖**(예: `temp-dir`)에 씁니다(형식은 `reference/change-package.md` 2절). 목적·정책·바뀌는 ID·유지할 것(keep)·디자인 단위와 화면·재작업/회귀 배치·파일 범위·DB/API·테스트 변경(삭제·수정·추가)·위험 작업·검증 방법을 모두 채웁니다.
2. `open --contract <파일>` → `gaps`가 비어 있지 않으면 계약을 보강해 `amend-contract`(또는 처음이면 다시 `open` 전 수정).
3. `docs/changes/CP-###.md`를 사용자에게 보여 주고 **1차 승인 문장**을 받아 `approve-contract --id CP-### --note "<원문>"`.

### 3. 실행(계약 범위 안)

1. 기획 개정: `/product-start` 규칙대로 문서를 고친 뒤(폐기 ID는 취소선·이력 표기, ID 재사용 금지, 4개 문서 revision 공유) `snapshot-planning --id`. 이후 디자인·구현은 이 제안을 임시 기준으로 진행하며 기존 승인은 무효가 되지 않습니다.
2. 디자인 영향이 있으면 `product_design.py change open --package CP-###` → 계약 범위 안에서 문서·프리뷰 수정 → `change verify --id CR-###`(화면 실측 포함) → `change submit --id CR-###`. 디자인 CR은 따로 승인하지 않습니다(최종 통합 승인으로).
3. 구현 계획을 바꾸면 계획 파일 수정 → `snapshot-plan --id`. 재작업 배치는 `/product-build`의 `batch-start`·구현·`verify`로 진행합니다(검증은 패키지 표식과 함께 기록).
4. 수시로 `check --id`(계약 밖 파일·위험 작업). 영향받았지만 바꾸지 않은 단위는 `review --id --unit --reason`.
5. `regression --id`(구현이 있는 모든 배치 verify).

### 4. 최종 통합 승인 → finalize

1. `submit-final --id` → 묶음(전후 차이·산출물·화면 검증·배치 검증·회귀·바꾸지 않은 영향 단위와 이유) 요약을 사용자에게 보여 줍니다.
2. **2차 승인 문장**을 받아 `approve-final --id --note "<원문>"`. 묶음 digest가 승인 이후 바뀌었으면 거부되고 다시 `submit-final`부터 합니다.
3. 승인 직후 finalize가 자동 실행됩니다(기획 → 디자인 범위 rebase·승인 패치 → 구현 계획·배치 승인 승계). 중간에 멈추면 `resume --id`(멱등). 끝나기 전에는 `gate`가 공식 빌드·배포를 막습니다.

### 취소

`abandon --id --reason`(파일은 그대로) 또는 `abandon --id --reason --restore`(계약 범위 파일만, 안전할 때만 복원; 패키지 전 미커밋 작업과 범위 밖 파일은 보존). 기존 승인 기록은 바뀐 적이 없으므로 그대로입니다.
