# AC 기반 자동 검증 (M2.3)

배치를 구현한 뒤(`implemented`) `verify`가 프로필의 검증 단계를 **직접 실행**해, 테스트 결과로 AC별 증거 수준을 판정합니다. 통과하면 `verified`이고, 아니면 `verify_failed`와 AC별 사유를 남깁니다.

## 1. 테스트 리포트

프로필의 검증 단계에 `report`를 붙입니다.

```toml
[[verify.steps]]
name = "fe-unit"
stage = "test"
run = "pnpm --dir frontend exec vitest run --reporter=junit --outputFile=$PB_REPORT_DIR/fe.xml"
report = { format = "junit-xml", file = "fe.xml" }     # 실행별 폴더($PB_REPORT_DIR) 안 파일(권장)
# report = { format = "junit-xml", path = "frontend/junit.xml" }   # 고정 경로(실행 전후 해시·시각으로 새 파일인지 확인)
optional = false                                        # true면 실패·미실행이어도 배치 검증을 막지 않음(브라우저 검사 등)
requires = []                                           # 필요한 환경. 없으면 not_run(통과로 세지 않음)
```

| 형식 | 내용 |
|---|---|
| `pb-json` | `{"format": "pb-test-report/v1", "tool": "…", "cases": [{"id", "name", "file", "status": "passed\|failed\|error\|skipped", "acs": ["AC-001"]}]}` |
| `junit-xml` | 표준 JUnit XML. `testcase`의 `failure`·`error`·`skipped`, `property name="ac"`를 읽음 |

명령에는 환경 변수 `PB_REPORT_DIR`(실행별 리포트 폴더), `PB_RUN_ID`, `PB_BATCH`가 주어집니다.

## 2. AC 태그(매핑 규칙)

| 방식 | 예 | 프로필 |
|---|---|---|
| 이름 속 대괄호 태그 | `[AC-001] 빈 좌석 표시`, `[AC-006, AC-007]` | 기본(`tag_style = "bracket"`) |
| 리포트의 명시 필드 | pb-json `acs`, JUnit `<property name="ac" value="AC-001"/>` | 항상 |
| 이름 머리 ID 목록 | `SCR-212 / AC-010 / AC-016: …`, `AC-042·071: …`(→ AC-042, AC-071) | `tag_style = "prefix"` |
| 테스트 함수 이름 | `test_ac_010_add_member…`, `test_ac_012_013_guest…` | `tag_style = "pytest_name"` (여러 형식은 목록: `["prefix", "pytest_name"]`) |

- `prefix` 형식은 테스트 이름(마지막 `>` 구간)의 콜론 앞이 **ID 목록으로만** 이루어질 때만 인정합니다. `shows AC-001 in text: …`처럼 문장 속 언급은 인정하지 않습니다.
- 이 밖의 언급(이름·주석·본문)은 **E1(언급)**입니다. E2 이상의 근거가 되지 않습니다.

## 3. 증거 수준

| 수준 | 기준 |
|---|---|
| E0 | 태그도 언급도 없음 |
| E1 | 테스트에 AC ID가 나오지만 태그가 아니거나, 태그된 테스트가 실행되지 않음 |
| **E2** | 태그된 테스트가 **이번 유효한 실행**에서 통과 |
| **E3** | E2 + 같은 테스트가 **이전 유효한 실행에서 다른 코드 버전으로 실패**한 기록(실패→수정→통과) |

- **목표 수준**(계획 승인 때 고정, `ac_targets`)
  - Must는 E2입니다.
  - 보안·권한·데이터 손실 등 위험 태그가 감지된 AC는 E3입니다.
  - Should는 E1입니다.
- **E3를 얻는 방법**
  1. 구현 중에 태그된 테스트를 먼저 쓰고 `verify --batch --lock`(구현 중 확인 실행)으로 실패를 기록합니다.
  2. 구현해서 통과시킵니다.
  - 테스트 이름만 바꾸거나 통과 결과만 있으면 E3가 되지 않습니다.

## 3-1. E3 증거 유형 (M2.4)

통과한 태그 테스트마다 실패→통과 이력의 **유형**을 구분해 기록합니다(`ac-report`의 `evidence`).

| 유형 | 조건 | E3 인정 |
|---|---|---|
| `fix` | 그 테스트의 첫 결과가 실패이고, 테스트(그 함수)는 그대로인 채 **코드가 바뀌어** 통과(테스트 먼저·실제 결함 수정) | 예 |
| `regression_fix` | 통과하던 테스트가 **다른 배치의 실행**에서 실패(회귀 감지)한 뒤, 이전 통과 때와 **다른 코드**로 고쳐 통과 | 예 |
| `fault_injection` | 통과하던 테스트를 **같은 배치**에서 실패시켰다가 다시 통과, 또는 실패 때와 같은 코드로 통과, 또는 회귀 뒤 이전 코드로 되돌림 | 아니요(별도 유형) |
| `test_changed` | 실패와 통과 사이에 그 테스트의 기존 줄이 바뀌거나 지워짐, 또는 skip 같은 약화 표기 추가(줄 추가만은 허용) | 아니요 |

- 정상 코드를 일부러 훼손했다가 복구한 기록은 실제 결함 수정 이력으로 인정하지 않습니다.
- **결함 주입 증거 인정**
  - AC별로 사용자 승인이 있을 때만 그 AC의 목표 E3를 충족한 것으로 봅니다: `accept-fault-injection --batch --ac --note`.
  - 인정되더라도 증거 유형은 계속 `fault_injection`으로 표시됩니다.
- **기존 구현**
  - `adopt-register --batch --note`(사용자 확인)로 이미 있는 코드를 `imported`로 등록하고, E2부터 검증합니다.
  - 목표가 E3인 AC는 `insufficient`이며 "기존 구현: 실패 우선 기록 불가" 안내가 붙습니다.
- **목표 변경**
  - `target --batch --ac --level --reason --note`(사용자 승인 필수)로만 바꿀 수 있습니다. 자동으로 낮추지 않습니다.
  - 원래 목표(`ac_targets`)는 그대로 두고, 변경 이력(`target_overrides`)을 덧붙입니다.
  - 검증된 배치는 재검증이 필요해집니다.

## 4. AC 판정과 배치 판정

| AC 상태 | 뜻 |
|---|---|
| `verified` | 목표 수준 충족 |
| `insufficient` | 통과했지만 목표보다 낮음(예: E2인데 목표 E3) |
| `failing` | 태그된 테스트 실패·오류 |
| `not_run` | 태그된 테스트가 모두 skip이거나, 필수 단계가 실행되지 않거나 결과를 믿을 수 없음 |
| `untested` | 태그된 테스트 없음(E0·E1) |
| `invalid_run` | 실행 중 코드가 바뀌어 실행 자체가 무효 |

**배치 `verified` 조건**(모두 충족)
- 실행이 유효함
- 선택 단계가 아닌 모든 단계가 `passed`
- 목표가 E2 이상인 모든 AC가 `verified`

**검증 단계 상태**

| 상태 | 뜻 |
|---|---|
| `passed`, `failed` | 통과, 실패 |
| `not_run` | 환경 없음 |
| `timeout` | 중단 |
| `report_invalid` | 리포트 미생성·오래됨·재사용 의심·해석 실패 |
| `report_empty` | 케이스 없음 |
| `inconsistent` | 종료 코드는 실패인데 리포트에는 실패가 없음 |

같은 케이스가 여러 번 나오면 가장 나쁜 결과로 봅니다.

## 5. 출처·코드 버전·무효화

**출처**
- 증거는 `verify`가 직접 실행한 단계가 **그 실행 중에** 만든 리포트뿐입니다. 외부 리포트를 가져오는 명령은 없습니다.
- 실행 전후 코드 트리 해시(프로필 source·tests 경로)가 다르면 실행 전체가 무효입니다.

**기록**
- 실행 원본: `.ai-workflow/build/evidence/<배치>/runs/<run_id>/`
  - `run.json`(digest 포함), 리포트 사본, 로그
  - Git에서 제외됩니다.
- `build.json`에 남기는 요약
  - run_id·digest
  - 단계 결과·AC별 판정
  - 코드 트리 해시
  - 배치 범위 해시

**무효화**(`verified` → `stale`, 재검증 필요)

| 원인 | 판정 |
|---|---|
| 검증 이후 배치 범위(allow·shared·배치가 바꾼 파일·그 AC 테스트 파일)의 내용이 바뀜 | `check`가 기록, `status`·의존 배치 시작에서 즉시 반영 |
| 다른 배치의 검증 실행에서 이 배치 AC의 태그 테스트가 실패 | 회귀 |
| 실행 원본(`run.json`)이 없거나 digest가 맞지 않음 | 증거 유실·조작 |

**우회 차단**(`build.json`을 손으로 고친 경우)
- `verified`인데 검증 기록이 없으면 → `invalid_state`, 자동 수정 없음
- 구현 제출 기록 없이 `implemented` 이상이면 → `invalid_state`
- 구현 제출 기록이 없는 배치는 검증할 수 없습니다(`not_implemented`).

## 5-1. 최종 사용자 승인과 영향 분석 (M2.4)

| 단계 | 기록 | 뜻 |
|---|---|---|
| 계획 승인 | `plan.approved` | 사용자가 계획을 승인 |
| 구현 완료 | `implemented`(또는 기존 구현 `imported`) | 코드 제출(검증 아님) |
| AC 검증 완료 | `verified` | **자동 검증 결과**. 사용자 승인이 아님 |
| 최종 사용자 승인 | `approved` + `approvals[]` | `approve batch --batch --note`(검증이 유효하고 선행 배치도 유효할 때만) |

**무효화**
- 검증 이후 다음이 바뀌면 `stale`(재검증 필요)이 됩니다.
  - 배치 범위 코드·테스트
  - 영향을 주는 의존성 파일: 그 파일 디렉터리 아래에 배치 파일이 있거나, 저장소 루트의 파일
  - 증거 원본
  - AC 목표·증거 기준(사용자 승인 변경)
  - 다른 배치 실행에서 감지된 회귀
- **승인 기록은 지우거나 덮어쓰지 않고** `valid: false`와 무효화 사유만 덧붙입니다. 다시 승인하면 새 기록이 추가됩니다.
- 같은 코드로 다시 검증하면 승인이 유지됩니다.

**영향 분석**(`impact`, 읽기 전용)
- 직접 영향 배치(재검증 대상)와 그에 기대는 후속 배치(전이 포함, 차단)를 구분합니다. 영향 없는 배치는 다시 검증하지 않습니다.
- 후속 배치는 직접·간접 선행 배치가 모두 유효해질 때까지 시작·최종 승인이 막힙니다.

## 6. 선행 배치 조건

- 기본 `execution.dependency_min = "verified"`입니다. 선행 배치가 `verified`이고 증거가 유효해야 다음 배치를 시작합니다.
- 의존이 없는 **독립 배치**는 이 조건과 관계없이 시작할 수 있습니다.
- 프로젝트가 원하면 `implemented`로 낮출 수 있습니다(M2.2 동작).

## 7. 실패와 재시도

- 최종 검증이 실패하면 `verify_failed`입니다. `resume --batch Bxx`로 다시 열어 고치고 → `batch-submit` → `verify`.
- 같은 배치의 검증이 연속 `max_retries`회 실패하면 `failed`입니다. 사용자 결정(`resume --retry-failed --note`)이 있어야 재개합니다.
- 검증을 통과시키려고 기존 테스트를 약하게 만들지 않습니다(`batch-submit`이 확인을 요구함).
- Playwright 같은 브라우저 검사는 선택입니다(`optional = true`, `requires = ["playwright"]`). 설치되지 않은 환경에서도 단위·API 테스트만으로 검증할 수 있습니다.

## 8. 명령

| 명령 | 하는 일 |
|---|---|
| `verify --batch B --lock L [--steps a,b] [--available x]` | 구현 중 확인 실행(상태 유지, 실패→통과 이력 기록, 연속 실패 한도) |
| `verify --batch B [--available x]` | 최종 검증(모든 단계) → `verified` / `verify_failed` / 한도 초과 `failed` |
| `ac-report [--batch B]` | AC별 상태·수준·목표·사유·증거 유형, 목표 변경·승인 이력과 증거 유효성(읽기 전용) |
| `impact` | 재검증 대상 배치와 차단되는 후속 배치(읽기 전용) |
| `approve batch --batch B --note` | 최종 사용자 승인(검증과 별개) |
| `adopt-register --batch B --note` | 기존 구현 등록(imported, E2부터 검증) |
| `target --batch B --ac A --level E2 --reason --note` | AC 목표 변경(사용자 승인, 이력 보존) |
| `accept-fault-injection --batch B --ac A --note` | 이 AC에 한해 결함 주입 증거 인정(사용자 승인) |
| `status` | `needs_reverify`(재검증 필요 배치와 이유) |
