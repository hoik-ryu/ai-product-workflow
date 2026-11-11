# M1 안정화 인수인계 (2026-11-10 → 다음 작업일)

상태: **미커밋**(commit·push 하지 않음). 새 기능(M2/M3)은 시작하지 않았습니다.

> **2026-11-11 갱신**: `/product-start` 전체 회귀(reg12)를 수정한 하네스로 1회 실행해 **19/19 Pass**(S07 Pass 포함). 결과는 `tests/design-scenarios.md` 끝 기록 참고. 아래 3·5절의 `/product-start` 항목은 완료되었고, `/product-init` K1–K10만 미실행으로 남았습니다.

## 1. 오늘 한 일 (M1 안정화 변경)

| 구분 | 파일 | 내용 |
|---|---|---|
| 모듈 분리 | `skills/product-design/scripts/product_design.py` (813줄) | CLI 진입점만 남김(`cmd_*`, `JsonArgParser`, `main` 등) |
| | `skills/product-design/scripts/pd_core.py` (1,564줄, 신규) | 상태·승인·해시·공통 검증 |
| | `skills/product-design/scripts/pd_theme.py` (292줄, 신규) | 테마·렌더러 계약, `preview_check` |
| | `skills/product-design/scripts/pd_impact.py` (445줄, 신규) | 변경 영향 분류 |
| 하네스 보존 | `tests/harness/product_start/` (신규) | S01–S19 회귀 하네스 + `run_regression.sh`, `summarize.py`(자동 판정) |
| | `tests/harness/product_init/` (신규) | K1–K10 하네스(`run_k.sh`, `mk.py`, `summarize.py`) |
| | `tests/harness/README.md` (신규) | 사용법·요구 사항·검증 상태 |
| 문서 | `README.md`, `docs/architecture.md`, `skills/product-design/SKILL.md`, `tests/scenarios.md` | 모듈·하네스 안내 줄 추가 |
| 기록 | `tests/design-scenarios.md` | 안정화 기록 추가(끝에 덧붙임, 기존 줄 유지) |

- 분리 방식: AST로 함수 원문을 그대로 옮겼습니다(최상위 정의 196개가 분리 전후 같고, 원문도 같음). 로직은 바꾸지 않았습니다.
- 가져오기 순서: `pd_core` ← `pd_theme` ← `pd_impact` ← CLI. 모두 star import이고 `__all__`을 씁니다.
- 실행 방식: `python3 -I`(격리 모드)를 유지합니다. CLI가 자기 폴더를 `sys.path`에 넣고 `sys.dont_write_bytecode = True`로 바이트코드 생성을 막습니다.
- 그 밖에 WF-D01~D04 작업도 아직 미커밋입니다. 목록은 `git status`로 확인합니다.

## 2. 통과한 테스트 (오늘, 분리 후 코드 기준)

| 테스트 | 결과 |
|---|---|
| `python3 tests/product_design_test.py` | 120/120 |
| `python3 tests/product_design_impact_test.py` (WF-D01) | 62/62 |
| `python3 tests/product_design_v2_test.py` (WF-D05, v1 명령 29개 비교, v2 마이그레이션·승인 해시 보호 포함) | 56/56 |
| `python3 tests/product_design_dd_test.py` (WF-D02) | 61/61 |
| `PD_FULL=1 python3 tests/product_design_theme_test.py` (WF-D03·D04) | 40/40 |
| `python3 tests/product_init_test.py` | 48/48 (Docker 꺼짐) |
| 분리 전/후 동등성(명령 54개: 출력·종료 코드·최종 `design.json`) | 일치 |
| 심볼릭 링크로 설치한 Skill, 다른 cwd에서 `-I` 실행 | 정상, `__pycache__` 없음 |
| `/product-start` 회귀 reg11, 중단 전까지 진행분 | 아래 3절 참고 |

## 3. 미완료 테스트

### `/product-start` 회귀 S01–S19 (reg11) — 중단함

- 퇴근 전에 PHASE C 진행 중 SIGTERM으로 직접 종료했습니다(종료 코드 143).
  - 이 실행은 VSCode의 Claude Code 프로세스 아래에서 돌았습니다. 맥북이 잠자기 상태가 되면 일시 정지되고, VSCode나 터미널을 닫으면 함께 종료됩니다.
- 중단 시점까지 `summarize.py` 판정은 다음과 같습니다(부분 로그라 "RESULT 9/19"로 나옴).

| 판정 | 시나리오 |
|---|---|
| 완료·PASS | S01, S02, S03, S04, S05, S06, S08, S10 |
| 부분 PASS | S15: PHASE B 산출물(main)의 추적성만 확인. S07 이후 산출물 trace는 미실행 |
| 미실행(FAIL로 표시되나 실패 아님) | S07, S09, S12(PHASE C 진행 중 중단), S11, S13, S14, S16, S17, S18, S19 |

- 하네스는 단계(PHASE A–F)가 앞 단계의 저장소와 세션 ID에 의존하므로 **중간부터 재개할 수 없습니다**.
  - 내일은 처음부터 한 번 전체 실행해야 합니다(S01–S06·S08·S10도 다시 실행됨).
  - 중간 재개 기능은 하네스 기능 추가이므로 승인 없이 만들지 않았습니다.

### `/product-init` K1–K10 — 미실행

- Docker가 꺼져 있습니다(K7 db·smoke 필요). `BOILERPLATE_SRC`(보일러플레이트 Git URL)와 네트워크도 필요합니다.
- K9 판정 줄(엔진 `check`의 `user_modified`)은 실제 실행 로그로 아직 확인하지 못했습니다.
- 이 하네스는 보존만 했고 **검증되었다고 보지 않습니다**.

## 4. reg10 S07 정정 (18/19)

- `tests/design-scenarios.md`의 "2026-11-10 (WF-D03·D04, M1 완료 검증)" 표에는 `/product-start` 회귀가 **19/19**로 적혀 있습니다. 실제 판정은 **18/19, S07 미검증**입니다.
- 원인은 하네스 픽스처 결함입니다.
  - S07 픽스처는 `state.yaml`의 `artifacts_done: []`를 정규식으로 바꿉니다. 이때 줄 끝 주석이 경로 뒤에 붙어 YAML이 깨졌습니다.
  - 모델은 손상된 상태를 올바르게 감지하고 멈췄습니다. 따라서 S07이 의도한 '중단 후 재개 생성'은 검증되지 않았습니다.
  - 엔진 결함이 아닙니다.
- 사람이 읽고 판정할 때 이 점을 놓쳤고, `summarize.py`(자동 판정)를 만든 뒤 과거 로그를 다시 판정하다 발견했습니다.
  - reg7·reg8·reg9는 19/19, reg10은 18/19였습니다.
- 수정: `tests/harness/product_start/run_all.sh` PHASE C의 정규식을 줄 끝 주석까지 바꾸도록 고쳤습니다.
- **수정한 픽스처로 S07을 통과한 실행은 아직 없습니다**(reg11은 S07 도중 중단).

## 5. 내일 실행할 명령

```bash
cd ~/Desktop/ai-product-workflow

# 0) 상태 확인 (변경이 오늘과 같은지)
git status --short

# 1) 빠른 테스트 (수 분)
python3 tests/product_design_test.py
python3 tests/product_design_impact_test.py
python3 tests/product_design_v2_test.py
python3 tests/product_design_dd_test.py
python3 tests/product_init_test.py

# 2) 장시간 테스트 — 각 1회만. 실행 중 잠자기 방지(caffeinate). 노트북을 닫지 말고 전원 연결
caffeinate -dims env PD_FULL=1 python3 tests/product_design_theme_test.py
caffeinate -dims tests/harness/product_start/run_regression.sh ~/Desktop/ai-product-workflow-test-logs/reg12   # 약 30–40분

#    판정만 다시 보려면
python3 -I tests/harness/product_start/summarize.py ~/Desktop/ai-product-workflow-test-logs/reg12/all.log

# 3) (선택) Docker를 켠 경우에만
BOILERPLATE_SRC=<보일러플레이트 Git URL> caffeinate -dims tests/harness/product_init/run_k.sh ~/Desktop/ai-product-workflow-test-logs/k1
```

- 작업 폴더는 `/private/tmp` 대신 위처럼 영구 위치를 쓰는 것이 안전합니다.
- 회귀가 끝나면 다음을 정리합니다.
  1. `tests/design-scenarios.md` 안정화 기록의 미완료 칸을 결과로 채웁니다.
  2. 이 문서 3절을 갱신합니다.
  3. 위생 점검을 합니다: 개인 경로 grep, `__pycache__` 없음, product-start·init 변경 없음, badminton-playbook `git status`(기존 사용자 변경 4줄).
  4. commit 여부를 결정합니다.

## 6. 확인할 파일

| 파일 | 용도 |
|---|---|
| `~/Desktop/ai-product-workflow-test-logs/2026-11-10/reg11/all.log` | 오늘 중단된 회귀 로그(PHASE A·B 완료, PHASE C 중단) |
| `~/Desktop/ai-product-workflow-test-logs/2026-11-10/reg11.out` | 실행 래퍼 출력 |
| `~/Desktop/ai-product-workflow-test-logs/2026-11-10/reg10/all.log` | S07 정정 근거(18/19) |
| `~/Desktop/ai-product-workflow-test-logs/2026-11-10/reg7`~`reg9` | 판정기 검증용 과거 로그(19/19) |
| `~/Desktop/ai-product-workflow-test-logs/2026-11-10/old_k_full.log` | `/product-init` K1–K10 과거 전체 로그(판정기 검증용) |
| `~/Desktop/ai-product-workflow-test-logs/2026-11-10/split/` | 분리 전 원본(`product_design.monolith.py`)과 동등성 비교 스크립트 |
| `tests/harness/README.md` | 하네스 사용법·검증 상태 |
| `tests/design-scenarios.md` (끝 부분) | M1 안정화 기록 |

- 로그 폴더는 저장소 밖에 있어 Git에 들어가지 않습니다. 로그에는 모델 응답 원문과 임시 경로가 들어 있으므로 외부에 공유하기 전에 확인합니다.
- 원래 위치(`/private/tmp/claude-501/.../scratchpad/`)는 재부팅하거나 세션이 끝나면 사라질 수 있습니다.

## 7. 남은 위험

- **star import**: 세 모듈이 이름 공간을 공유합니다. 같은 이름을 다른 모듈에 새로 정의하면 조용히 가려질 수 있습니다. 분리 자체는 중복 정의 0으로 확인했습니다.
- **LLM 변동**: `/product-start` 회귀는 실행마다 결과가 조금씩 다를 수 있습니다. 판정은 상태·해시 출력으로만 합니다.
- **하네스 재개 불가**: 하네스가 중간부터 재개되지 않아, 중단되면 처음부터 다시 실행해야 합니다.
- **K7 미검증**: Docker 의존인 K7과 새 K9 판정 줄은 아직 실제 실행으로 확인하지 않았습니다.
- 생성된 스크립트·설정은 사람이 검토하고 테스트한 뒤 사용합니다. 운영 환경에 바로 적용하지 않습니다.
