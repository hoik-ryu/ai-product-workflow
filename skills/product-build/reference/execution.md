# 배치 실행 (M2.2)

역할 분리: **Claude가 코드를 씁니다. 스크립트는 상태·범위·잠금·체크포인트·재시도만 판정합니다.**
배치를 끝내면 `implemented`(구현 완료)입니다. 검증 완료(M2.3)나 승인 완료(M2.4)가 아닙니다.

## 1. 흐름

```
batch-start ─▶ [코드 작성 → task-done]×작업 수 ─▶ (check-run: 실패 시 수정·재실행, 연속 한도) ─▶ batch-submit ─▶ 다음 배치
     │               │ checkpoint(선택)                         │ 한도 초과 → failed(잠금 해제)
     │               └─ pause ─▶ paused ─▶ resume ─▶ in_progress
     └─ 잠금(저장소당 1개)·시작 기준선(HEAD + 미커밋 파일 해시)
```

| 명령 | 하는 일 | 주요 차단 |
|---|---|---|
| `batch-start --batch --owner [--confirm-risk --note] [--allow-dirty-in-scope --note]` | 진입 검사(계획 승인·해시·입력 기준선·선행 배치·waiver), 잠금 생성(원자적), 시작 기준선·작업 목록·첫 체크포인트 | `plan_not_approved`, `dependencies_not_ready`, `active_batch_exists`, `lock_held`, `batch_paths_missing`, `risk_confirmation_required`, `uncommitted_in_scope` |
| `task-done --batch --task --lock` | 직전 체크포인트 이후 바뀐 파일을 그 작업에 기록하고 체크포인트를 남김. 이미 끝난 작업은 `already_done` | `lock_mismatch`, `task_deps_pending`, `protected_path_changed`, `base_conflict`, `checkpoint_corrupt` |
| `checkpoint --batch --lock` | 작업 완료 없이 중간 저장 | 위와 같음 |
| `check-run --batch --lock --step [--available docker,…]` | **승인된 프로필의** 검증 단계만 실행(임의 명령 불가). 연속 실패를 세고 `max_retries`회면 `failed`로 멈춤. 필요한 환경이 없으면 `not_run` | `unknown_step`, `plan_modified`, `retry_limit_exceeded` |
| `batch-submit --batch --lock [--confirm-test-changes --note]` | 모든 작업 완료 확인 → `implemented`, 잠금 해제, 다음 배치 제안 | `tasks_pending`, `test_changes_need_confirmation`, 보호 경로·충돌 |
| `pause --batch --lock` | 체크포인트 → `paused`, 잠금 해제 | — |
| `resume [--batch] [--take-over] [--accept-changes] [--retry-failed] [--restore-checkpoint prev\|rebuild] --note` | 잠금·체크포인트·실패·외부 변경을 확인한 뒤 새 잠금으로 재개 | `lock_active`, `lock_stale`, `external_changes`, `checkpoint_corrupt`, `failed_needs_decision` |
| `guard --batch` | 기록 없이 현재 변경 분류만 보기 | — |

## 2. 수정 범위(계획의 `paths`)

- `paths.allow`: 이 배치가 소유하는 경로입니다(새로 만드는 파일 포함).
- `paths.shared`: 명시적으로 허용한 공통 파일입니다(공통 컴포넌트, 라우터 등).
- 패턴 형식은 `dir/`(하위 전체), `*`(한 단계), `**`(여러 단계), 정확한 경로입니다.
- 다음 패턴은 계획 검증에서 거부합니다.
  - 보호 경로(다른 Skill의 상태·승인 문서·프리뷰)
  - `/product-build` 상태 경로
  - 저장소 밖
  - 저장소 전체(`**`)
- `paths.allow`가 없으면 `batch-start`가 거부합니다.

**변경 분류**(시작 이후 바뀐 경로)

| 분류 | 처리 |
|---|---|
| 보호 경로 | **차단.** 기록하지 않습니다. 되돌려야 진행합니다(자동으로 되돌리지 않음) |
| 시작 때 이미 미커밋이던 파일(사용자·다른 세션 작업)이 바뀜 | **차단**(`base_conflict`). 사용자 확인이 필요합니다 |
| 범위 안 | 작업에 기록 |
| 범위 밖 | 기록하고 **보고**(`out_of_scope`). 제출 기록에 남깁니다 |

**범위 안에 미커밋 파일이 있을 때**: 시작할 때 `uncommitted_in_scope`로 알리고 먼저 커밋할 것을 권장합니다. 사용자가 그 파일들을 배치 작업 대상으로 확인하면(`--allow-dirty-in-scope --note`) 충돌로 보지 않습니다.

- **Git**
  - 배치별 브랜치는 권장만 하고 만들지 않습니다(`branch_recommendation`).
  - add·commit·push를 하지 않습니다.
  - 시작 때의 미커밋 파일은 해시로 기록해 보존을 확인합니다.
  - 그중 테스트 파일 내용은 `.ai-workflow/build/runs/<배치>/base/`에 보관합니다. 테스트 약화 판정에 쓰며, Git에서 제외됩니다.

## 3. 기존 테스트 보호

시작 때 있던 테스트 파일(`*.test.*`, `*.spec.*`, `test_*.py`, `*_test.py`, `tests/` 등)의 변경을 분류합니다.

| 분류 | 조건 | 사용자 확인 |
|---|---|---|
| `deleted` | 파일 삭제 | 필요 |
| `weakened` | 추가된 줄에 `skip`·`only`·`xit`·`todo`·`@pytest.mark.skip/xfail`·`@unittest.skip`·`skipTest` 등 | 필요 |
| `modified` | 기존 줄이 바뀌거나 지워짐(기대값 변경 포함) | 필요 |
| `appended` | 줄 추가만 | 불필요 |

`batch-submit`은 확인이 필요한 변경이 있으면 차단합니다. 사용자 확인 문장과 함께(`--confirm-test-changes --note`) 제출하면 그 기록이 남습니다.

## 4. 잠금·체크포인트·중단 복구

**잠금**
- 위치: `.ai-workflow/build/lock.json`
- 내용: lock_id, 배치, owner, pid, host, 생성·갱신 시각
- `O_EXCL`로 만들어 두 세션이 동시에 잡을 수 없습니다.
- 실행 명령은 `--lock <id>`가 일치해야 기록합니다.

**체크포인트**
- 위치: `.ai-workflow/build/runs/<배치>/checkpoint.json`(직전 것은 `checkpoint.prev.json`)
- 내용: 작업 상태, 시작 이후 경로 상태, digest
- `build.json`에 순번·digest 포인터를 둡니다. 이 포인터와 맞지 않으면 손상으로 봅니다.

**재개 절차**(`resume`)

1. **남은 잠금**
   - 갱신이 TTL(`execution.lock_ttl_minutes`) 이내이면 `lock_active`입니다. 넘겨받으려면 `--take-over`와 사용자 확인 문장이 필요합니다.
   - 오래된 잠금은 `lock_stale`이며 `--take-over`가 필요합니다.
   - 어떤 경우에도 자동으로 지우지 않습니다.
   - 아래 검사를 모두 통과한 뒤에만 넘겨받습니다. 그 사이 잠금이 바뀌면 `lock_changed`로 멈춥니다.
2. **체크포인트 손상**
   - `--restore-checkpoint prev`: 직전 체크포인트로 돌아갑니다. 그 이후 변경은 외부 변경으로 보고합니다.
   - `--restore-checkpoint rebuild --note`: 현재 파일을 기준으로 다시 만듭니다. 사용자 확인이 필요합니다.
   - 작업 상태의 기준은 `build.json`입니다.
3. **실패 배치**: `--retry-failed --note`(사용자 결정)로만 재개합니다. 실패한 단계의 연속 실패 수를 0으로 되돌립니다.
4. **마지막 체크포인트 이후 변경**: 보호 경로면 차단합니다. 그 밖에는 `external_changes`로 보고하고, 사용자가 받아들이면 `--accept-changes --note`.
5. **새 잠금·재개**: 끝난 작업은 그대로 두고, 첫 미완료 작업부터 이어 갑니다.

상태 파일·체크포인트는 임시 파일에 쓴 뒤 이름을 바꾸는 방식(원자적)으로만 씁니다.

## 5. 재시도 한도

- `check-run`은 같은 단계의 **연속** 실패를 셉니다. 통과하면 0이 됩니다.
- `execution.max_retries`(1–5, 기본 3)회에 이르면 배치를 `failed`로 멈춥니다. 원인(단계, 종료 코드, 로그 위치, 마지막 출력)과 체크포인트를 기록하고 잠금을 풉니다.
- 사용자 결정 없이 다시 시작할 수 없습니다(무한 재시도 없음).
- 실행 로그는 `.ai-workflow/build/evidence/<배치>/attempts/`에 남깁니다(Git 제외). 이것은 재시도 계산용이며, M2.3의 검증 증거가 아닙니다.

## 6. 선행 배치 조건

- `execution.dependency_min`(M2.3부터 기본 `verified`)입니다. 선행 배치의 필수 AC가 검증되고 그 증거가 유효해야 다음 배치를 시작합니다. 자세한 내용은 `reference/verification.md` §6입니다.
- 의존이 없는 독립 배치는 그대로 시작할 수 있습니다.
- `implemented`로 낮추면 M2.2처럼 구현 완료만으로 이어 갑니다.
