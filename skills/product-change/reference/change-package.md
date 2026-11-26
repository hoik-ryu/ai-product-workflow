# 변경 패키지(Change Package) 레퍼런스

승인된 제품의 변경을 **사용자 승인 2회**(변경 계약 → 최종 통합)로 처리합니다. 각 단계의 엔진 검증(추적성·프리뷰 검사·빌드·화면 실측·배치 검증·회귀)은 생략하지 않고, 사용자에게 다시 묻는 횟수만 줄입니다.

## 1. 상태와 소유권

| 파일 | 소유(쓰기) | 내용 |
|---|---|---|
| `.ai-workflow/change.json` | `/product-change` | 기능 켜짐·패키지 목록·각 패키지 상태·기준 스냅샷·영향·승인·finalize 진행 |
| `docs/changes/CP-###.json`·`.md` | `/product-change` | 계약 원본(revision별)과 사람이 읽는 렌더링 |
| `.ai-workflow/changes/CP-###/pre/` | `/product-change` | 패키지를 열 때의 미커밋 파일 백업(Git 제외) |
| `state.yaml`·`design.json`·`build.json` | 각 Skill | 패키지는 각 Skill CLI의 `--package` 옵션으로만 바꿈 |

상태 저장은 `.ai-workflow/.change.lock`(O_EXCL) 잠금 아래에서 하며, 읽은 뒤 다른 프로세스가 바꿨으면 거부합니다. 같은 패키지 키가 두 번 있는 `change.json`(병합 흔적)은 `state_duplicate_keys`로 멈추고 자동으로 고르지 않습니다.

패키지 상태: `awaiting_contract_approval` → `executing` ⇄ `escalated` → `awaiting_final_approval` → `finalizing` → `approved` / 언제든 `abandoned`.
진행 중(앞의 다섯 개)인 패키지는 하나만 둘 수 있습니다. 진행 중인 디자인 변경 요청(M1 CR)이 있으면 패키지를 열지 않습니다(반대도 같음).

## 2. 변경 계약 형식(`change-contract/v1`)

```json
{
  "schema": "change-contract/v1",
  "purpose": "주문 취소 복원(AC-164)을 폐기한다",
  "policy": "취소된 주문은 되돌리지 않는다",
  "ids": {"add": [], "modify": ["AC-160"], "remove": ["AC-164", "FLOW-005-S7d"]},
  "keep": ["주문 취소 자체(AC-159)", "주문 상세 화면 레이아웃"],
  "design": {"units": ["VD-084", "VD-085", "UXD-112"], "screens": ["SCR-112", "SCR-226"], "files": []},
  "build": {"rework": ["B11"], "regression": ["B2", "B6"]},
  "files": ["frontend/src/features/orders/**", "backend/app/modules/orders/**"],
  "db_api": {"migrations": [], "api": {"add": [], "modify": [], "remove": []}},
  "tests": {"remove": [{"ac": "AC-164", "paths": ["backend/tests/modules/test_order_restore.py"]}], "modify": [], "add": []},
  "risky_ops": [],
  "verification": ["B11 재작업, B2·B6 회귀", "SCR-112·SCR-226 화면 실측"]
}
```

- 계약은 **프로젝트 밖** 파일로 만들어 `open --contract`로 등록합니다. 엔진이 `docs/changes/`에 복사·렌더링합니다.
- `design.units`에 `"tokens"`를 넣어야 디자인 토큰·테마 변경이 허용됩니다.
- `risky_ops`: `security`(인증·권한), `migration`(DB 스키마) 등. 계약에 없는 위험 경로(`**/migrations/**`, `*.sql` 등) 변경은 `check`가 막습니다.
- `tests.remove`는 **AC 단위**입니다. 같은 파일이라도 폐기 AC가 아닌 테스트 단위 삭제·assert 완화는 계약 밖으로 막습니다.

계약 승인 digest = 계약 sha256 + 기준 digest(승인 기획 해시·디자인 유효 기준·구현 계획 승인) + 영향 digest. 계약을 개정(`amend-contract`)하면 새 revision이 되고 이전 승인은 재사용할 수 없습니다(`contract_approval_reuse`).

## 3. 영향 분석(P1)

`pc_graph.py`가 기획·디자인·프리뷰·계획·코드를 ID 그래프로 만들고, 바뀐 ID(씨앗)에서 전파합니다.

1. **기획 차이**: 승인본(작업 트리·Git 이력에서 해시로 찾음)과 현재 문서를 ID 블록 단위로 비교합니다. 헤딩 블록(US·AC·FLOW)과 표·목록 행(FR·NFR·C·FLOW 단계). 폐기는 ID 취소선(`~~AC-164~~`) 또는 제목·첫 칸의 폐기 표기(`(r14에서 폐기)`)로만 판정합니다. 긴 본문 속 '폐기' 언급은 폐기가 아닙니다. 따로 추적하는 하위 행(FLOW-001 안의 FLOW-001-S1a)은 상위 블록 변경으로 세지 않습니다.
2. **직접 영향**: 씨앗 ID를 적은 디자인 블록(UXD·SCR·CMP·VD)·추적 행·흐름 행·배치.
3. **간접 영향(화면 경유)**: 영향 행·블록이 가리키는 화면(SCR)은 영향 화면이 됩니다. 영향 화면을 가리키는 VD·UXD·CMP 블록, 그 화면의 프리뷰 파일 묶음(manifest 기준 closure), 그 화면을 다루는 배치로 이어집니다.
   예(AC-164): `AC-164 → 05 추적 행 → SCR-112·SCR-226 → VD-084·VD-085 → design-preview/src/screens/SCR-226.tsx·공용 컴포넌트(OrderCard.tsx 등)`.
   화면 블록(SCR-###) 자체가 직접 영향이면 그 화면만 씨앗이 됩니다(블록 안 다른 화면 링크로 연쇄 확대하지 않음).
4. **보수적 확대(`widened`, 이유 기록)**: 여러 화면에 적용되는 VD는 다른 화면을 '검토 화면'(`review_screens`, 한 단계만)으로 넣습니다. 토큰 변경은 토큰을 쓰는 모든 화면, 새 ID는 증명할 수 없으므로 넓게 잡습니다.
5. **코드 언급**: Git 추적 파일과 미추적 파일에서 ID를 단어 단위로 찾습니다. `docs/` 아래 메모·제안 문서(`.md`)는 `doc_mentions`로 참고만 보여 주고 계약 공백으로 세지 않습니다.
6. **폐기 ID의 남은 참조**: 이력 표기(취소선·이력 절)는 `historical_refs`, 그 밖의 유효 참조는 `dangling_refs`. 유효 참조가 남으면 최종 묶음을 만들 수 없습니다.
7. **단계 판정**: 영향 단위가 없는 디자인 단계는 `stages_inherited`(다시 승인할 필요 없음), 있으면 `stages_affected`.

`open`은 영향 중 계약이 덮지 못한 것(`gaps`: 디자인 단위·배치·코드 파일·기획 ID)이 있으면 승인할 수 없다고 표시합니다(`approvable: false`).

## 4. 실행 중 기준(P2·P3)

- `snapshot-planning`: 기획 front matter revision = 승인 revision + 1, 차이 ID ⊆ 계약 ID여야 합니다. 벗어나면 `escalated`.
- 스냅샷과 계약 승인이 유효한 동안 `pd_core.read_gate`는 패키지 제안을 **임시 기준**(`package_basis`, `provisional`)으로 보고, 디자인은 outdated가 되지 않습니다. 구현 쪽도 같은 기준을 씁니다(`pb_core.input_baseline`의 `planning.package`).
- 디자인: `product_design.py change open --package`로 연 CR은 계약 디자인 단위·화면과 엔진 영향 범위 안에서만 바꿀 수 있습니다(`contract_scope_exceeded`). 바뀐 줄이 모두 계약이 허용한 하위 ID 행(예: FLOW-005-S7d)이면 상위 블록(FLOW-005) 변경으로 보지 않습니다. 같은 블록의 다른 줄을 고치면 위반입니다. 프리뷰 파일은 허용 화면의 closure 안에서만, 토큰·테마는 `tokens` 계약에서만 바꿀 수 있습니다. 패키지 CR은 개별 승인할 수 없고(`package_cr_final_only`) 최종 통합 승인으로만 반영됩니다.
- 구현: 재작업 배치는 새 실행(run)으로 시작합니다(이전 run 기록 보관). 검증은 패키지 표식과 함께 기록되며, 계약 밖 테스트 변경·위험 작업은 막습니다. 계약이 승인한 AC 테스트 단위 삭제는 다시 묻지 않습니다.
- 패키지가 진행 중이면 `build approve batch`는 `package_pending`으로 막습니다(배치 승인은 finalize가 승계).

## 5. 최종 통합 승인과 finalize(P4)

`submit-final`은 다음을 확인한 뒤 묶음 digest를 만듭니다: 스냅샷 이후 기획 변경 없음, 범위 밖 변경 없음, 디자인 CR이 제출 상태(화면 실측 포함), 영향 단위가 처리되었거나 `review`로 이유가 남음, 폐기 ID 유효 참조 없음, 재작업·회귀 배치가 패키지 표식으로 검증됨, 회귀 산출물 digest. `approve-final`은 digest를 다시 계산해 같을 때만 받습니다.

finalize 순서(각 단계 완료를 `change.json`에 기록, 다시 실행하면 끝난 단계는 건너뜀):

1. **기획**: `ps_state.py reopen → submit → approve --package CP-###`(adopt 모드는 approve만). `ps_state.py`는 `change.json`이 finalizing이고 기획 해시가 패키지 제안과 같을 때만 받으며, 승인 기록에는 `[CP-### 최종 통합 승인 <시각> · 묶음 <digest 앞 12자>] <사용자 원문>`을 남깁니다.
2. **디자인**: `product_design.py change package-finalize --package` — 영향 단계만 범위 rebase, 승인 패치(Amendment, kind `package`) 추가, 영향 없는 단계 승인은 그대로.
3. **구현**: `product_build.py package-finalize --package` — 계획 reopen·submit·approve, 패키지 기준으로 검증된 배치 승인 승계.

finalize가 끝나기 전에는 `gate`가 종료 코드 2를 내고, 부분 finalize 상태에서도 공식 빌드·배포·활성화는 막힙니다. 테스트에서는 `PC_SIMULATE_FAIL_AT=planning:reopen|planning:submit|planning:approve|design|build`로 각 지점의 강제 중단을 재현합니다.

## 6. 무결성 규칙 요약

- 계약 승인·최종 승인은 각각 산출물 digest에 결합합니다. 승인 이후 바뀌면 거부합니다.
- 기존 승인 기록·해시는 바꾸지 않고, 새 승인 기록과 Amendment만 덧붙입니다.
- 계약 확장(개정)은 이전 승인을 재사용할 수 없습니다.
- 사용자 승인 문장은 두 번의 원문만 쓰고, 단계별 문장을 만들지 않습니다. state 파일을 직접 조작하는 경로는 없습니다.
- 진행 중 패키지는 하나, 다른 진행 중 변경(M1 CR, 다른 패키지)과 동시에 열 수 없습니다.

## 7. 미커밋 작업 보호와 취소

`open`은 세 가지를 구분합니다: 승인 기준(Git·승인 해시), 패키지 전 작업 트리(열 때의 미커밋 변경 — 스냅샷·백업), 패키지 변경(그 이후).
`abandon --restore`는 다음만 되돌립니다: 계약 범위 안이면서 패키지가 바꾼 파일 → 열 때 내용(Git 기준 또는 백업). 새로 생긴 파일은 지우지 않고, 범위 밖 파일은 건드리지 않으며(`skipped`), 열 때 미커밋이던 파일은 그 내용 그대로 둡니다(`kept_preexisting_uncommitted`). 복원 대상이 열 때 이후 다른 사람이 바꾼 것으로 보이면 멈춥니다. `git reset --hard`·`git clean`·조건 없는 `git restore`는 쓰지 않습니다.

## 8. 기존 프로젝트 적용(전환)

1. 진행 중인 단계(제출·승인 대기, 진행 중 CR·배치)가 없을 때 `enable`합니다(`transition_problems`가 있으면 거부).
2. 기획을 고치기 **전에** 켭니다. 이미 고쳤다면 `/product-start`로 제출(awaiting_approval)한 뒤 패키지를 `adopt` 모드로 열 수 있습니다(제출본을 받아들임).
3. 디자인 영향이 있는 패키지는 디자인 v2 + 변경 요청 기능이 켜져 있어야 합니다. 아니면 `design_package_unsupported`로 열지 않습니다(기존 재개정 경로 사용).
4. 켜기 전 프로젝트, 켜지 않은 프로젝트는 동작이 바뀌지 않습니다.

## 9. 한계

- 영향 분석은 ID 텍스트 그래프 기반입니다. ID를 적지 않은 코드의 의미적 의존은 찾지 못하므로 화면·배치 단위 회귀(regression)로 보완합니다.
- 화면을 많이 공유하는 결정(VD)·컴포넌트가 많은 제품에서는 검토 범위가 넓게 나옵니다(이유는 `widened`에 남음). 줄이려면 `review`로 바꾸지 않는 이유를 남깁니다.
- 동시에 여러 패키지를 병렬로 진행하는 기능(worktree 병합, M3)은 범위 밖입니다. 동시 진행은 감지해 막기만 합니다.
- 실제 대규모 프로젝트의 전체 finalize(재작업 배치 구현 포함)는 픽스처에서만 끝까지 검증했습니다. 실제 프로젝트 사본 리허설(엔진 저장소 docs/roadmap/change-package-adoption.md)은 영향 분석·계약 승인·기획 스냅샷·디자인 범위 판정·안전 취소까지 확인했습니다.
