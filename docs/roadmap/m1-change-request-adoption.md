# 변경 요청·승인 패치(M1) — 기존 프로젝트 적용 절차

이미 승인·구현이 진행된 제품 프로젝트에 M1 엔진(커밋 `34e6972` 이후)을 적용하는 절차입니다. 규칙은 `skills/product-design/reference/change-request.md`에 있습니다.

> 이 문서의 명령은 예시입니다. 실제 프로젝트에 적용하기 전에 검토하고, 먼저 프로젝트 복제본에서 리허설하는 것을 권장합니다. 승인 문장(`--note`)은 사용자가 실제로 한 말만 넣습니다.

## 0. 무엇이 바뀌고 무엇이 그대로인가

| 구분 | 기능을 켜지 않은 프로젝트(`config.changes` 없음) |
|---|---|
| 승인 상태·해시·revision·history | **그대로**. 엔진 업데이트만으로는 상태 파일을 쓰지 않습니다 |
| `product_design.py status`·`check` 출력 | 기존과 같음(`changes` 키 없음) |
| `/product-build` 계획 입력 기준선 | 기존과 같음(패치 목록은 기능을 켠 뒤에만 기록) |
| 새로 적용되는 안전장치 | 상태 파일 저장 잠금(`.ai-workflow/.design.lock`, 저장 순간에만 존재), 읽은 뒤 바뀐 파일 덮어쓰기 거부(`state_conflict`), 중복 키 거부(`state_duplicate_keys`), 병합 충돌 표시 안내 |
| 고쳐진 기존 버그 | 승인된 프리뷰의 바이너리(PNG 등)가 바뀌었을 때 `check`가 `UnicodeDecodeError`로 멈추던 문제 |
| 새 Build 검증 기록 | 이후 `verify` 기록에 `design_amendments`(그 시점 패치 수, 기능 꺼짐이면 0) 필드가 붙음. 기존 기록은 고치지 않음 |

엔진 저장소 리허설(구 엔진 `3bf6107`이 만든 v2 + DD + Preview + Build 계획 승인 프로젝트)에서 확인한 결과:
- 업데이트 전후 `state.yaml`·`design.json`·`build.json` 바이트 동일
- `status`의 승인·Build 의미 필드(`overall`·`stages`·`validity`·`cross_verify`, `build`·`design_level`·`needs_reverify`·`ledger`) 동일
- 새 엔진 `check`도 아무것도 쓰지 않음(Build 계획 approved r1, 디자인 L3 유지)

## 1. 업데이트 전 준비(제품 프로젝트에서)

```bash
cd <제품 프로젝트>
git status --short                     # 비어 있어야 함(승인 상태를 먼저 커밋)
OLD=<현재 쓰는 엔진 경로>               # 예: 업데이트 전 엔진 체크아웃
E=$(mktemp -d)                         # 증거 폴더(저장소 밖)
shasum -a 256 .ai-workflow/state.yaml .ai-workflow/design.json .ai-workflow/build.json .ai-workflow/build/ledger.json 2>/dev/null > "$E/before.sha"
python3 "$OLD/skills/product-design/scripts/product_design.py" status --project "$PWD" > "$E/before-design.json"
python3 "$OLD/skills/product-build/scripts/product_build.py"   status --project "$PWD" > "$E/before-build.json"
git rev-parse HEAD > "$E/project-head.txt"
```

- `status`는 읽기 전용입니다. `check`는 outdated·stale을 기록할 수 있으므로 기준선에는 쓰지 않습니다.
- 진행 중인 Build 배치(잠금)가 있으면 끝낸 뒤 업데이트합니다.

## 2. 엔진 업데이트

```bash
cd <엔진 저장소>
git rev-parse HEAD > "$E/engine-before.txt"   # 복원용
git pull                                      # 또는 git checkout <M1 이후 커밋>
```

설치 방식(심볼릭 링크·프로젝트 설정)은 README의 설치 절을 따릅니다. 링크를 쓰면 엔진 체크아웃만 바꾸면 됩니다.

## 3. 업데이트 후 상태 유지 확인

```bash
cd <제품 프로젝트>
NEW=<엔진 저장소>
python3 "$NEW/skills/product-design/scripts/product_design.py" status --project "$PWD" > "$E/after-design.json"
python3 "$NEW/skills/product-build/scripts/product_build.py"   status --project "$PWD" > "$E/after-build.json"
shasum -a 256 -c "$E/before.sha"              # 모두 OK여야 함
python3 - "$E" <<'PY'
import json, sys
E = sys.argv[1]
L = lambda n: json.load(open(f"{E}/{n}"))
d0, d1 = L("before-design.json"), L("after-design.json")
pick = lambda d: {"overall": d.get("overall"), "stages": d.get("stages"), "validity": d.get("validity"),
                  "consistent": d["cross_verify"]["consistent"], "problems": d["cross_verify"]["problems"]}
b0, b1 = L("before-build.json"), L("after-build.json")
K = ("build", "design_level", "design_reason", "needs_reverify", "ledger")
print("design:", "SAME" if pick(d0) == pick(d1) else "DIFF")
print("build :", {k: ("SAME" if b0.get(k) == b1.get(k) else "DIFF") for k in K})
print("changes 키(꺼진 상태면 없어야 함):", "changes" in d1)
PY
python3 "$NEW/skills/product-design/scripts/product_design.py" check --project "$PWD"   # 종료 0
python3 "$NEW/skills/product-build/scripts/product_build.py"   check --project "$PWD"   # 계획 상태가 그대로여야 함
shasum -a 256 -c "$E/before.sha" && git status --short   # check 뒤에도 OK, 작업 트리 깨끗
```

- 하나라도 DIFF이거나 `check`가 상태 파일을 바꿨다면 아래 §7로 복원하고 원인을 확인합니다(기능을 켜지 않습니다).
- Build `status`에는 배치 상태(`build.batches`)와 계획(`build.plan`)이 들어 있어 Build 상태 유지 여부를 함께 확인합니다.

## 4. 기능 활성화(선택, 기존 승인 기록 유지)

조건: 워크플로 v2, `check` 문제 없음, planning outdated 아님. v1 프로젝트는 대상이 아닙니다(`changes_requires_v2`, 필요하면 먼저 사용자 승인으로 `migrate --to v2`).

```bash
PD="python3 $NEW/skills/product-design/scripts/product_design.py"
$PD change enable --project "$PWD"                                      # dry-run: 추가할 필드·백업 여부만 출력
$PD change enable --project "$PWD" --confirm --note "<사용자 동의 문장>"
$PD check --project "$PWD"     # changes.effective_status가 모두 approved, head.count 0
python3 "$NEW/skills/product-build/scripts/product_build.py" check --project "$PWD"   # 계획 유지
git diff --stat                # .ai-workflow/design.json만 바뀌어야 함(config.changes·changes 추가, history 1줄)
```

- `enable`은 **추가만** 합니다. 쓰기 전후 기존 필드 비교(`_preserved`)로 하나라도 바뀌면 원래 바이트로 되돌립니다.
- 상태 파일이 Git 추적·clean이 아니면 `.ai-workflow/backup/design/design.json.pre-changes`에 백업합니다.
- 화면 검증 산출물(`.ai-workflow/changes/<CR>/runs/`)은 TEMP입니다. 프로젝트 `.gitignore`에 `.ai-workflow/changes/*/runs/`를 추가합니다(권장 블록 `docs/policies/gitignore.recommended` v1을 이미 넣은 프로젝트는 이 한 줄만 덧붙임). 요약·해시는 design.json에 남습니다.
- 결과를 확인한 뒤 사용자가 커밋합니다.

## 5. 측정 어댑터(CDP) 업데이트와 재확인 — Type B 영향 화면 실측용

Type B가 프리뷰 파일을 바꾸면 `change verify`가 영향 화면을 실제 브라우저로 측정합니다. 이전 어댑터에는 이미지 측정(`images`)이 없어, 이미지가 바뀐 검증은 `images_not_measured`로 막힙니다.

```bash
diff tools/pd-measure/pd-measure-cdp.mjs "$NEW/skills/product-design/templates/measure-adapters/chrome-cdp/pd-measure-cdp.mjs"   # 변경 내용 검토
cp "$NEW/skills/product-design/templates/measure-adapters/chrome-cdp/pd-measure-cdp.mjs" tools/pd-measure/pd-measure-cdp.mjs
# 파일이 바뀌어 측정 명령 지문이 달라졌으므로, 확인 전에는 측정을 실행하지 않습니다(measure_cmd_unconfirmed / not_run)
$PD explore-config --project "$PWD" --measure-cmd "node --experimental-websocket tools/pd-measure/pd-measure-cdp.mjs"            # dry-run: 새 지문
$PD explore-config --project "$PWD" --measure-cmd "node --experimental-websocket tools/pd-measure/pd-measure-cdp.mjs" --confirm --note "<사용자 확인 문장>"
```

- 필요 조건: Chrome·Chromium(`CHROME_PATH` 지정 가능), Node 22 이상(Node 20.10 이상은 `--experimental-websocket`), 프리뷰 `node_modules`(프리뷰 빌드 1회).
- **탐색 설정(`config.exploration`)이 없는 v2 프로젝트**(예: `migrate --to v2`로만 전환)는 측정 명령을 바로 등록할 수 없습니다(`exploration_disabled`). M1에는 전용 명령이 없으므로 다음 중 하나를 택합니다(사용자 결정).
  - 기존 명령으로 설정 만들기: `explore-config --enable structure --confirm --note …` → `explore-config --disable structure --confirm --note …` → 위 `--measure-cmd` 등록. 탐색 조건은 다음 재검토(reopen) 이후 제출에만 적용되고, 바로 끄므로 실제 영향은 없습니다. 사용자 문장이 세 번 필요합니다.
  - 측정 없이 진행: `change verify --screen-waiver "<사용자 문장>"`. 결과는 검증 완료가 아니라 `waived`로 기록됩니다.

## 6. 적용 후 첫 Type B 리허설(권장, 프로젝트 복제본에서)

```bash
$PD change plan --project "$PWD" --request <프로젝트 밖 요청 JSON>        # 읽기 전용: 유형·영향 화면·필요한 승인·검증
# 실제 진행은 skills/product-design/SKILL.md 5-1단계(open → 수정 → verify → submit → 사용자 최종 확인 → approve)
python3 "$NEW/skills/product-build/scripts/product_build.py" check --project "$PWD"   # 계획 유지, 영향 화면 배치만 stale
```

## 7. 복원

| 상황 | 복원 방법 |
|---|---|
| 엔진 업데이트 직후 상태가 다르게 보임(§3 DIFF) | 엔진을 이전 커밋으로 되돌림: `cd <엔진>; git checkout $(cat "$E/engine-before.txt")`. 제품 프로젝트는 엔진 업데이트만으로 쓰이지 않으므로 그대로입니다. 혹시 바뀌었다면 `git checkout -- .ai-workflow/` |
| 기능을 켠 직후(패치·진행 중 CR 없음) | `change disable --confirm --note …`(추가한 필드만 제거) 또는 `git checkout -- .ai-workflow/design.json`(커밋 전), 커밋 뒤면 `git revert <enable 커밋>` |
| `enable` 도중 실패 | 엔진이 원래 바이트로 자동 복원합니다(부분 쓰기 없음). 백업 파일이 있으면 `.ai-workflow/backup/design/design.json.pre-changes` |
| 패치(AMD)가 생긴 뒤 기능·엔진을 되돌리려 함 | `disable`은 거부됩니다(유효 승인 기준이 깨짐). 패치 이전 커밋으로 **산출물과 상태 파일을 함께** 되돌립니다: `git revert <패치 커밋들>` 또는 `git checkout <enable 이전 커밋> -- .ai-workflow/design.json docs/design design-preview design-profile`. 구 엔진은 패치 체인을 모르므로, 패치된 파일이 남은 채 구 엔진으로 돌아가면 `approved_modified`로 차단됩니다(설계상 안전 방향) |
| 진행 중 CR을 버리고 싶음 | 범위 파일을 기준으로 되돌린 뒤 `change cancel --id … --reason …`(제자리 교체로 바뀐 권리 기록은 자동 복원) |
| 측정 어댑터 교체 후 문제 | `git checkout -- tools/pd-measure/` 후 이전 명령을 다시 확인(`explore-config --measure-cmd … --confirm --note …`) |
| 상태 파일 병합 충돌·중복 키 | 엔진은 자동으로 고르지 않습니다(`state_unreadable`·`state_duplicate_keys`). `git merge --abort` 또는 한쪽 기준으로 복원 후 다른 쪽 변경을 다시 진행합니다(Worktree 간 통합은 M3) |

## 8. 알려진 한계

`change-request.md` §9를 참고합니다.
