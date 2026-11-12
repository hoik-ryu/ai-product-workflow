# LLM 회귀 하네스(장시간)

`/product-start`·`/product-init`은 판정과 상태 기록 일부를 LLM(Skill 지시문)이 맡으므로, 실제 `claude -p`로 대화를 이어 가며 검증합니다. 스크립트 단위 테스트(`tests/*_test.py`)와 달리 **시간과 모델 비용**이 들고 결과가 실행마다 조금씩 다를 수 있습니다. 판정은 모델 문장이 아니라 상태 파일·해시·파일 비교 출력으로만 합니다(`summarize.py`).

## `/product-start` S01–S19 (`product_start/`)

```bash
tests/harness/product_start/run_regression.sh [작업 폴더]   # 약 30–40분
```

- 필요: `claude`(로그인), `expect`(S19 대화형), `git`, `python3`. 엔진 경로는 스크립트 위치에서 계산합니다(`ENGINE`).
- 임시 폴더에 제품 저장소 여러 개를 만들고 시나리오를 실행한 뒤 `summarize.py`가 `tests/scenarios.md`의 기대 결과로 판정합니다.
- 판정기 검증: 이전 실행 로그 4개로 확인했습니다. 3개는 19/19, 1개(2026-11-10 M1-4 검증 실행)는 **S07 미통과**였습니다.
  - 그 실행은 S07 픽스처 생성 결함(아래) 때문에 모델이 손상된 상태를 감지하고 멈춘 경우라, S07이 의도한 '재개 생성'을 검증하지 못했습니다.
  - 일부러 변조한 로그에서는 해당 항목을 FAIL로 판정했습니다.
- 픽스처 결함 수정: S07은 S06 결과의 `state.yaml`을 고쳐 만듭니다. `artifacts_done: []` 줄 끝 주석이 경로에 붙어 YAML이 깨질 수 있어, 줄 전체를 바꾸도록 고쳤습니다(`run_all.sh` PHASE C).

## `/product-init` K1–K10 (`product_init/`)

```bash
BOILERPLATE_SRC=<보일러플레이트 Git URL> tests/harness/product_init/run_k.sh [작업 폴더]
```

- 필요: `claude`, 네트워크(보일러플레이트 저장소의 `boilerplate.manifest.toml`과 `v1.0.0` 태그), **Docker 실행 중**(K7의 db·smoke), `git`, `python3`.
- 픽스처는 `tests/product_init_test.py`의 `make_product`를 씁니다(승인 / 미승인 제품 저장소). 실행 뒤 검증용 Docker 볼륨을 `cleanup --remove-volumes --confirm`으로 정리합니다(이 하네스가 만든 검증 전용 볼륨만).
- 판정기 검증: 이전 실행의 전체 로그로 K1–K8·K10을 확인했습니다. K9 판정 줄(엔진 `check`의 `user_modified`)은 이번에 새로 넣어 실제 실행 로그로는 아직 확인하지 못했습니다.
- **이 하네스는 보존 후 아직 실행하지 않았습니다**(2026-11-10 기준 Docker 꺼짐). 실행 전에는 검증되었다고 보지 않습니다.

## `/product-build` P1–P5 (`product_build/`)

```bash
tests/harness/product_build/run_regression.sh [작업 폴더]   # 약 10–15분
```

- 필요: `claude`(로그인), `git`, `python3`. Docker·네트워크 의존 없음(픽스처는 Python 코드와 unittest).
- 의원 진료 예약 픽스처(프리뷰 승인 L3, 계획 제출 상태)에서 계획 승인 → 배치 실행 → AC 검증(M2.3, pb-json 리포트) → 위험 배치 정지 → 중단·재개 → 차단 정책·decide(P6–P7)를 실제 대화로 확인합니다. 시나리오는 `tests/build-scenarios.md`.
- 판정(`summarize.py`)은 상태·잠금·작업 기록·Git·단위 테스트로만 합니다. 허용 명령에 `git commit`은 없습니다.

## 빠른 테스트(스크립트 단위)

```bash
python3 tests/product_design_test.py          # /product-design 기본(v1)
python3 tests/product_design_impact_test.py   # WF-D01
python3 tests/product_design_v2_test.py       # WF-D05(v1 명령 29개 비교 포함)
python3 tests/product_design_dd_test.py       # WF-D02
python3 tests/product_design_theme_test.py    # WF-D03·D04 (PD_FULL=1이면 프리뷰 빌드·승인 포함)
python3 tests/product_init_test.py            # /product-init 스크립트
python3 tests/product_build_test.py           # /product-build 계획(M2.1)
python3 tests/product_build_exec_test.py      # /product-build 배치 실행(M2.2)
python3 tests/product_build_verify_test.py    # /product-build AC 기반 자동 검증(M2.3)
python3 tests/product_build_approval_test.py  # /product-build 증거 정책·최종 승인·영향 분석(M2.4)
python3 tests/product_build_ledger_test.py    # /product-build 정책·편차 원장·decide·문서 반영(M2.4b)
```
