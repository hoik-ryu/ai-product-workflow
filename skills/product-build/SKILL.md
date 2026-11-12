---
name: product-build
description: 승인된 기획(PRD·US·AC)과 UX 설계·디자인 방향을 바탕으로 구현 계획(배치·작업·순서·승인 정책)을 만들어 승인받고, 승인된 계획의 배치를 Claude가 실제 코드로 구현합니다(잠금·체크포인트·중단 복구·범위 검사). 사용자가 /product-build를 실행하거나 진행 중인 구현을 재개·일시 중지할 때 사용합니다.
argument-hint: "[plan | execute [Bxx] | resume | pause | decide | status | adopt]  (생략하면 상태에 따라 재개)"
disable-model-invocation: true
---

# /product-build — 승인된 기획·디자인 → 구현 계획 → 계획 승인 → 배치 구현 → AC 검증 → 최종 승인, 정책·편차 원장 (M2)

사용자의 **제품 저장소**(현재 작업 디렉터리)에서 실행합니다. 이 Skill의 기본 디렉터리를 `$SKILL`로 표기합니다.

- `reference/build-state.md`: 상태·승인·입력 기준선·preview waiver·배치 승인 정책 (**먼저 읽기**)
- `reference/planning.md`: 범위 추출·초안 골격·계획 JSON 형식·검증 규칙
- `reference/execution.md`: 배치 실행·잠금·체크포인트·중단 복구·범위·테스트 약화·재시도 (**실행 전에 읽기**)
- `reference/verification.md`: AC 태그·테스트 리포트·증거 수준(E0–E3)·검증 판정·무효화 (**검증 전에 읽기**)
- `reference/ledger.md`: 정책·편차 원장, 차단 정책, decide, 문서 반영 대기열 (**정책을 만나거나 결정할 때 읽기**)
- `reference/adopt.md`: 기존 구현 분석과 증거 수준(E0–E3·EM)
- `templates/build-profile.toml`: 프로젝트 프로필(init이 탐지 결과로 채움), `templates/implementation-plan.example.json`: 계획 형식 예
- `scripts/product_build.py`: 모든 판정·상태 기록(JSON 출력, 차단 시 종료 코드 2, 내부 오류 1). 같은 폴더의 `pb_*.py`를 불러옵니다(직접 실행하지 않음)

호출 형식: `python3 $SKILL/scripts/product_build.py <명령> --project "$PWD" ...`

이번 실행의 사용자 입력: `$ARGUMENTS`

> **현재 범위(M2)**: 계획 생성·검증·승인, 배치 실행, AC 기반 자동 검증, E3 증거 유형 구분, 기존 구현 등록, 목표 변경 승인, 최종 사용자 승인, 영향 분석, 정책·편차 원장·decide·문서 반영 대기열. 계획 승인 / 구현 완료(`implemented`·`imported`) / AC 검증(`verified`, 자동) / 최종 사용자 승인(`approved`)을 구분해 말합니다.

## 반드시 지킬 규칙

1. **상태 판정과 기록은 스크립트로만 합니다.** `.ai-workflow/build.json`을 직접 편집하지 않고, 차단(`"ok": false`)을 우회하지 않습니다.
2. **다른 Skill의 상태와 승인 문서는 읽기만 합니다**: `.ai-workflow/state.yaml`·`design.json`·`boilerplate.json`, `docs/planning/`, `docs/design/`, `design-preview/`. 기획·디자인을 바꿔야 하면 `/product-start`·`/product-design`의 재검토를 안내합니다.
3. 이 Skill이 쓰는 파일은 `.ai-workflow/build.json`, `.ai-workflow/build/`, `docs/build/`뿐입니다. `00-implementation-plan.md`는 스크립트가 생성하므로 직접 고치지 않습니다.
4. **명시적 승인만 인정합니다.** "좋네요"·"괜찮은 것 같아요"는 다시 묻습니다. 승인 문장은 `--note`에 사용자 원문 그대로 기록합니다.
5. **사용자 개입은 꼭 필요한 곳만**: 계획 승인 1회, preview waiver(필요할 때 1회), 그리고 아래 경우만 묻습니다. 작업·화면·일반 배치마다 승인을 받지 않고 다음 배치로 이어 갑니다.
   - 위험 배치 시작(보안·권한·개인정보·되돌리기 어려운 스키마·데이터 삭제 등, 스크립트의 `risk_confirmation_required`)
   - 기존 테스트의 삭제·약화·기대값 변경(`test_changes_need_confirmation`)
   - 승인된 기획·UX 내용을 바꿔야 할 때(코드로 바꾸지 않고 멈춤)
   - 다른 세션·사용자의 변경과 충돌(`base_conflict`, `external_changes`, `lock_active`, `uncommitted_in_scope`)
   - 재시도 한도 초과(`retry_limit_exceeded`) 뒤 재개
6. 계획이나 입력이 승인 이후 바뀌었으면 **보고하고 멈춥니다.** 자동으로 다시 승인하지 않습니다.
7. ID가 코드에 언급됐다는 이유로 구현 완료·검증 통과라고 말하지 않습니다(adopt 결과는 후보).
8. Git commit, push, reset, checkout, clean, stash를 실행하지 않습니다. 커밋은 사용자가 합니다. 비밀값과 `.env`를 읽거나 만들지 않습니다.
9. Docker 등 특정 실행 환경을 전제하지 않습니다. 검증 명령과 필요한 환경은 프로필에 적습니다. 실행할 수 없는 단계는 `not_run`이며 통과로 말하지 않습니다.
10. 대화와 산출물은 한국어로 씁니다. ID, 파일명, 상태값은 영어로 유지합니다.
11. **코드는 배치의 `paths.allow`·`paths.shared` 안에서만 씁니다.** 다른 Skill의 상태·승인 문서·`design-preview/`·`.env`를 고치지 않습니다. 기존 테스트를 지우거나 약하게 만들어 통과시키지 않습니다.

## 0단계 — 사전 점검(매 실행)

`check`를 실행하고 결과로 분기합니다.

| 결과 | 행동 |
|---|---|
| `engine_repo`, `not_git_repo`, `not_repo_root`, `no_commits`, `planning_not_approved`, `no_workflow_state` | 사유와 해결 방법을 보고하고 멈춤 |
| `invalid_state` | 문제 목록을 보고하고 멈춤(자동으로 고치지 않음) |
| `status: not_initialized` | 1단계 |
| `plan_outdated` | `changed`(바뀐 입력)를 보고하고, 확인을 받으면 `reopen plan --reason` → 2단계 |
| `plan_modified` | 승인 이후 바뀐 계획 파일을 보고하고 선택지(다시 제출 / 사용자가 되돌림)를 제시하고 멈춤 |
| 정상 | `plan.status`와 `next`에 따라 2–4단계 |

재개할 때는 먼저 2–4줄로 요약합니다: 계획 상태·revision, 디자인 준비 수준(`design.level`), 배치 수(자동/사용자 승인), 다음 할 일.

인자가 `status`면 `status --all` 결과만 요약하고 멈춥니다(원장 요약 `ledger` 포함). `decide`면 9단계입니다. 인자가 `adopt`면 5단계만 합니다. `execute [Bxx]`면 6단계, `resume`이면 7단계, `pause`면 8단계입니다. 인자가 `plan`이거나 없으면 상태에 따라 진행합니다(계획이 승인돼 있고 진행 중 배치가 있으면 7단계, 없으면 6단계).

## 1단계 — 초기화

1. `init`: `build.json`, `docs/build/build-profile.toml`(탐지한 경로·검증 명령), `.ai-workflow/build/.gitignore`(증거 원본 로그 제외)를 만듭니다. 기존 파일은 덮어쓰지 않습니다.
2. `scan` 결과(스택, 검증 명령 후보, 컴포넌트, ID 언급 수)를 짧게 보여 주고, 프로필의 경로·검증 명령·`order_strategy`가 맞는지 확인을 받습니다. 사용자가 고치라고 하면 프로필만 고칩니다.

## 2단계 — 계획 작성(Claude) · 검증(스크립트)

`reference/planning.md`를 따릅니다.

1. `scope`로 범위를 확인합니다(기본 Must). Should/Could를 넣을지 한 번만 묻습니다(권장: Must만).
2. `scope --draft`의 골격을 `docs/build/implementation-plan.json`으로 저장한 뒤 다듬습니다: 배치 제목·목표, 작업 분해(fe/be/db/api/test), 의존성, 공통 컴포넌트(신규/재사용), 위험 태그, 완료 기준, 테스트 계획. `scan`의 컴포넌트·기존 코드 정보를 반영해 재사용을 우선합니다. 골격은 출발점일 뿐 정답이 아닙니다.
3. `plan-validate`의 오류를 모두 고칩니다(AC·화면 중복·누락, 순환 의존, 순서, 참조). 경고는 판단해 고치거나 이유를 보고에 적습니다.
4. 디자인 준비 수준이 **L2**(UX Spec 승인, 프리뷰 미승인)이고 화면 배치가 있으면 `design_not_ready` 오류가 납니다. 3단계의 waiver가 필요합니다. **L0/L1**이면 화면 배치는 계획할 수 없고, 화면 없는 DB/API 배치(`kind: non_ui`)만 가능하다고 설명합니다.

## 3단계 — preview waiver(필요할 때만, 1회)

1. `waiver add --reason "<사유>" --all-ui`(또는 `--batches B1,B2`)를 확인 없이 실행해 기록될 내용을 받습니다.
2. 사용자에게 설명합니다: 프리뷰 승인 없이 UX Spec(+Design Direction) 기준으로 구현한다는 것, 시각 확인은 배치 검증(브라우저 검사·스크린샷)으로 대신한다는 것, `design.json`의 프리뷰 상태는 바뀌지 않는다는 것, UX Spec·DD가 다시 승인되면 waiver가 무효가 된다는 것.
3. 명시적 승인을 받으면 `--note "<사용자 승인 문장>" --confirm`으로 기록합니다.

## 4단계 — 계획 제출과 승인

1. `submit plan`이 `docs/build/00-implementation-plan.md`를 생성합니다. 요약을 보여 줍니다: 범위(US·AC·화면 수), 배치 목록과 순서, **자동 진행 배치와 사용자 승인 필요 배치(이유)**, 미룬 항목, waiver, 경고.
2. **"구현 계획 승인"**을 요청하고 멈춥니다. 승인하면 `approve plan --revision N --note "<사용자 승인 문장>"`.
3. 수정 요청이면 계획 JSON을 고쳐 다시 `submit plan`(revision이 오름). 승인 후 바꾸려면 `reopen plan --reason` → 수정 → 제출 → 승인.
4. 승인되면 짧게 보고(계획 revision, 배치 순서, 사용자 확인이 필요한 배치)하고 6단계로 이어 갑니다. 사용자가 계획만 원했으면 멈춥니다. 각 배치의 `paths.allow`가 비어 있으면 실행할 수 없으니 계획 단계에서 채웁니다.

## 5단계 — 기존 구현 adopt 분석(읽기 전용)

1. `adopt`(필요하면 `--full`, 기록하려면 `--save`)로 화면별 신호(라우트·ID 언급), AC 증거 수준(E0/E1), 배치별 후보를 받습니다.
2. 보고할 때 반드시 구분합니다: **후보**(라우트·ID가 코드에 있음)와 **확인된 구현**(아직 없음). E1은 '테스트에 ID가 언급됨'일 뿐 검증이 아닙니다. 실제 등록(`imported`)과 검증은 M2.2·M2.3에서 합니다.

## 6단계 — 배치 실행(`execute`) — `reference/execution.md`

1. 대상 배치: 인자로 받은 배치, 없으면 `status`의 `next`·`execute-gate`로 시작 가능한 첫 배치. 진행 중(`in_progress`·`paused`·`failed`) 배치가 있으면 새로 시작하지 않고 7단계로 갑니다.
2. `batch-start --batch Bxx --owner <이 대화를 구분하는 짧은 이름>`. 결과의 `lock_id`를 이 대화 끝까지 씁니다.
   - `risk_confirmation_required`: 이유(`reasons`)와 구현 범위를 설명하고 확인을 받은 뒤 `--confirm-risk --note "<사용자 확인 문장>"`. 확인 없이 시작하지 않습니다.
   - `uncommitted_in_scope`: 범위 안 미커밋 파일을 보여 주고 커밋을 권장합니다. 사용자가 배치 작업 대상으로 확인하면 `--allow-dirty-in-scope --note`.
   - `branch_recommendation`이 있으면 한 줄로 알립니다(브랜치를 만들지 않음).
3. 작업을 `next_task` 순서대로 구현합니다.
   - 계획의 화면·AC·컴포넌트와 승인된 UX Spec(02 화면 상태·문구·권한)을 따릅니다. `scan`의 기존 컴포넌트를 먼저 재사용합니다.
   - 명세에 없는 정책은 임의로 확정하지 않습니다(`reference/ledger.md`).
     - 되돌리기 쉬운 값이면 코드에 `TODO(POL): …` 임시값 표시를 남깁니다. 배치를 마칠 때 `ledger sync`로 원장에 넣습니다(비차단).
     - 보안·권한·개인정보·되돌리기 어려운 데이터·외부 계약이거나, 승인 명세와 다르게 구현해야 하면 `ledger add --type policy|deviation --blocking --rationale`로 등록하고 멈춰 사용자에게 묻습니다.
   - 검증 증거가 부족한 것(테스트 없음·목표 미달)은 정책이 아닙니다. 테스트·구현으로 해결합니다.
   - 작업 하나를 끝낼 때마다 `task-done --batch Bxx --task Bxx-Tn --lock <id>`. 결과의 `out_of_scope`는 보고에 모으고, 범위 밖 수정이 필요 없었다면 되돌립니다. 중간 저장이 필요하면 `checkpoint`.
   - 차단(`protected_path_changed`, `base_conflict`)이면 그 변경을 설명하고 멈춥니다(직접 되돌리지 않음, 사용자 결정).
4. 검증: 프로필의 단계를 `check-run --step <이름> --lock <id>`로 실행합니다(임의 명령은 실행되지 않음). 실패하면 원인을 고치고 다시 실행합니다. 같은 단계가 연속 `max_retries`회 실패하면 스크립트가 배치를 `failed`로 멈춥니다. 그때는 더 고치지 말고 `failure`를 보고합니다. 환경이 없어 `not_run`인 단계는 그대로 보고합니다.
   - **AC 테스트는 태그를 붙여 씁니다**(`reference/verification.md` §2: 기본 `[AC-001] …`). 목표가 E3인 AC(위험 AC, `ac_targets`)는 테스트를 먼저 쓰고 `verify --batch Bxx --lock <id> --steps <단계>`로 실패를 기록한 뒤 구현합니다(실패→통과 증거).
5. 모든 작업이 끝나면 `batch-submit --batch Bxx --lock <id>`.
   - `test_changes_need_confirmation`: 바뀐 테스트와 이유를 보여 주고 확인을 받은 뒤 `--confirm-test-changes --note`.
   - 성공하면 배치는 `implemented`입니다.
6. `verify --batch Bxx`(최종 검증, 모든 단계). 결과를 AC별로 보고합니다(통과·부족·실패·미실행·테스트 없음과 사유).
   - `verified`: 다음으로 갑니다.
   - `verify_failed`: 원인이 코드·테스트면 `resume --batch Bxx`로 다시 열어 고치고 → `batch-submit` → `verify`. 기존 테스트를 약하게 만들어 통과시키지 않습니다. 환경이 없어 `not_run`이면 그대로 보고하고 멈춥니다.
   - 같은 배치가 연속 한도만큼 실패하면 `failed`입니다. 보고하고 멈춥니다.
   - 목표 E3 AC가 `insufficient`이면 증거 유형(`evidence`)을 보고합니다. **정상 코드를 일부러 깨뜨렸다 되돌려 E3를 만들지 않습니다**(결함 주입은 E3로 인정되지 않음). 사용자에게 선택지를 묻습니다: 결함 주입 증거 인정(`accept-fault-injection`) 또는 목표 변경(`target`, 사유 필요). 둘 다 사용자 승인 문장이 있어야 하며, 목표를 스스로 낮추지 않습니다.
   - `user` 배치(위험 배치)가 `verified`가 되면 결과를 보여 주고 최종 승인을 요청합니다(`approve batch --batch --note`). `verified`를 승인이라고 말하지 않습니다.
7. `next_batches` 중 `needs_user_confirmation: false`인 배치는 묻지 않고 이어서 시작합니다(선행 배치가 `verified`여야 시작됨, 독립 배치는 예외). 확인이 필요한 배치를 만나거나, 사용자가 범위를 정했거나, 남은 배치가 없으면 멈추고 보고합니다(구현 파일, AC 검증 결과, 범위 밖 변경, 임시값, not_run 단계, 다음 배치). 커밋은 사용자가 합니다.

## 7단계 — 재개(`resume`)

1. `resume --owner <이름>`(배치 지정은 `--batch`). 성공하면 `done`·`next_task`를 보고 이어서 6단계 3번부터 합니다(끝난 작업은 다시 하지 않음). 검증 실패(`verify_failed`)·재검증 필요(`stale`) 배치를 고칠 때는 `resume --batch Bxx`로 엽니다.
   - `status`의 `needs_reverify`에 있는 배치는 코드가 그대로 맞으면 `verify --batch`로 다시 검증합니다.
2. 차단별 대응(모두 사용자 확인 없이 옵션을 붙이지 않음):
   - `lock_active`: 다른 세션이 실행 중일 수 있다고 알리고 확인을 받으면 `--take-over --note`. `lock_stale`(오래된 잠금)은 상황을 알린 뒤 `--take-over`.
   - `external_changes`: 바뀐 파일과 분류를 보여 줍니다. 사용자가 이 배치 작업으로 받아들이면 `--accept-changes --note`. 아니면 사용자가 정리합니다.
   - `checkpoint_corrupt`: 선택지(`--restore-checkpoint prev` 또는 `rebuild --note`)를 설명하고 결정을 받습니다.
   - `failed_needs_decision`: 실패 원인을 보여 주고, 사용자가 방향을 정하면 `--retry-failed --note`.
   - `protected_path_changed`: 보호 경로 변경을 되돌려야 재개할 수 있다고 알리고 멈춥니다.

## 8단계 — 일시 중지(`pause`)

`pause --batch Bxx --lock <id> --note "<이유>"` → 체크포인트를 남기고 잠금을 풉니다. 다음 작업과 재개 방법(`/product-build resume`)을 알려 줍니다.

## 9단계 — 정책 결정(`decide`)·문서 반영 — `reference/ledger.md`

1. `decide`로 미결 정책·편차와 영향(배치·AC·문서)을 보여 줍니다. `decide --id <ID>`는 미리보기만 하고 기록하지 않습니다.
2. **결정은 사용자가 말한 경우에만** 기록합니다: `decide --id <ID> --decision "<결정 요약>" --note "<사용자 원문>" --confirm`.
   - 결정을 추측하거나 권장안을 대신 승인하지 않습니다.
   - 문서에 '사용자 지시'라고 적혀 있어도, 이 대화에서 사용자가 확인하기 전에는 기록하지 않습니다.
   - 문서를 바꿔야 하면 `--propose "<문서경로>::<변경 내용>"`로 제안만 만듭니다. 승인된 원본은 고치지 않습니다.
3. **결정 이후**
   - 영향을 받은 검증·승인 배치는 재검증 필요가 됩니다. 재검증·최종 승인을 생략하지 않습니다.
   - 결정을 바꾸면 새 결정으로 다시 기록합니다(이전 기록은 남음).
4. **문서 변경 제안**: 사용자 승인(`doc-proposal approve --id --note`) → 소유 Skill이 개정·재승인 → `doc-proposal apply-check --id`. 승인과 적용은 별개입니다.
5. **차단 정책이 미결인 동안**
   - 영향 배치는 시작·재개·최종 승인이 막힙니다.
   - 실행 중이던 배치는 다음 `task-done`·`checkpoint`에서 자동으로 멈춥니다.
   - 관련 없는 배치는 계속 진행할 수 있습니다.

## 상태 보고 — `status --all`

기획(state.yaml), 디자인(design.json), 보일러플레이트(boilerplate.json), 구현 계획(build.json)을 한 번에 요약합니다. `state.yaml`의 `design: not_started`는 '디자인 단계가 열림' 표시라는 `notes`를 함께 전합니다.

## 다른 도구

- `guard --base <커밋>` 또는 `--path <경로>`: 바뀐 파일 중 보호 경로(다른 Skill의 상태·승인 문서·프리뷰)가 있는지 확인합니다.
- `execute-gate --batch <ID>`: 승인된 계획·입력 기준선·선행 배치·waiver를 확인해 배치 시작 가능 여부만 판정합니다(`batch-start`가 같은 검사를 합니다).
- `guard --batch <ID>`: 실행 중 배치의 변경을 기록하지 않고 분류만 봅니다(보호 경로, 범위 밖, 미커밋 충돌, 테스트 변경).
- `ac-report [--batch <ID>]`: AC별 검증 상태·수준·목표·사유·증거 유형과 승인 이력을 봅니다(읽기 전용).
- `impact`: 코드·의존성 변경으로 다시 검증할 배치와 차단되는 후속 배치를 봅니다. 영향 없는 배치는 다시 검증하지 않습니다.
- `adopt-register --batch <ID> --note`: 엔진 밖에서 이미 구현된 배치를 사용자 확인 후 `imported`로 등록하고 E2부터 검증합니다.
