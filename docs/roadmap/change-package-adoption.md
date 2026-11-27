# 변경 패키지(/product-change) — 기존 프로젝트 적용 절차

M1 변경 요청 적용 절차(`m1-change-request-adoption.md`)를 이어서 씁니다. 모든 단계는 **제품 프로젝트 복제본에서 먼저 리허설**하고, 원본에는 사용자가 직접 확인한 뒤 적용합니다. 이 문서의 명령은 검토·테스트한 뒤 사용하세요. 운영 환경에 바로 적용하지 마세요.

## 0. 무엇이 바뀌고 무엇이 그대로인가

- 켜기 전에는 아무것도 바뀌지 않습니다. 기존 `state.yaml`·`design.json`·`build.json`의 승인 기록·해시는 켠 뒤에도 고쳐 쓰지 않습니다(덧붙이기만).
- 켜면 `.ai-workflow/change.json`이 생기고, 디자인 v2 프로젝트는 디자인 변경 요청 기능(`config.changes`)이 같은 동의 문장으로 켜집니다.

## 1. 켜기 전 확인

Skill 연결(개인 설정, Git 제외): 다른 Skill과 같은 엔진 경로로 `ln -s "$ENGINE/skills/product-change" .claude/skills/product-change`. 링크가 없어도 스크립트를 경로로 실행할 수는 있지만 `/product-change` 명령과 Skill 안내를 쓰려면 연결합니다.

```bash
python3 $ENGINE/skills/product-change/scripts/product_change.py enable --project .   # 계획만(쓰지 않음)
```

- `transition_in_progress`: 제출·승인 대기 단계, 진행 중 디자인 CR·배치가 있으면 켜지 않습니다. 먼저 정리합니다.
- **기획 문서를 고치기 전에 켭니다.** 기획이 승인본과 다르면 디자인 쪽 기능을 켤 수 없습니다(`design_enable_failed` + 안내). 이미 고쳤다면 `/product-start`로 제출(awaiting_approval)한 뒤 패키지를 adopt 모드로 엽니다.
- 사용자 동의 문장을 받아 `enable --confirm --note "<원문>"`.

## 2. 첫 패키지(권장: 복제본 리허설)

```bash
PC=$ENGINE/skills/product-change/scripts/product_change.py
python3 $PC plan --project .                        # 기획을 고친 뒤: 승인본 대비 ID 차이와 영향
python3 $PC open --project . --contract /tmp/.../CP.json
python3 $PC approve-contract --project . --id CP-001 --note "<사용자 1차 승인 원문>"
python3 $PC snapshot-planning --project . --id CP-001
python3 $PC gate --project .                        # 진행 중에는 종료 2(공식 빌드·배포 차단)
```

이후 절차는 `skills/product-change/SKILL.md` 3–4절입니다.

## 3. SMAPSH 사본 리허설 결과(2026-11-26, 엔진 작업 중 확인)

복제본(기준 6040a51, 기획 문서만 r14 내용으로 교체)에서 실제 r14 변경(AC-164 폐기)을 돌렸습니다. 원본 저장소는 건드리지 않았습니다.

| 확인 | 결과 |
|---|---|
| 기획 ID 차이 | modified AC-160·AC-165·C-37·C-38·NFR-003·US-015, removed AC-164·FLOW-005-S7d |
| 간접 영향 사슬 | AC-160/AC-164 → 02 SCR-112·SCR-226 → VD-084·VD-085 → `SCR-226.tsx`·`SCR-112.tsx`·`RoundLive.tsx` 탐지 |
| 영향 범위 | 영향 화면 9, 검토 화면 5(공용 VD 한 단계), 배치 B2·B6·B11·B15·B17, 폐기 ID 유효 참조 10건 |
| 계약 → 승인 | 공백 0, `approve-contract` 통과 |
| snapshot-planning 후 | 디자인 4단계 승인 유지(outdated 아님), 구현 계획 valid, `gate` 종료 2 |
| 디자인 패키지 CR | 범위 안 수정(추적·흐름 행 폐기 표기, SCR-226-ST9) 통과 / 같은 흐름 블록의 다른 행 수정은 `contract_scope_exceeded` |
| `abandon --restore` | 디자인 수정 3파일만 복원, 패키지 전 기획 수정본은 바이트 동일 유지, 무관한 미추적 파일 보존, 게이트 해제 |

리허설 중 실제 데이터로 찾아 고친 엔진 결함: 긴 표 행 본문 속 '폐기' 단어를 폐기로 오판(NFR-003), 화면 블록 안 링크로 화면이 연쇄 확대(25화면 → 9+5), 메모 문서(`docs/workflow-proposals/`)를 코드 영향으로 계산, `enable`의 디자인 v2 판정 키 오류, 허용 하위 행 수정을 상위 흐름 블록 변경으로 오판.

전체 finalize(재작업 배치 구현 포함)는 실제 구현 작업이 필요해 사본에서는 하지 않았고, 픽스처(`tests/product_change_test.py`)에서 끝까지 검증했습니다.

## 4. 복원

- 패키지 취소: `abandon --id --reason [--restore]`. 기존 승인 기록은 바뀐 적이 없습니다.
- 기능 끄기: 진행 중 패키지가 없을 때 `.ai-workflow/change.json`을 사용자가 직접 보관·삭제합니다(엔진은 지우지 않음). 디자인 변경 요청 기능은 `product_design.py change disable` 절차를 따릅니다.
- `git reset --hard`·`git clean`·조건 없는 `git restore`는 쓰지 않습니다.
