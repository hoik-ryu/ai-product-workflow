# 디자인 탐색(design_exploration) 상세 설계와 구현 계획

상태: **EX0 확정(2026-11-17, 구현 전)**. 엔진 코드·Skill 파일은 바꾸지 않았습니다. 기준 엔진 커밋: `a92a57c`. EX0 결정과 그에 따른 설계 변경은 §0.1에 있습니다.
근거: 설치된 디자인 Skill 조사(2026-11-17), `design-workflow-v2.md`(v2 원칙·WF-D14~D18), SMAPSH `SCR-211-design-experiment-AB.md` §7(실제 적용 사례 — 엔진 규칙의 근거로만 쓰고 특화 규칙은 넣지 않음).

## 0. 확정된 결정과 범위

| # | 결정 | 이 설계에서의 의미 |
|---|---|---|
| 1 | frontend-design 재사용 | 시안 제작의 **절차 지침**(계획 → 진부한 기본값과 대조 → 제작 → 스크린샷 자기 비평)으로 씁니다. 엔진의 필수 의존이 아니며, 설치되지 않아도 같은 절차를 엔진 문서(`reference/exploration.md`)로 수행합니다 |
| 2 | 새 UI Design Skill 없음 | `/product-design` 안의 선택 기능으로 둡니다. 상태는 `design.json`, 판정은 `product_design.py` |
| 3 | UI UX Pro Max 보류 | 외부 규칙 데이터는 WF-D16(규칙 출처 어댑터)이 생길 때 다룹니다. 이번 설계는 규칙 출처 없이 동작합니다 |
| 4 | 신규 v2 기본 활성, 정책으로 끔 | §2.3에서 "신규"를 데이터로 정의합니다 |
| 5 | 승인 게이트·해시·추적성 유지 | 탐색은 **승인 단계가 아닙니다.** 기존 단계(ux_planning, design_direction) 안의 **제출 조건**으로만 들어갑니다 |
| 6 | 제품·프레임워크 비종속 | 기본 렌더러는 격리된 HTML/CSS. 엔진은 산출물 계약과 판정만 압니다 |

### 0.1 EX0 결정(확정)과 설계 반영

| # | 결정 | 이전 설계와의 차이 | 반영 위치 |
|---|---|---|---|
| D1 | 화면 유형은 엔진 기본 목록 + 프로젝트별 확장·재정의 | 같음(권장안 채택) | §2.4 |
| D2 | 시안 기본 3개, 최소 2개. **단순 색상 차이가 아니라 구조 또는 시각 방향이 명확히 달라야 함** | 이전: 구성 서명이 같으면 **경고**(`variants_not_distinct`) → **오류**로 강화하고 판정 기준을 단계별로 정의 | §2.7.1 |
| D3 | 측정 도구가 없으면 경고 후 선택 허용. **측정에서 실제 오류가 확인되면 기존 검증 정책대로 차단** | 이전: 측정 결과와 선택의 관계 미정 → 차단 오류가 있는 시안은 선택 불가 | §2.7.2, §2.8 |
| D4 | 시안과 **제품 코드**의 동일 파일 복사, 명시적 import·copy 차단. **시각적 유사성은 차단하지 않음** | 이전: 유사도 임계값 경고 → **삭제**. 검사 대상을 프리뷰에서 product-build 범위 코드까지 확장 | §2.9 |
| D5 | Figma는 HTML 표지를 요구하지 않음. **공통 manifest 계약 + 렌더러별 검증** | 이전: 요소 근거를 HTML 표지에만 의존 → 근거 목록을 manifest의 렌더러 무관 `elements`로 옮기고, HTML은 표지에서 **추출·대조**, Figma는 **선언 검사** | §2.5, §2.6 |
| D6 | 선택 기록·재현 증거는 Git 추적 가능하게, 선택되지 않은 시안·임시 파일·대량 스크린샷은 기본 제외. 선택 시안의 manifest·계획·비평·핵심 시각 증거는 누락 금지 | 이전: 라운드 전체 트리 해시 + 커밋 권장 → **보존 집합**을 정의하고, 엔진이 `.gitignore`와 보존 목록을 만들며, 무결성은 보존 집합 기준 | §2.11 |
| D7 | 기존 v2에서 2차 탐색을 켜면 Design Direction 게이트가 **반드시** 켜져 있어야 함 | 이전: 함께 켜도록 안내(권장) → **필수 조건**. 게이트가 꺼져 있으면 `explore-config --enable visual` 거부 | §2.3 |

D2·D3·D5는 판정을 엄격하게, D4는 범위를 좁히는(유사도) 동시에 넓히는(제품 코드) 변경입니다. 승인·해시·revision 체계에는 영향이 없습니다.

### 0.2 최종 결정(U1–U4, 2026-11-17)과 구현 반영

| # | 결정 | 반영 |
|---|---|---|
| U1 | 레퍼런스 원본은 프로젝트 안 격리 경로(`design-explore/references/REF-xxx/original.<ext>`), 기본 Git 제외, 원본 해시 재검증 가능 | §2.12.7 그대로. `.gitignore`의 `references/*/original.*`는 EX1부터 생성 |
| U2 | MVP 색상 분석은 모델 추정 허용, 추정값 표시·사용자 확인 | §2.12.2 확인 규칙(`estimated`는 `confirm: required` 대상) |
| U3 | 이미지당 10MB, 라운드당 5장, PNG·JPEG·WebP, 프로젝트 정책으로 변경 | `config.exploration.limits`(`reference_max_bytes`·`references_per_round`·`reference_formats`) 기본값으로 EX1에 기록, 판정은 EX3 |
| U4 | 개인정보는 모델 점검과 사용자 확인을 모두 기록, 모델 판단만으로 안전 확정 금지 | §2.12.7: 추적(`track`) 조건에 사용자 확인 필수 |

**단일 시안 예외(D2 보완)**: AI 신규 탐색은 기본 3개, 레퍼런스 기반 신규 탐색은 기본 2–3개입니다. 사용자가 특정 레퍼런스나 **기존 시안을 기준으로 고치는 후속 라운드**(`explore-init --parent <라운드> --base <라운드-시안> [--variants 1]`, 라운드 `kind: revision`)에서는 단일 시안을 허용합니다.
- D2와의 관계: 시안 간 구분 검사(`variants_not_distinct`)는 시안이 2개 이상일 때만 적용합니다. 단일 수정 시안은 대신 **기준 시안과 렌더 산출물이 달라야** 합니다(`revision_identical_to_base`). 신규 탐색(`kind: explore`)은 여전히 2–3개만 허용(`variant_count`).
- 단일 시안도 렌더링·계약 검사·시각 평가(critique)·사용자 선택 문장·핵심 증거를 모두 거쳐야 선택됩니다(테스트 X28–X33).
- 레퍼런스 기준 단일 수정은 EX3에서 같은 `kind: revision`에 `base: REF-xxx`를 허용하는 방식으로 확장합니다.

**구현 중 좁힌 것(사용자 원칙 "기존 프로젝트 자동 활성 금지"에 맞춤)**: §2.3의 "승인 기록이 없는 프로젝트를 `migrate --to v2`하면 기본 활성"은 구현하지 않았습니다. 진행 중인 기존 v1 프로젝트도 기존 프로젝트이므로, **기본 활성은 `start --workflow v2`로 새로 시작한 프로젝트만**입니다. 그 밖은 `explore-config`(사용자 문장)로 켭니다.

**구현 상태**: EX1·EX2·EX2.1·EX3(레퍼런스 MVP, `pd_reference.py`)·EX4(측정)·EX5(2차 시각 탐색, `pd_visual.py`) 구현(엔진 커밋 전). EX5: `explore-init --phase visual`(Must·구성 서명 대표 화면), 구조 지문 `structure_drift`, 후보 테마·엔진 생성 토큰 CSS·날 색 값 금지, `variants_color_only`, 측정 연계 `component_inconsistent`(차단 — 화면·인스턴스 간 같은 컴포넌트의 계산된 스타일), 레퍼런스 토큰 출처·대조 사실(alignment), 축별 조합 선택, `explore-adopt`(후보 VD·후보 테마·UI Brief 근거 후보, 07·공식 테마 미작성), Design Direction 제출 조건·trace(`adopted_theme_unapproved`), `explore-impact`. 테스트는 같은 파일의 V 그룹. **EX5.1**(시각 품질 개선): 시각 자산 계약 `pd_assets.py`(아이콘 스타일 가이드·출처·라이선스·해시·장식/기능 역할·권리 확인 전 공식 채택 금지·레퍼런스 복제 금지·자산 없이 렌더 측정 `--asset-fallback`), 시각 품질 평가 계약 `pd_quality.py`(design-quality-review/v1: 7기준 등급·스크린샷 근거·개선 항목 필수·자동 사실과 모순 금지), 기준 시안 수정 라운드(목표·피드백·기본 2회·수정 전후 비교). `component_inconsistent`는 뷰포트·명시적 변형·선언된 상태별로만 비교. 테스트는 같은 파일의 A 그룹. **EX6**(구현 보호·영향): 읽기 전용 `pd_guard.py`를 preview-check·product-build verify·ui-guard·UI Brief가 공유 — 동일·느슨한 정규화 복사, CSS 부분 복사, 경로 변형·심볼릭 링크 참조, 탐색 후보 토큰, 레퍼런스 원본, 미승인 자산(권리·승인 VD·해시), 등록 자산은 자산 기준 판정; UI Brief `design_sources`(승인 기록 VD·공식 자산, 탐색 선택은 source_only); `impact --design --choice`·`exploration_choice` 사실 종류. 테스트는 같은 파일의 P 그룹·V38·V39·R57. **EX7**(렌더러): `pd_render.py` — 시안별 렌더러(html 기본·코드 어댑터 정적 HTML·figma 선언 검사), 렌더러 버전·상태(complete·incomplete·failed·unavailable), Figma 파일·페이지·프레임 ↔ 화면 ID·요소 ↔ 노드·프레임 토큰·컴포넌트·자산 근거, 외부 전송 범위 기록·사용자 허용 범위·레퍼런스/개인정보 별도 확인, figma는 측정 not_run·렌더러 스크린샷 증거·품질 근거, `explore-renderer` 설정. 테스트는 같은 파일의 N 그룹. 미구현: 레퍼런스 기준 단일 수정(`base: REF-xxx`). EX8 E2E는 `tests/product_workflow_e2e_test.py`. **v1.0 안정화**(P0·P1: 승인 자산 스냅샷, 주석 판정, 탐색 선택 stale, verify 검사 일치, 측정 명령 지문, discovery 제출 스냅샷): `reference/exploration.md` 15절, 테스트 `tests/product_stabilization_test.py`. 테스트 `tests/product_design_explore_test.py`(EX3은 같은 파일의 R 그룹, 별도 `product_design_reference_test.py`는 만들지 않음). EX3 추가: 프로젝트 상한 변경 `explore-ref policy`, EX5용 후보 내보내기 `explore-ref candidates`(`design-system-candidates/v1`, 승인 아님). EX4(브라우저 측정, `pd_measure.py`): `explore-verify`, `design-explore-report/v1` 판정(pb-ui-report/v1 공통 필드·같은 분류 + 레이아웃 사실: 실제 뷰포트·DPR, 상자, 고정 요소 가림, 적중 검사, 선언 열 구조 `layouts` 대조, 터치·대비), 측정 무효(뷰포트·스크린샷 크기 불일치 포함)와 미실행 구분, 시안 기준 해시로 측정 이후 변경 무효(`measurement_stale`), 차단 시안 선택 거부, 측정 스크린샷 핵심 증거·critique 근거 스크린샷, 예시 어댑터 `templates/measure-adapters/chrome-cdp/`(엔진 비의존). 테스트는 같은 파일의 M 그룹. **C13 대비 변경**: 차단 분류에 `layout_mismatch`(선언 열 구조와 실제 배치 불일치)·`required_not_rendered`·`required_unreachable`(필수 항목 요소가 보이지 않거나 어떤 스크롤 위치에서도 가려짐)을 더함 — 사용자가 고르는 구조가 선언과 다르게 렌더링되므로. 뷰포트·스크린샷 크기 불일치는 시안 결함이 아니라 측정 무효(`invalid`). 측정 무효·미측정은 재측정 또는 사용자 문장(`--measurement-waiver`).

### 0.3 EX2.1 안정화(2026-11-17, SMAPSH r6 실사용 검증 후)

| # | 문제(실사용 검증) | 반영 |
|---|---|---|
| P0-1 | critique 판정이 줄바꿈을 넘어 다음 항목을 값으로 읽어, 마지막 항목만 채워도 통과(게이트 우회) | 항목 단위 파싱(같은 줄 + 이어지는 줄), 자리표시(`TODO`·`-`) 거부. 여러 줄 평가는 허용 |
| P0-2 | 검사가 요구사항 밖 요소(초과)만 막고 필수 정보 누락은 통과(구조 시안이 AC-053 프로필을 빠뜨림) | 대상별 AC 후보 계산(엔진) → 분류(required·delegated·not_ui·other_target·uncertain, Claude) → 필수 항목(R#) → 시안 요소 `covers` 대조. HTML에 실제로 있는 요소만 셈. `required_missing`은 선택 차단, 위임·불확실은 선택 시 사용자 확인 문장 |
| P1 | 자동 선정이 허브·역할별 첫 화면을 고르지 않음, 한국어 유형 판별 약함 | 역할별 첫 화면·허브·진입점·다른 흐름 연결 점수와 근거(`basis`) 출력, 기본 유형에 hub 추가·한국어 키워드 보강, 동점이면 문장 끝 서술어 쪽, 프로젝트 유형·assign 우선 |
| P2 | 대상 표시가 기획 문장(로그인 흐름 문장)이라 무엇을 비교하는지 흐림 | `--targets "ID+ID=표시 이름"`. 표시 이름은 표시 전용(ID 포함 금지), 근거·검사는 앵커 ID |

계약 변경: manifest 라운드에 `coverage`, 요소에 `covers`(선택 필드). EX2 라운드(coverage 없음)는 다시 검사하면 `coverage_missing`이 됩니다(EX2 산출물은 실험용이라 호환 경로를 두지 않음).

**확장(2026-11-17): Reference-driven Design** — 사용자 레퍼런스 이미지로 탐색 방향을 지정하는 기능을 같은 탐색 라운드 안의 `mode`(ai·reference·mixed)로 통합했습니다(별도 승인 단계·Skill 없음). 설계는 §2.12, EX0 결정과의 충돌과 해결은 §8, 구현 순서 영향은 §5.

## 1. 현재 엔진과의 충돌 확인과 해결

| # | 요구 | 현재 엔진 | 충돌 | 해결 |
|---|---|---|---|---|
| C1 | 신규 v2 프로젝트 기본 활성 | `start`는 항상 v1을 만들고, v2는 사용자 승인 `migrate --to v2 --confirm`으로만 켜짐 | "신규 v2"가 존재하지 않음 | `start --workflow v2`(사용자가 시작할 때 명시) 추가, 또는 **승인 기록이 하나도 없는** 프로젝트를 v2로 전환할 때 기본 활성. 그 밖의 전환·기존 v2는 꺼짐(§2.3) |
| C2 | 1차 탐색을 UX Planning 확정 전에 | UX Planning 산출물은 00(UXD)뿐, **화면 ID(SCR)는 UX Spec에서 생김** | 대표 "화면"에 ID가 없음 | 1차 시안의 대상은 **기획 ID 기준 장면**(FLOW 단계·US·AC)입니다. 선택 결과는 UXD로 기록되고, UX Spec에서 SCR이 그 UXD를 참조합니다(기존 02 `UX 결정` 필드) |
| C3 | 2차 결과를 VD·테마로 | design_direction 게이트는 기존 v2에서 꺼져 있음(선택 단계). 꺼져 있으면 프리뷰가 VD를 검사하지 않음 | 시각 선택이 프리뷰에 도달하지 않을 수 있음 | 신규 v2(§2.3)는 `gates.design_direction: true`로 시작. 기존 v2는 **게이트가 켜져 있어야만** 2차 탐색을 켤 수 있음(D7, 기존 `migrate --enable-gate` 절차를 먼저) |
| C4 | 선택 결과 해시·근거 기록 | `design-notes.md`는 해시 대상 아님. `design.json`은 스크립트만 씀 | 선택 기록의 무결성 | 선택은 `design.json.exploration`에 스크립트 명령(`explore-choose`)으로 기록. 시안 파일 해시·사용자 문장 포함 |
| C5 | 선택 결과만 UXD·VD 후보에 | UXD 상태 `확정`/`권장안 수용`, VD는 후보가 남으면 제출 불가 | 없음(맞물림) | 2차 채택은 VD를 **`후보`로만** 넣고, 기존 규칙대로 VD마다 사용자 결정. 1차는 선택 자체가 사용자 답이므로 UXD `확정` + 근거에 선택 ID |
| C6 | 탐색 시안은 공식 승인 대상 아님 | 승인 규칙: 명시적 승인 표현만 인정 | 선택이 승인처럼 보일 위험 | 선택 명령은 `approve`와 분리. 선택 표현("B안 선택")만 인정하고 승인 표현으로 기록하지 않음. 시안 트리는 어떤 승인 해시에도 들어가지 않음 |
| C7 | 시안 코드 복사 금지 | 규칙 8: 프리뷰는 `design-preview/`에만. product-build는 `design-preview/`를 보호·재사용 차단 | 새 폴더가 보호되지 않음 | `design-explore/`를 product-design `start`의 기존 경로 검사, `preview-check` import·복사 검사, product-build `PROTECTED`·`preview_reuse` 대상에 추가 |
| C8 | 테마 연결 | 테마 파일은 승인 산출물이 아님. 04 토큰 이름이 기준, 새 이름은 ② | 없음 | 테마 **값**(데이터)은 옮길 수 있음(그게 목적). 시안 HTML/CSS **코드**는 옮기지 않음. 후보 테마는 04 토큰 이름만 쓸 수 있음(아니면 ②로 CR) |
| C9 | 브라우저 측정 | product-build의 `pb-ui-report/v1` 판정은 product-build 안에 있음. Skill 간 import 금지(독립 Skill) | 재사용 경로 | 같은 필드의 **`design-explore-report/v1`** 계약을 product-design에 따로 둠(형식만 같고 코드는 독립). 어댑터 하나로 두 형식을 낼 수 있게 필드를 맞춤 |
| C11 | 시안과 제품 코드 복사 차단(D4) | product-build는 `design-preview/`만 재사용 검사. product-design은 product-build 범위를 모름 | 검사 주체 | 프리뷰 쪽은 product-design `preview-check`, 제품 코드 쪽은 product-build(UI Plan 경로 필드·`verify` 범위 파일·`ui-guard`)가 각각 같은 규칙(동일 파일·명시 참조)으로 검사. 규칙 정의는 이 문서 §2.9 하나 |
| C12 | 선택되지 않은 시안 제외(D6) vs 선택 기록 무결성 | 이전 설계는 라운드 전체 트리 해시를 무결성 기준으로 씀 | 제외된 파일이 없어지면 해시를 다시 확인할 수 없음 | 모든 시안의 **파일별 해시는 선택 기록에 남기고**, 이후 무결성 검사(`changed_since_choice`)는 **보존 집합**만 대상으로 함. 제외된 시안은 "기록상 존재, 파일 미보존"으로 표시 |
| C13 | 측정 오류 차단(D3) vs "측정은 선택을 막지 않음"(이전 §2.6) | 이전 문장이 미실행과 오류를 구분하지 않음 | 정책 불일치 | 미실행(`not_run`)은 경고, **차단 결과**(렌더 실패·콘솔 오류·접근성 critical·핵심 상호작용 실패 — product-build 브라우저 판정과 같은 분류)는 그 시안의 선택 거부 |
| C10 | 2차 탐색이 구조를 바꾸면 | 07은 ①·②를 결정하지 않고 CR로 UX Spec reopen | 시안이 정보·행동을 바꿀 위험 | 2차 시안은 **구조 지문**(승인된 02의 화면별 정보·행동·CMP·상태 집합)과 같아야 함. 다르면 `structure_drift` 오류. 의도한 구조 변경은 CR(①)로만 |

## 2. 상세 설계

### 2.1 전체 흐름

```
ux_planning(in_progress)
  ├ 인터뷰 라운드(기존)
  ├ [1차 탐색: 구조] 대상 장면 선정 → 시안 A/B/C → 측정·자기 비평 → 비교 페이지 → 사용자 선택(explore-choose)
  ├ 선택 → UXD(확정, 근거: EXP-S01-B) 작성
  └ submit(조건: 1차 탐색 chosen 또는 skipped) → "UX 결정 확정" → approve          ← 기존 게이트 그대로
ux_spec → (구조 확인) → 승인                                                     ← 변경 없음
design_direction(in_progress)
  ├ [2차 탐색: 시각] 대표 화면 선정 → 시안 A/B/C(구조 지문 고정) → 측정·자기 비평 → 비교 → 선택
  ├ explore-adopt: 후보 VD 블록·후보 테마 출력 → 07에 '후보'로 기록 → VD별 사용자 결정(기존)
  └ submit(조건: 2차 탐색 chosen 또는 skipped, 후보 VD 없음) → "디자인 방향 승인" → approve ← 기존 게이트 그대로
preview → 승인 → /product-build                                                 ← 프리뷰는 승인 VD·테마로 새로 작성
```

### 2.2 공식 삽입 지점

| 탐색 | 삽입 지점 | 새 제출 조건(탐색이 켜진 프로젝트만) | 기존 규칙과의 관계 |
|---|---|---|---|
| 1차(구조) | `ux_planning` `in_progress` 중, `submit --stage ux_planning` 전 | `exploration.structure.status ∈ {chosen, skipped}`. chosen이면 선택 ID를 근거로 하는 UXD가 00에 1개 이상 | 답변 대기 라운드가 있으면 제출 거부하는 기존 규칙과 같은 형태. 승인·해시·무효화 불변 |
| 2차(시각) | `design_direction` `in_progress` 중, `submit --stage design_direction` 전 | `exploration.visual.status ∈ {chosen, skipped}`. chosen이면 선택 ID를 근거로 하는 VD가 07에 1개 이상(승인 또는 제외로 결정됨) | 후보 VD가 남으면 제출 불가인 기존 규칙 그대로 |

`skipped`는 사용자 문장과 사유가 있어야 합니다(`explore-skip --note`). 엔진이 대신 건너뛰지 않습니다.

### 2.3 활성화 정책(호환성 포함)

| 프로젝트 | 1차 | 2차 | design_direction 게이트 |
|---|---|---|---|
| `start --workflow v2`로 새로 시작 | 켜짐 | 켜짐 | 켜짐 |
| ~~승인 기록이 하나도 없는 프로젝트를 `migrate --to v2`~~ — 구현에서 제외(§0.2): 기존 프로젝트는 자동 활성 없음 | 꺼짐 | 꺼짐 | 기존대로 |
| v1 프로젝트, 승인 기록이 있는 프로젝트의 `migrate --to v2` | 꺼짐 | 꺼짐 | 기존대로(꺼짐) |
| 이미 v2인 프로젝트(엔진 갱신 전 전환) | 꺼짐(`config.exploration` 없음) | 꺼짐 | 기존 값 유지 |

- 끄기(프로젝트 정책): `explore-config --disable structure|visual|all --note "<사용자 문장>" --confirm`. `config.exploration.<단계>.enabled=false`와 사유·문장을 남깁니다. 이미 chosen된 기록은 지우지 않습니다.
- 켜기(기존·승인 프로젝트): `explore-config --enable structure|visual --note --confirm`. 켠 기록(`exploration.activations`)만 남기고 **승인 상태는 바꾸지 않습니다.** 적용 시점:
  - 1차: ux_planning이 이미 승인이면 다음 `reopen --stage ux_planning`(사용자 결정, 하위 승인 무효) 이후부터 제출 조건 적용
  - 2차: design_direction이 이미 승인이면 다음 `reopen --stage design_direction` 이후부터.
  - **2차를 켜는 조건(D7)**: `config.gates.design_direction == true`. 꺼져 있으면 `explore-config --enable visual`은 `design_direction_gate_required`로 거부하고, 먼저 기존 절차(`migrate --to v2 --enable-gate design_direction` 계획 → 사용자 동의 → `--confirm`)를 안내합니다. 한 명령에서 두 가지를 함께 켜지 않습니다(승인 대상이 다른 두 결정을 한 번에 받지 않기 위해).
  - 게이트를 끄는 명령은 원래 없으므로, 2차가 켜진 뒤 게이트가 꺼지는 경우는 상태 파일 복원뿐입니다. 그때 `check`가 `exploration_gate_mismatch`로 보고하고 2차 명령을 거부합니다.
- `engine_repo`·v1 프로젝트에는 탐색 명령이 `exploration_unavailable`로 거부됩니다.

### 2.4 대표 장면·화면 선정 규칙(범용)

엔진이 후보를 계산하고, 사용자가 바꿀 수 있습니다(`explore-init --targets`). 기본 개수는 프로젝트 정책 `exploration.max_targets`(기본 없음 → 2–3을 권장 문구로만 안내, 엔진 강제 아님).

| 탐색 | 후보 계산(결정적) |
|---|---|
| 1차 | Must US가 가장 많이 걸린 FLOW의 첫 단계, 그다음 **유형이 다른** FLOW 단계(유형 추정: 해당 AC·FR 문장의 행동 동사 분류 — 조회·입력·확인·관리. 분류 실패 시 유형 '미분류'로 표시만) |
| 2차 | 승인된 02에서 Must 화면 중 **화면 구성이 서로 다른** 화면: 정보 행 수·입력 유무·목록 CMP 유무로 만든 구성 서명이 다른 화면을 우선. 1차 선택 UXD를 참조하는 화면 우선 |

선정 결과와 근거는 `exploration.<단계>.targets`에 기록합니다.

**화면 유형(D1)**: 엔진 기본 목록을 제공하고 프로젝트가 확장·재정의합니다.

| 기본 유형 | 판별 신호(결정적, 승인 문서에서) |
|---|---|
| `browse`(목록·탐색) | 목록·표 CMP, 필터·정렬 행동, 여러 항목 정보 |
| `detail`(상세) | 단일 항목 정보 행 위주, 편집·이동 행동 |
| `input`(입력·작성) | 02 '입력과 검증' 표가 있음 |
| `dashboard`(현황) | 숫자·요약 정보 행이 많음, 여러 출처 |
| `guidance`(안내·상태) | 정보 행이 적고 행동 1–2개(시작·완료·오류 안내) |

- 프로젝트 파일(선택): `design-profile/screen-types.json`(`{"format": "design-screen-types/v1", "extends": "default" | null, "types": {이름: {"label", "signals": {...}}}, "assign": {"SCR-001": "browse"}}`). `extends: null`이면 기본 목록을 쓰지 않고 재정의합니다. `assign`은 판별을 사람이 고정합니다(판별보다 우선).
- 이 파일은 승인 산출물이 아니며 해시는 탐색 라운드 `basis`에만 기록합니다. 판별 결과는 대상 선정과 구도 VD의 SCR 목록 작성에만 쓰고, 승인 판정에는 쓰지 않습니다.
- 판별이 안 되면 `unclassified`로 표시만 합니다(오류 아님).

### 2.5 산출물 계약(렌더러 무관)

```
design-explore/
  explore.manifest.json          # 엔진이 만들고 검사(템플릿), Claude가 채움 — 보존(Git 추적)
  .gitignore                     # 엔진이 생성·갱신: 보존 집합 밖 제외(§2.11)
  S01/                           # 1차 라운드(구조) — 라운드 ID: S##(structure) / V##(visual)
    brief.md                     # 탐색 브리프(엔진 생성: 입력 ID·제약·대상) — 보존
    A/ plan.md  index.html  styles.css      # 시안(렌더러 html). 선택되면 보존, 아니면 기본 제외
    B/ ...
    C/ ...
    critique.md                  # 모델 시각 평가(형식 검사) — 보존
    compare.html                 # 비교 페이지(엔진 생성: 대상 × 뷰포트 × 시안) — 재생성 가능, 제외
    shots/<variant>/<target>-<viewport>.png  # 측정 산출 스크린샷 — 기본 제외
    selection/                   # explore-choose가 만듦 — 보존
      selection.json             # 선택 기록 사본(모든 시안의 파일별 해시 포함)
      evidence/<target>-<viewport>.png   # 핵심 시각 증거: 선택 시안의 대상×뷰포트 스크린샷(또는 렌더러별 대체물)
  V01/ ...
```

`explore.manifest.json`(`design-explore/v1`, **렌더러 무관 공통 계약**)

```json
{ "format": "design-explore/v1", "experimental": true,
  "renderer": { "kind": "html | figma | <코드 어댑터 이름>", "adapter": null },
  "guidance": [ { "name": "frontend-design", "version": "1.1.1", "used_for": ["plan", "contrast", "critique"] } ],
  "rounds": {
    "S01": { "phase": "structure", "basis": { "planning_revision": "6", "screen_types_hash": null },
             "targets": [ { "id": "T1", "anchor": ["FLOW-001-S1", "US-001"] } ],
             "variants": {
               "A": { "title": "…", "concept": "…", "distinct_axes": ["layout", "hierarchy"],
                      "plan": "S01/A/plan.md", "render": { "html": "S01/A/index.html" },
                      "elements": [ { "target": "T1", "id": "e1", "kind": "action", "refs": ["US-001", "AC-002"], "label": "할 일 추가" },
                                    { "target": "T1", "id": "e2", "kind": "info", "refs": ["FR-001"], "sample": true } ] } } },
    "V01": { "phase": "visual", "basis": { "ux_spec_revision": "2", "ux_spec_hashes": "<digest>" },
             "targets": [ { "id": "SCR-003", "states": ["SCR-003-ST1", "SCR-003-ST4"] } ],
             "variants": { "A": { "distinct_axes": ["typography", "component"], "theme_candidate": "V01/A/theme.json",
                                  "render": { "html": "V01/A/index.html" }, "elements": [ … ] } } } } }
```

**요소 근거(`elements`) — 렌더러 무관**: 시안의 정보·행동 요소마다 근거 ID(1차: 기획 ID, 2차: `SCR-xxx:info-n`·`SCR-xxx:action-n`·`CMP-xxx`)를 선언합니다. `kind`는 `info | action | input | navigation | decoration`. `decoration`만 근거가 없어도 됩니다. 예시 데이터는 `sample: true`.

**렌더러별 검증(D5)**: 공통 계약 검사는 모든 렌더러에 같습니다. 렌더러별로 "선언이 실제 산출물과 맞는지"를 다르게 확인하고, 확인 수준을 기록합니다.

| 렌더러 | 렌더러별 검증 | 확인 수준 |
|---|---|---|
| `html`(기본) | HTML의 표지를 **추출해 manifest `elements`와 대조**: `data-el="e1"`(요소 ID), `data-target`. 상호작용 요소(`button`, `a[href]`, `input`, `select`, `textarea`, `[role=button]`)에 `data-el`이 없으면 `unbacked_element`, manifest에 없는 `data-el`이면 `undeclared_element`, 선언됐는데 HTML에 없으면 `element_missing`, 예시 데이터 선언 요소에 `data-sample` 표시 필수 | `checked` |
| 코드 어댑터(React 등) | 어댑터가 낸 **정적 HTML 산출물**을 `html`과 같은 방식으로 대조(소스는 `design-explore/` 안에만) | `checked` |
| `figma` | HTML 표지를 요구하지 않음. manifest에 대상별 `figma: {file_key, node_id}`, 요소별 `node`(노드 ID) 필수, 대상×뷰포트 스크린샷과 해시 필수. 엔진은 Figma를 호출하지 않으므로 노드와 선언의 일치는 확인하지 않음 | `declared`(모델 평가 `critique.md`에서 요소 목록 대조를 필수 항목으로 둠) |

공통 계약 검사(모든 렌더러): 근거 ID가 승인 문서에 존재, `decoration` 외 요소의 근거 필수(`unbacked_element`), 2차 구조 지문(§2.7.1), 후보 테마 토큰 이름이 04에 있음(아니면 ②), 시안 수 2–3개, `distinct_axes`(§2.7.1).

### 2.6 렌더러 분리

| 렌더러 | 지위 | 산출물 |
|---|---|---|
| `html`(기본) | 엔진 기본. 의존성 없음(파일을 브라우저로 열면 됨) | 정적 HTML/CSS + 표지 |
| 코드 어댑터(`react`·`vue` 등) | 선택형, 프로젝트가 설치·실행 | 정적 HTML 산출물(빌드 결과·스냅샷) + 스크린샷을 `design-explore/<라운드>/<시안>/`에. 어댑터 소스도 `design-explore/` 안에만 |
| `figma` | 선택형(MCP) | 노드 링크 + 스크린샷(manifest 공통 계약) |

엔진은 어댑터를 실행하지 않습니다. 측정 명령은 프로젝트 설정(`config.exploration.measure_cmd`)이고, 리포트 형식만 검사합니다(`design-explore-report/v1`: `pb-ui-report/v1`과 같은 필드 — `target`, `variant`, `viewport`, `rendered`, `console_errors`, `a11y`, `overflow`, `clipped`, `touch_target_violations`, `screenshot`, `run_id`). 측정 결과와 선택의 관계는 §2.7.2.

### 2.7 디자인 품질 검토

세 층을 분리해 기록합니다(v2 원칙 6).

| 층 | 누가 | 무엇 | 기록 표시 |
|---|---|---|---|
| 정적 검사 | 엔진(`explore-check`) | 공통 계약·렌더러별 검증(§2.5), 시안 구분(§2.7.1) | `checked` / `declared` |
| 측정 | 프로젝트 측정 명령 → 엔진 판정 | 렌더·콘솔 오류·접근성·넘침·잘림·터치 영역, 프로젝트 정책 값 기준 지표(첫 화면 정보 수, 주 행동 위치 — 정책이 있을 때만) | `measured` |
| 모델 시각 평가 | Claude(스크린샷을 직접 봄) | frontend-design 절차의 자기 비평 + 화면별 **정보 계층·강조(한 곳)·밀도·제품 정체성** 4축, 진부한 기본값 해당 여부, 결함 후보 | `visually_reviewed: model` (사람 평가가 아님을 명시) |

`critique.md` 형식(엔진이 형식만 검사):

```markdown
## V01-B / SCR-003-ST1
- **계획 대비**: 계획한 강조(점수 열)가 실제로 가장 먼저 보이는가 — 예/아니오, 근거
- **정보 계층**: …  - **강조**: …  - **밀도**: …(정책 값과 측정값 인용)  - **제품 정체성**: …
- **진부한 기본값**: 해당 항목 번호 또는 없음
- **결함 후보**: 없음 | D-1 …(측정으로 확인 필요 여부)
- **요구사항 밖 요소**: 없음 | …(unbacked_element와 대조)
```

- 자동 측정 결함 0건이나 모델 평가 통과를 **선택·승인으로 간주하지 않습니다.** 선택은 사용자만 합니다.
- frontend-design 사용 여부는 "호출했는가"가 아니라 "plan.md(색 4–6·글꼴·배치 스케치·원칙)와 대조 기록, critique.md가 형식대로 있는가"로 확인합니다(SMAPSH 실험 결론). Skill이 없으면 `reference/exploration.md`의 같은 절차를 따르고 `guidance`에 `engine-procedure`로 기록합니다.

### 2.7.1 시안 구분 기준(D2)

시안은 기본 3개, 최소 2개입니다(`variant_count`: 1개면 `too_few_variants`, 4개 이상이면 `too_many_variants` 오류). 시안끼리는 **단순 색상 차이가 아니라 구조 또는 시각 방향이** 달라야 합니다. 판정은 단계마다 다릅니다.

| 단계 | 반드시 달라야 하는 것 | 결정적 판정(엔진) | 오류 |
|---|---|---|---|
| 1차(구조) | 구조: 정보 배치·우선순위·행동 위치·화면 분할 | 시안마다 **구조 서명** = 대상별 (요소 순서, 영역 묶음, 첫 화면에 보이는 요소 집합 — 측정이 있으면 측정값, 없으면 선언 `fold: above|below`, 주 행동 위치). 두 시안의 서명이 같으면 | `variants_not_distinct` |
| 2차(시각) | 시각 방향: 타이포그래피·밀도·컴포넌트 표현·시각 계층 중 하나 이상(색상만은 불가). 구조는 **같아야** 함 | (1) 구조 지문이 승인된 02와 같음(다르면 `structure_drift`) (2) 시안마다 `distinct_axes`(`typography`·`density`·`component`·`hierarchy`·`layout_grid`)를 선언하고, 후보 테마·CSS에서 그 축의 값이 실제로 다른지 계산 — 두 시안의 차이가 색 토큰·색 값뿐이면 | `variants_color_only` |

- 축별 계산 근거: 타이포그래피(글꼴 패밀리·크기 비율·굵기 토큰), 밀도(간격 토큰·행 높이), 컴포넌트 표현(모서리·테두리·그림자·채움 방식 토큰, 컴포넌트 CSS 규칙), 시각 계층(제목 크기 단계 수·강조 요소 지정), 레이아웃 격자(열 수·최대 폭 — 2차에서는 정보 순서를 바꾸지 않는 범위).
- 모델 평가(`critique.md`)에 "시안 간 차이" 항목이 필수입니다. 엔진 판정은 최소 기준이고, "명확히 다름"의 최종 판단은 비교 페이지를 본 사용자입니다.

### 2.7.2 측정 결과와 선택(D3)

| 측정 상태 | 선택 | 기록 |
|---|---|---|
| 측정 명령 없음 / 환경 없음(`not_run`) | **허용**(경고 `measurement_not_run`). 선택 기록에 측정 없음 표시 | `measured: not_run` |
| 리포트 형식 오류·다른 실행의 리포트·시간 초과 | 그 라운드 측정이 무효. 다시 측정하거나 측정 없이 진행 여부를 사용자에게 확인(측정 무효를 숨기지 않음) | `measured: invalid` |
| **차단 결과**: 렌더 실패, 콘솔 오류, 접근성 critical, 핵심 상호작용 실패(product-build 브라우저 판정과 같은 분류) | 그 **시안은 선택 불가**(`variant_has_blocking_findings`). 다른 시안 선택은 가능 | 결과·스크린샷 해시 |
| 보고 결과: 접근성 serious, 넘침·잘림, 터치 영역 | 허용(경고, 선택 기록에 함께 남김) | 결과 |

차단된 시안을 고쳐 다시 측정해 통과하면 선택할 수 있습니다. 선택 후 그 시안을 고치면 `changed_since_choice`(§2.11)입니다.

### 2.8 선택·채택·추적성

| 명령 | 하는 일 | 기록(`design.json.exploration.<단계>`) |
|---|---|---|
| `explore-init --phase structure\|visual [--targets] [--mode ai\|reference\|mixed] [--parent <라운드>]` | 라운드 생성, 대상 계산, brief.md·manifest 골격·비교 페이지 템플릿 생성. `--parent`는 피드백 이후 새 라운드(§2.12.6) | `rounds[]`: id, phase, mode, parent, basis(승인 revision·해시, 화면 유형 파일 해시), targets, created_at |
| `explore-check --round` | 정적 검사(§2.5·§2.7.1, 레퍼런스 사용 규칙 §2.12.4) | `checks`(결과 요약·확인 수준) |
| `explore-verify --round` | 측정 명령 실행·리포트 판정, 스크린샷 해시 | `measurements`(run_id, 결과, 차단 여부, 스크린샷 해시) |
| `explore-choose --round --variant B [--per-target T1=A,T2=B] [--axes typography=B,density=A] --note "<사용자 선택 문장>"` | 선택 기록. 거부 조건: 선택 문장 없음, 승인 표현만 있고 선택 대상이 없음, 정적 검사 오류가 남은 시안, **측정 차단 결과가 있는 시안**(§2.7.2) | `choice`: id(`EXP-S01-B`), 시안(또는 대상·축별 조합), statement, feedback(FB 목록), at, **모든 시안의 파일별 해시**, 보존 집합 목록·해시(§2.11), 측정 상태, 사용한 레퍼런스·규칙(§2.12.5) |
| `explore-skip --phase --note` | 건너뜀(사용자 문장·사유) | `status: skipped` |
| `explore-adopt --round` | 선택 결과를 문서 후보로 출력(파일은 쓰지 않음): 1차는 UXD 초안, 2차는 후보 VD 블록 + 후보 테마 diff | `adoption`: 출력 해시 |
| `explore-status` | 읽기 전용 요약(보존 집합 무결성 포함) | — |

- 같은 단계에서 새 라운드를 만들면 기존 선택은 지우지 않고 `superseded_by`로 표시합니다. 제출 조건은 **가장 최근 라운드**의 선택 기준입니다.

추적성 고리:

```
기획 ID ──(1차 elements.refs)──> EXP-S01-B ──(UXD 근거)──> UXD-0xx ──(02 'UX 결정')──> SCR ──…
SCR·CMP·상태 ──(2차 elements.refs, 구조 지문)──> EXP-V01-B ──(VD 근거·관련)──> VD-0xx(승인) ──> 프리뷰 manifest vd ──> 프리뷰 승인 해시 ──> UI Brief VD ──> 증거
레퍼런스: REF-001(sha256) ──> 추출 규칙 RX-001-nn(관찰/추정·확인) ──> 사용 의도(범위) ──> 시안 provenance ──> 선택 ──> UXD/VD 근거 ──> 승인
```

- `trace --stage ux_planning`·`trace --stage design_direction`에 추가 검사: 근거에 `EXP-…`를 적은 UXD·VD는 그 ID가 기록된 선택과 같아야 함(`exploration_ref_unknown`), 선택되지 않은 시안 ID를 근거로 쓰면 오류(`exploration_ref_not_chosen`). 근거에 `REF-…`·`RX-…`를 적었으면 그 선택이 실제로 그 레퍼런스·규칙을 썼어야 함(`reference_ref_not_used`).
- 2차 채택 시 **구도 결정**(화면 유형별 배치·계층·강조)은 VD의 `관련`에 그 유형에 속한 SCR 목록을 명시합니다(새 키를 만들지 않음 → product-build UI Brief의 기존 VD 연결 규칙 그대로 동작).

### 2.9 재사용·복사 차단(D4)

차단하는 것은 **동일 파일 복사**와 **명시적 import·copy**뿐입니다. 시각적으로 비슷한 것은 차단하지 않습니다(유사도 검사 없음).

| 지점 | 검사 | 코드 |
|---|---|---|
| product-design `preview-check` | 프리뷰 파일이 `design-explore/`를 import·참조(모듈 경로·상대 경로·URL·CSS `@import`·`url()`) | `explore_reuse` 오류 |
| product-design `preview-check` | 프리뷰 파일과 시안 파일의 **정규화 후 동일**(줄 끝·끝 공백만 정규화) | `explore_copy` 오류 |
| product-build | `design-explore/` 보호 경로(`PROTECTED`: 쓰기·수정 차단), UI Plan 경로 필드·대응표의 `design-explore/` 지정, 자유 서술의 재사용 지시(M3 P0-2 규칙 그대로 확장) | `protected_path`·`preview_reuse` |
| product-build `verify`·`ui-guard` | 배치 범위 코드 파일이 시안 파일과 정규화 후 동일, 또는 `design-explore/`를 import·참조 | `explore_copy`·`explore_reuse`(차단) |
| 레퍼런스(§2.12) | 시안·프리뷰·제품 코드에 레퍼런스 원본 파일(또는 바이트 동일 사본)이 들어감 | `reference_asset_embedded` 오류 |
| manifest | `experimental: true` 필수. 승인 명령은 `design-explore/`를 어떤 승인 해시에도 넣지 않음 | `explore_not_experimental` |

테마 **값**은 채택 경로(§2.8)로만 옮깁니다. 값 복사는 차단 대상이 아닙니다.

### 2.10 변경 영향과 downstream 재승인

| 변경 | 영향 | 절차(사용자 확인 후, 기존 명령) |
|---|---|---|
| 1차 선택을 바꾸고 싶음(ux_planning 승인 전) | 해당 UXD 개정만 | 새 라운드 또는 재선택 → UXD 대체(기존 `~~UXD~~` 규칙) |
| 1차 선택을 바꾸고 싶음(승인 후) | ux_spec·design_direction·preview 승인 무효(D7 전이) | `reopen --stage ux_planning` → 재선택 → UXD 대체 → 하위 재승인. product-build 계획은 기존 M2 규칙대로 outdated |
| 2차 선택을 바꾸고 싶음(design_direction 승인 후) | 게이트 켜짐: preview 승인 무효 | `reopen --stage design_direction` → 재선택 → VD 개정 → 07 재승인 → 프리뷰 재작성·재승인 |
| 후보 테마만 다시 고름(VD 불변) | 테마 값 변경 → 프리뷰만 `theme_changed`(기존 v2 규칙) | `reopen --stage preview` → 재검증·재승인 |
| 보존 집합 파일이 선택 이후 바뀜 | 승인에는 영향 없음(시안은 승인 대상 아님). 선택 기록 무결성만 | `explore-status`가 `changed_since_choice` 경고. 근거로 쓰인 선택이면 재선택 권장 |
| 레퍼런스 철회(권리·개인정보 문제 발견) | 승인에는 자동 영향 없음 | `explore-ref withdraw` 기록 → 그 레퍼런스를 쓴 선택을 근거로 한 UXD·VD를 `refs`로 보고 → 사용자가 재선택·reopen 결정 |
| `impact --design` | 사실 종류 `exploration_choice` 추가: 1차 → ①, 2차 구도 → ④(VD), 2차 테마 값 → ③ | 기존 분류·재승인 단계 계산 그대로 |

### 2.11 Git 보존 정책(D6)

엔진은 Git 명령을 실행하지 않습니다. 대신 **보존 집합**을 정의하고, `design-explore/.gitignore`를 생성·갱신하며, 선택 기록에 보존 집합의 파일별 해시를 남깁니다.

| 분류 | 파일 | 기본 |
|---|---|---|
| 보존(추적) | `explore.manifest.json`, 라운드 `brief.md`, **선택 시안의** `plan.md`·렌더 산출물(HTML/CSS 또는 렌더러별 정의 파일), `critique.md`, `selection/selection.json`, `selection/evidence/*`(핵심 시각 증거), 레퍼런스 `reference.json`·`extraction.json`(§2.12) | 추적 |
| 제외 | 선택되지 않은 시안 디렉터리, `shots/`(측정 산출 전체), `compare.html`(재생성 가능), 임시 파일, 레퍼런스 원본 이미지(§2.12.7) | `.gitignore` |

- **핵심 시각 증거**: 선택 시안의 대상 × 뷰포트 스크린샷(측정이 있으면 측정 산출물, 없으면 사람이 저장한 캡처를 `explore-choose --evidence <파일>`로 등록). 렌더러별: html은 스크린샷, figma는 노드 링크 + 스크린샷. 개수 = 대상 수 × 뷰포트 수(대량 아님). 크기 상한은 프로젝트 정책(`config.exploration.evidence_max_bytes`, 기본 없음 → 경고만).
- 선택 기록에는 **모든 시안**(제외되는 시안 포함)의 파일별 해시가 남습니다. 제외된 시안은 "기록상 존재, 파일 미보존"으로 표시하고 무결성 검사 대상이 아닙니다(C12).
- `explore-choose`는 보존 집합 파일이 하나라도 없으면 거부합니다(`retention_incomplete`): 선택 시안의 plan·render, critique, 증거 1개 이상(측정이 `not_run`이면 사람 캡처 1개 이상).
- 프로젝트 정책으로 제외 시안도 추적할 수 있습니다(`config.exploration.keep_unselected: true`).

### 2.12 Reference-driven Design(레퍼런스 기반 탐색)

design_exploration의 확장입니다. 별도 승인 단계·독립 Skill을 만들지 않고, 같은 라운드·선택·제출 조건을 씁니다.

#### 2.12.1 세 가지 탐색 방식(라운드 `mode`)

| mode | 시안의 출처 | 조건 |
|---|---|---|
| `ai` | 요구사항(승인 문서)에서 생성 | 기존 그대로 |
| `reference` | 사용자 레퍼런스에서 추출한 규칙을 **의도한 범위만** 반영 | 의도(intent)가 기록된 레퍼런스 1개 이상 |
| `mixed` | AI 후보 + 레퍼런스의 특정 요소를 축별로 조합 | 시안마다 축별 출처(`axis_sources`)를 선언 |

- 레퍼런스는 초기 탐색에서도, 기존 시안 피드백 이후에도 넣을 수 있습니다(후자는 `--parent`로 새 라운드, §2.12.6).
- D2 유지: 어느 mode든 시안은 최소 2개이고 서로 명확히 달라야 합니다. `reference` mode에서도 "레퍼런스에 충실한 해석"과 "제품 맥락을 더 반영한 해석"처럼 **해석이 다른** 시안을 둡니다. 레퍼런스 하나를 그대로 옮긴 시안 1개만 내는 방식은 지원하지 않습니다(충돌 R4).

#### 2.12.2 레퍼런스 등록과 분석

```
design-explore/references/
  .gitignore                 # 원본 이미지 기본 제외(엔진 생성)
  REF-001/
    original.<ext>           # 사용자 제공 원본(기본 Git 제외)
    reference.json           # 등록 기록(추적)
    extraction.json          # 추출된 디자인 규칙(추적)
```

`reference.json`(`design-reference/v1`, `explore-ref add`가 작성):
`{id, file, sha256, bytes, media_type, source: {kind: user_file|screenshot|export, note}, rights: {statement, basis: own|licensed|reference_only|unknown}, privacy: {screening: {by: model|user, result: none|suspected|confirmed, note}, decision: keep|redact_requested|hash_only}, track_original: false, added_at, added_in_round}`

`extraction.json`(`design-reference-extract/v1`, Claude가 이미지를 보고 작성, 엔진은 형식·참조만 검사 — 특정 이미지 모델 비종속):

| 축(`axis`) | 추출 내용 |
|---|---|
| `palette` | 색 역할(배경·표면·강조·텍스트·상태)과 값 |
| `typography` | 제목·본문·보조의 상대 크기 단계, 굵기 대비, 글꼴 계열(세리프·산세리프·고정폭 수준까지 — 글꼴 이름은 추정) |
| `layout` | 영역 구성, 정보 계층(무엇이 먼저 보이나), 열·격자 |
| `components` | 카드·버튼·탭·목록 행·입력의 표현(모서리, 테두리, 채움, 그림자) |
| `spacing_density` | 여백 규칙, 행 높이 감, 첫 화면 정보량 |
| `emphasis_mood` | 강조 위치·방식, 시각적 분위기(형용사 + 근거가 되는 관찰) |
| `navigation` | 내비게이션 패턴(하단 탭·상단 탭·사이드·없음) |

규칙 항목 형식: `{id: "RX-001-07", axis, statement, value?, basis: "observed" | "estimated", confidence: "high" | "medium" | "low", confirm: "not_required" | "required" | "confirmed" | "rejected", evidence: "<이미지의 어느 부분을 보고 판단했는지>"}`

- `observed`: 이미지에서 직접 보이는 사실(예: "하단에 아이콘+라벨 탭 4개"). `estimated`: 값 추정(색 hex, px 크기, 글꼴 이름, 비율).
- **확인 규칙**: `estimated` 이면서 `confidence ≠ high`인 항목은 `confirm: required`. 시안이 `required` 상태 항목을 쓰면 `explore-check`가 `reference_unconfirmed` 오류. 사용자가 `explore-ref confirm --items … --decision confirmed|rejected --note`로 결정합니다.
- **제외 기록**: 이미지 속 실제 텍스트·데이터·로고·브랜드 자산·인물은 규칙으로 추출하지 않고 `excluded: [{kind: text|data|logo|brand_asset|person, note}]`에 **종류만** 기록합니다(원문 텍스트를 옮겨 적지 않음).

#### 2.12.3 사용자 의도(참고 범위) 기록

`explore-ref intent --round S02 --ref REF-001 --scope layout,navigation [--items RX-001-03,RX-001-05] [--ref REF-002 --scope palette,typography] --note "<사용자 문장>"`

| 범위 예 | `--scope` |
|---|---|
| 분위기만 | `emphasis_mood` |
| 레이아웃만 | `layout`(+ 필요하면 `navigation`) |
| 색상·타이포그래피만 | `palette,typography` |
| 카드·버튼 스타일만 | `components` |
| 여러 이미지 조합 | 레퍼런스별로 다른 범위(같은 축을 두 레퍼런스에 주면 `axis_conflict` 오류 — 하나만 고르게 함) |

- 사용자 문장이 없으면 거부합니다. 엔진은 의도를 추정해 기록하지 않습니다.
- **단계별 적용 가능 범위(충돌 R3·R8 해결)**:
  - 1차(구조): `layout`, `navigation`, `spacing_density`, `emphasis_mood`(강조 위치만). `palette`·`typography`·`components`는 **2차로 이월**(기록은 하되 1차 시안에 쓰지 않음, 경고 `scope_deferred_to_visual`).
  - 2차(시각): 모든 축. 단 `layout`·`navigation`은 **승인된 구조를 바꾸지 않는 범위**(격자·최대 폭·간격·영역 표현)만. 정보 순서·화면 구성·내비게이션 구조를 바꾸면 `structure_drift`이며, 사용자가 원하면 CR(①)로 UX Spec reopen을 안내합니다.

#### 2.12.4 시안 생성 규칙과 검사

manifest의 시안에 출처를 선언합니다(D5 공통 계약 확장, 하위 호환):

```json
"B": { "mode": "mixed",
       "axis_sources": { "layout": "ai", "typography": "REF-002", "components": "REF-001" },
       "rules": ["RX-001-04", "RX-002-01", "RX-002-03"],
       "reinterpretation": "레퍼런스의 카드 표현을 유지하되 제품의 정보 밀도(정책 값)에 맞춰 행 높이를 줄임" }
```

`explore-check` 추가 검사:

| 검사 | 오류 |
|---|---|
| `rules`의 ID가 존재하고, 그 레퍼런스의 의도 범위·단계 적용 범위 안의 축인가 | `reference_scope_violation` |
| 확인이 필요한 추정 값을 썼는가 | `reference_unconfirmed` |
| `rejected` 항목을 썼는가 | `reference_rule_rejected` |
| 레퍼런스 원본(또는 바이트 동일 사본)·잘라 낸 영역 파일이 시안에 포함됐는가(파일 해시 대조) | `reference_asset_embedded` |
| 요소 근거(`elements.refs`)는 승인 문서 ID만 — 레퍼런스에만 있는 기능은 `unbacked_element`로 이미 차단 | (기존) |
| 철회된 레퍼런스를 썼는가 | `reference_withdrawn` |

- 이미지 속 텍스트·데이터는 시안에 쓰지 않습니다. 시안의 문구·데이터는 승인 문서와 `sample` 표시 데이터만 씁니다. 엔진은 텍스트 일치를 판정하지 않으므로(OCR 비종속), `critique.md`에 "레퍼런스 문구·데이터·브랜드 자산 미사용"을 필수 확인 항목으로 둡니다(`visually_reviewed: model`).
- `reinterpretation`(제품에 맞게 무엇을 바꿨는지) 필수 — 레퍼런스를 쓴 시안에서 비어 있으면 오류 `reinterpretation_missing`.

#### 2.12.5 선택과 추적

`explore-choose`가 선택 기록에 다음을 함께 남깁니다: 사용한 레퍼런스 ID·sha256, 사용한 규칙 ID와 그 시점의 확인 상태, 의도 기록 ID, 축별 출처. UXD·VD 근거는 `EXP-V02-B (REF-001: RX-001-04 · REF-002: RX-002-01)` 형식을 허용하며 `trace`가 대조합니다(§2.8).

#### 2.12.6 피드백 이후 레퍼런스 추가

"이 시안들이 마음에 들지 않는다 + 이 이미지처럼" → `explore-init --phase … --mode reference|mixed --parent S01` → 새 라운드 S02. 이전 라운드의 피드백(FB)은 새 라운드 brief에 연결되고, 이전 선택이 있었다면 `superseded_by: S02`. 단계 상태(ux_planning·design_direction)는 바뀌지 않습니다(제출 전이면 그대로 in_progress, 승인 후면 기존 reopen 필요 — §2.10).

#### 2.12.7 보존·저작권·개인정보 정책

| 항목 | 정책 |
|---|---|
| 원본 보존 | 프로젝트 안 `design-explore/references/REF-xxx/original.<ext>`에 복사(사용자 원본 경로는 기록하지 않음 — 개인 경로 노출 방지). **기본 Git 제외.** 추적하려면 `explore-ref track --ref --note`이며 조건: `rights.basis ∈ {own, licensed}` **그리고** `privacy.result = none`(사용자 확인) |
| 해시 | sha256·크기·형식은 항상 `reference.json`(추적)에 남아, 원본이 없어도 "어떤 이미지였는지" 대조 가능 |
| 원본 삭제 | 사용자가 지울 수 있음(엔진은 지우지 않음). 지우면 `original_missing` 표시, 추출·선택 기록은 유지 |
| 저작권·라이선스 | 레퍼런스는 **참고 전용**. 원본·잘라 낸 이미지·로고·아이콘·일러스트·사진을 시안·프리뷰·제품에 넣지 않음(§2.9 `reference_asset_embedded`). `rights.basis = unknown`이면 등록은 허용하되 경고(`reference_rights_unknown`)를 선택 기록·검토 묶음에 남김. 상표·고유 브랜드 표현(로고형 워드마크, 고유 일러스트 스타일)을 재현하지 않도록 `critique.md` 확인 항목 |
| 개인정보 | 등록 시 Claude가 이미지를 보고 사람 얼굴·이름·연락처·계정·메시지 등 포함 여부를 점검하고 결과를 사용자에게 보여 줌(`screening.by: model`). 의심·확인되면: 추적 불가, 사용자가 가린 이미지로 교체하거나(`redact_requested`) 해시만 남기고 원본 삭제(`hash_only`) 선택. 추출 규칙·`excluded`에 개인정보 원문을 쓰지 않음 |
| 외부 전송 | 엔진은 이미지를 외부 서비스로 보내지 않음. 렌더러·측정 어댑터가 외부 서비스를 쓰는 경우 레퍼런스 원본을 입력으로 넘기지 않음(어댑터 계약에 명시) |
| 형식·크기 | png·jpg·webp(그 밖은 거부), 크기 상한은 프로젝트 정책(기본 없음 → 큰 파일 경고) |

#### 2.12.8 기존 계약과의 호환

- `design-explore/v1` manifest에 `mode`, `axis_sources`, `rules`, `reinterpretation`, 라운드 `parent`, 최상위 `references` 목록을 **선택 필드로 추가**합니다. 없으면 `mode: ai`로 해석 → EX2에서 만든 manifest가 그대로 유효(버전 올리지 않음).
- 승인 게이트·해시·revision: 변경 없음. 레퍼런스·추출 파일은 어떤 승인 해시에도 들어가지 않습니다.
- 기존 v2 자동 적용 금지: 레퍼런스 명령은 탐색이 켜진 단계에서만 동작(`exploration_unavailable`).

## 3. 변경될 파일·명령·상태 스키마(구현 시)

### 3.1 파일

| 파일 | 변경 |
|---|---|
| `skills/product-design/scripts/pd_explore.py` | **새 모듈**: 대상 선정·화면 유형, manifest 공통 계약·렌더러별 검증, 시안 구분, 리포트 판정, 선택·보존·채택 |
| `skills/product-design/scripts/pd_reference.py` | **새 모듈**: 레퍼런스 등록·해시·형식, 추출 계약 검사, 의도·확인 기록, 사용 규칙 검사 |
| `skills/product-design/scripts/product_design.py` | 명령 추가(§3.2), `start --workflow`, `migrate` 기본 활성 표시, submit 조건 연결 |
| `skills/product-design/scripts/pd_core.py` | `existing_design_paths`에 `design-explore/`, `trace` 추가 검사, `state_shape_problems`에 `exploration` |
| `skills/product-design/scripts/pd_impact.py` | 사실 종류 `exploration_choice` |
| `skills/product-design/SKILL.md` | 2단계(UX Planning)·v2 절에 탐색·레퍼런스 절차, 규칙 8 보완(`design-explore/`) |
| `skills/product-design/reference/exploration.md` | **새 문서**: 절차(frontend-design 사용·대체 절차), 계약, 시안 구분, 품질 축, 선택 문장 규칙, 레퍼런스 분석·의도·권리·개인정보 절차 |
| `skills/product-design/reference/design-state.md`·`preview.md`·`change-impact.md` | 상태 구조·전이·재사용 검사·영향 분류 |
| `skills/product-design/templates/explore/` | manifest·brief·plan·critique·compare 템플릿(HTML/CSS만), `screen-types.default.json`, `extraction.example.json` |
| `skills/product-build/scripts/pb_core.py`·`pb_ui.py`·`pb_uiguard.py`·`product_build.py` | `PROTECTED`에 `design-explore/`, 재사용 검사 대상 확장, verify·ui-guard의 동일 파일·명시 참조 검사 |
| `skills/product-build/reference/ui.md` | 보호 경로·재사용 검사 표 |
| `tests/product_design_explore_test.py`, `tests/product_design_reference_test.py` | **새 테스트** |

### 3.2 명령

- 탐색: `explore-config`, `explore-init`, `explore-check`, `explore-verify`, `explore-choose`, `explore-skip`, `explore-adopt`, `explore-status`
- 레퍼런스: `explore-ref add|list|confirm|intent|track|withdraw`
- 기존 명령 확장: `start --workflow v1|v2`(기본 v1, 기존 호출과 같음), `migrate`(승인 전 전환 시 탐색 기본 활성 표시), `submit`(제출 조건), `trace`(근거 검사), `preview-check`(재사용·복사)

### 3.3 상태 스키마(`design.json`, 추가만)

```json
"config": { "workflow": "v2", "gates": { "design_direction": true },
            "exploration": { "structure": { "enabled": true }, "visual": { "enabled": true },
                             "renderer": "html", "measure_cmd": null, "max_targets": null,
                             "keep_unselected": false, "evidence_max_bytes": null, "reference_max_bytes": null,
                             "source": "start_v2 | migrate_pre_approval | explore-config" } },
"exploration": {
  "structure": { "status": "not_started|in_progress|chosen|skipped", "rounds": [ … ], "choice": { … } | null, "skip": { … } | null },
  "visual":    { "status": "…", "rounds": [ … ], "choice": null, "adoption": null },
  "references": { "REF-001": { "sha256": "…", "added_at": "…", "rights": "own", "privacy": "none", "tracked": false,
                               "extraction_hash": "…", "confirmations": [ … ], "withdrawn": null } },
  "intents": [ { "id": "INT-001", "round": "S02", "refs": [ { "ref": "REF-001", "scope": ["layout"], "items": [] } ], "statement": "…", "at": "…" } ],
  "activations": [ { "phase": "visual", "action": "enable|disable", "at": "…", "statement": "…", "stage_status": "approved" } ]
}
```

- `config.exploration`이 없으면 탐색 꺼짐(기존 프로젝트 판정 그대로). `references`·`intents`가 없으면 레퍼런스 미사용.
- `state_shape_problems`: `exploration`이 있으면 형태 검사, 없으면 문제 아님.
- 승인 기록(`stages.*.approved`)에는 아무 키도 추가하지 않습니다. design_direction 승인 시 선택 ID·보존 집합 해시를 **별도 키** `stages.design_direction.exploration_basis`(ux_planning은 `stages.ux_planning.exploration_basis`)에 남겨 추적만 합니다(승인 판정에 쓰지 않음).

## 4. 호환성과 마이그레이션

| 대상 | 전략 |
|---|---|
| v1 프로젝트 | 변화 없음. 탐색·레퍼런스 명령 거부 |
| 기존 v2 프로젝트(SMAPSH 포함) | `config.exploration` 없음 → 꺼짐. `check`·제출·승인 동작 동일. 쓰려면 `explore-config --enable`(명시적). 2차는 게이트가 켜져 있어야만 가능(D7). 해당 단계의 다음 reopen부터 적용 |
| 승인 기록이 있는 프로젝트 | 자동 적용 없음. 재개(reopen)는 사용자 결정이며 기존 무효화 규칙이 그대로 적용됨을 먼저 안내 |
| 신규 v2 | `start --workflow v2` 또는 승인 전 전환에서 기본 켜짐(계획 출력에 표시하고 사용자 확인) |
| EX2에서 만든 manifest | 레퍼런스 필드 없음 → `mode: ai`로 해석, 그대로 유효 |
| product-build | `design-explore/` 보호·복사 검사 추가. 기존 계획·검증 기록 영향 없음(그 경로를 쓰는 배치가 없었으므로) |
| 되돌리기 | `explore-config --disable`(기록은 보존). 상태 되돌리기 명령은 두지 않음(기존 v2 정책과 같음) |

SMAPSH는 실제 적용 사례로만 씁니다: 이미 design_direction·preview 승인 상태이므로, 적용하려면 사용자가 `reopen --stage design_direction`을 결정해야 하고 프리뷰 재승인·Build 재검증이 연쇄됩니다. 엔진에는 SMAPSH 값(600px 한 열, 행 높이 등)을 넣지 않습니다.

## 5. 구현 계획(Milestone)

### 5.1 의존 관계 재검토

- 이전 순서(EX2 정적 검사 → EX3 측정 → EX4 선택)는 "선택"이 맨 뒤라 첫 실사용 흐름(초안 → 시안 3개 → 브라우저 비교 → 선택 → UXD)까지 4개 MS가 필요했습니다.
- D3(측정 없이 경고 후 선택 허용) 덕분에 **측정은 첫 흐름의 필수 조건이 아닙니다.** 반면 상태 안전(활성화·제출 조건·경로 보호)과 선택 기록 무결성(D6 보존)은 첫 흐름에서 빠질 수 없습니다.
- 그래서 1차(구조) 탐색을 **수직 슬라이스**로 묶어 앞으로 당기고, 측정·2차·레퍼런스·재사용 완성을 그 뒤로 둡니다. 레퍼런스는 권리·개인정보 처리가 함께 들어가야 하므로 AI 흐름이 검증된 다음 MS로 분리하되, manifest 필드는 EX2에서 예약해 계약을 깨지 않습니다.

```
EX1 상태·활성화·경로 안전 ─┬─> EX2 1차 탐색 슬라이스(AI) ──> EX3 레퍼런스 MVP(1차) ─┐
                           │                                                      ├─> EX5 2차 탐색(AI+레퍼런스) ─> EX6 재사용·복사 차단 완성 ─> EX8 E2E
                           └─> EX4 측정(D3 차단) ────────────────────────────────┘                                 EX7 렌더러 어댑터·Figma ─┘
```

### 5.2 Milestone

| MS | 내용 | 완료 조건 | 자동 테스트 기준 |
|---|---|---|---|
| **EX0** 설계 확정 | 이 문서(D1–D7, Reference-driven) | 사용자 확정 | — |
| **EX1** 상태·활성화·경로 안전(선행 필수) | `config.exploration` 스키마, `start --workflow v2`(게이트 켜짐·탐색 켜짐), 승인 전 `migrate` 기본 활성, `explore-config`(D7 게이트 필수), `state_shape_problems`, `existing_design_paths`에 `design-explore/`, product-build `PROTECTED`에 `design-explore/`, `design-explore/.gitignore` 생성 규칙 | 기존 프로젝트·상태 파일에서 동작 변화 0. 승인·해시·revision 필드 불변을 쓰기 전후 비교로 보장 | 기존 product-design 5개·product-build 14개·start·init 전 묶음 통과 / v1·기존 v2 상태 파일에서 탐색 꺼짐 / 신규 v2 켜짐 / 승인 후 migrate 꺼짐 / 게이트 꺼진 v2에서 `--enable visual` 거부 / enable·disable 전후 승인 기록 바이트 비교 동일 / product-build가 `design-explore/` 쓰기 거부 |
| **EX2** 1차 탐색 슬라이스(AI) — **첫 구현 범위** | `explore-init --phase structure`(기획 ID 앵커 대상 계산, 화면 유형 기본 목록·프로젝트 파일), html 렌더러 계약(`elements`·표지 대조), `explore-check`(근거 ID·`unbacked_element`·`data-sample`·시안 수·구조 서명 구분), `compare.html` 생성, `explore-choose`(측정 없음 경고, 보존 집합·`retention_incomplete`, 파일별 해시, 선택 문장 규칙), `explore-skip`, `explore-status`, ux_planning **제출 조건**, `trace --stage ux_planning` 근거 검사, `reference/exploration.md`·SKILL.md 2단계 절차(frontend-design 사용·대체 절차), manifest 레퍼런스 필드 예약 | 신규 v2 픽스처에서: 초안 → 시안 3개 → 비교 페이지 → 선택 → UXD(근거 EXP-S01-x) → 제출 → 확정까지 스크립트로 통과. 탐색 꺼진 프로젝트는 기존과 동일 | 근거 없는 버튼 `unbacked_element` / 없는 기획 ID 오류 / `data-sample` 누락 / 시안 1개·4개 오류 / 두 시안 구조 서명 동일 `variants_not_distinct` / 선택 문장 없음·"좋네요" 거부 / 정적 오류 시안 선택 거부 / 보존 파일 누락 `retention_incomplete` / 측정 없음 경고 후 선택 / 탐색 없이 제출 거부·skip(문장) 통과 / UXD 근거 불일치·미선택 시안 오류 / 선택 후 보존 파일 변경 `changed_since_choice` / `.gitignore`에 미선택 시안·`shots/` 포함 / 1차 재선택(승인 후) reopen 안내 |
| **EX3** 레퍼런스 MVP(1차 범위) | `explore-ref add`(복사·sha256·형식·권리·개인정보 점검 기록·원본 Git 제외), 추출 계약 검사(`observed`/`estimated`·확인 규칙·`excluded` 종류만), `confirm`, `intent`(사용자 문장·축 충돌·단계 범위 이월), `withdraw`, `track` 조건, mode `reference`·`mixed`, 시안 `rules`·`axis_sources`·`reinterpretation` 검사, `reference_asset_embedded`(해시), 선택 기록·`trace`에 레퍼런스 연결, `--parent` 피드백 라운드 | 신규 v2 픽스처에서: AI 라운드 불만족 → 이미지 등록 → 추출 → 의도(레이아웃만) → 새 라운드 → 선택 → UXD 근거에 REF·RX까지 이어짐 | 지원하지 않는 형식 거부 / 해시 기록 / 원본 기본 미추적·`track` 조건(권리 unknown 또는 개인정보 의심이면 거부) / 추정·저신뢰 항목 확인 전 사용 `reference_unconfirmed` / rejected 사용 오류 / 의도 범위 밖 축 `reference_scope_violation` / 1차에서 palette 의도 → 이월 경고 / 같은 축 두 레퍼런스 `axis_conflict` / 원본 바이트 사본을 시안에 넣음 `reference_asset_embedded` / 재해석 누락 / 철회 레퍼런스 사용 거부 / 레퍼런스 없는 기존 manifest 유효 |
| **EX4** 측정(D3) | `explore-verify`, `design-explore-report/v1` 판정(`pb-ui-report/v1`과 같은 분류), 차단 시안 선택 거부, 측정 스크린샷을 핵심 증거로 등록 | 리포트 대역으로 판정 | 통과·차단(렌더 실패·콘솔 오류·critical)·`not_run`·형식 오류·다른 run_id·스크린샷 경로 밖 / 차단 시안 선택 거부·다른 시안 선택 허용 / 재측정 통과 후 선택 허용 / 두 Skill 테스트에 같은 리포트 예시 고정 |
| **EX5** 2차 탐색(AI + 레퍼런스 전 축) | `explore-init --phase visual`(구성 서명 기반 대표 화면), 구조 지문 `structure_drift`, `distinct_axes`·`variants_color_only`, 후보 테마(04 토큰 이름만, 아니면 ②), 레퍼런스 palette·typography·components 반영, 축별 조합 선택, `explore-adopt`(후보 VD·테마 diff), design_direction **제출 조건**, `trace --stage design_direction`, `impact` 사실 종류 | 신규 v2 픽스처에서: UX Spec 승인 → 2차 → 선택(조합) → 후보 VD → VD별 결정 → 07 제출·승인 | 정보 행 추가 `structure_drift` / 색만 다른 시안 오류 / 04에 없는 토큰 ② / 레퍼런스 레이아웃이 구조를 바꾸면 drift / 후보 VD만 생성(승인 아님) / 탐색 없이 07 제출 거부 / 2차 재선택(승인 후) preview 무효 안내 / 게이트 꺼짐 상태 복원 시 `exploration_gate_mismatch` |
| **EX6** 재사용·복사 차단 완성 | `preview-check` `explore_reuse`·`explore_copy`, product-build UI Plan·verify·ui-guard 동일 파일·명시 참조 검사, 구도 VD가 UI Brief 화면별로 도달 | 프리뷰·제품 코드 복사·import 차단, 시각적 유사는 통과 | 프리뷰 import·동일 파일 오류 / 제품 코드 동일 파일·import 차단 / 다른 파일(비슷한 모양) 통과 / 레퍼런스 원본 사본 차단 / 구도 VD가 Brief에 포함 / product-build 기존 회귀 |
| **EX7** 렌더러 어댑터·Figma | 코드 어댑터 계약(정적 HTML 산출), Figma 렌더러별 검증(`declared`), 어댑터의 레퍼런스 외부 전송 금지 명시 | 문서·계약 검사 | figma manifest 필수 필드 누락 오류 / `declared` 수준 기록 / 어댑터 산출 HTML 대조 |
| **EX8** 실전 E2E | §6.2 | §6.2 완료 기준 | — |

**첫 구현 Milestone = EX1 + EX2**(EX1은 안전 선행 작업이라 생략하지 않음). 이 둘이 끝나면 "UX Planning 초안 → 레이아웃 후보 3개 → 브라우저 비교 → 사용자 선택 → UXD 반영"을 실제 프로젝트에서 쓸 수 있습니다.

## 6. 검증 계획

### 6.1 자동 테스트(브라우저·이미지 모델 없이)

- `tests/product_design_explore_test.py`: EX1·EX2·EX4·EX5·EX6 기준(§5.2 표)
- `tests/product_design_reference_test.py`: EX3 기준. 이미지는 테스트가 만드는 작은 PNG(표준 라이브러리로 생성)와 바이트 사본·형식 위조 파일. 추출 결과는 고정 JSON 픽스처(모델 호출 없음)
- 회귀: 기존 product-design 5개·product-build 14개·start 4개·init·generality 묶음 전부

### 6.2 실제 E2E(신규 프로젝트, 사용자 승인 하에)

**AI 흐름**
1. `start --workflow v2` → 1차: 대상 장면 2개 × 시안 3개(HTML) → 비교 페이지를 브라우저로 열어 사용자 선택 → UXD 확정.
2. UX Spec 승인 → 2차: 대표 화면 2–3개 × 시안 3개(구조 고정) → 측정·모델 평가 → 사용자 선택(조합) → 후보 VD·테마 → VD별 결정 → 07 승인.
3. 프리뷰를 승인 VD·테마로 **새로** 작성(복사 시도가 차단되는지 한 번 확인) → 승인 → Build에서 구도 VD 반영·`design-explore/` 차단 확인.

**레퍼런스 흐름**(사용자가 준비한 실제 이미지)
| # | 시나리오 | 확인 |
|---|---|---|
| R-E1 | 1차 AI 시안에 불만족 → 직접 만든 앱 화면 캡처(권리 own) 등록 → "레이아웃만" | 추출의 관찰/추정 구분, 확인 질문, 새 라운드 시안이 레이아웃 축만 따름, UXD 근거에 REF·RX |
| R-E2 | 2차에서 공개 웹사이트 캡처(권리 unknown) 2장 → 한 장은 색·타이포, 다른 한 장은 카드 스타일 | 축별 조합, `reference_rights_unknown` 경고 기록, 원본 미추적, 로고·문구 미복제(모델 평가 확인) |
| R-E3 | 사람 이름·연락처가 보이는 화면 캡처 | 개인정보 의심 보고, 추적 불가, `hash_only` 또는 가린 이미지 교체 흐름 |
| R-E4 | 레퍼런스 레이아웃이 승인된 구조를 바꾸는 경우(2차) | `structure_drift` → CR(①) 안내, 승인 상태 불변 |
| R-E5 | 선택 후 레퍼런스 철회 | `withdraw` 기록, 영향받는 UXD·VD 보고, 승인 상태 자동 변경 없음 |

완료 기준: 두 탐색과 레퍼런스의 기록·근거 ID·해시가 끊김 없이 이어지고, 기존 승인·해시 규칙 위반 0, 복사·자산 삽입 시도 차단, 원본 이미지가 Git 추적에 들어가지 않음(조건 충족 시 제외), 사용자가 비교 근거(증거·평가)를 보고 선택했음이 기록됨.

## 7. 미결정 사항과 위험

### 7.1 EX0 결정 상태

D1–D7은 §0.1로 확정되었습니다. Reference-driven Design 추가로 생긴 미결정 사항:

| # | 미결정 | 권장 |
|---|---|---|
| U1 | 레퍼런스 원본을 프로젝트 안(Git 제외)에 복사할지, 프로젝트 밖 경로를 기록만 할지 | 프로젝트 안 복사(해시 재검증 가능), 사용자 원본 경로는 기록하지 않음 |
| U2 | 색 팔레트를 엔진이 결정적으로 계산할지(이미지 디코딩 필요 — 표준 라이브러리로는 PNG만 가능) | MVP는 모델 추출(`estimated`)만. 결정적 팔레트 계산은 후속 선택 어댑터 |
| U3 | 레퍼런스 1개당 크기·개수 상한 기본값 | 엔진 기본값 없음, 프로젝트 정책(큰 파일 경고만) |
| U4 | 개인정보 점검을 모델 점검만으로 허용할지 | 모델 점검 + 사용자 확인(둘 다 기록). 의심 시 추적 불가는 고정 규칙 |

### 7.2 MVP와 후속 확장

| 구분 | 범위 |
|---|---|
| **MVP**(EX1–EX3, EX5의 레퍼런스 축 포함 전까지) | 1차 탐색 AI·레퍼런스·혼합, 이미지 등록·해시·권리·개인정보, 추출 계약(관찰/추정·확인), 의도 범위, 사용 규칙 검사, 선택·보존·추적, 피드백 후 새 라운드 |
| **2차에 포함**(EX5) | 레퍼런스 palette·typography·components → 후보 테마·VD, 축별 조합 |
| **후속 확장** | 결정적 팔레트·간격 측정 어댑터(U2), 레퍼런스 영역 지정(이미지의 일부 영역만 참고 — 좌표 기록), Figma 프레임을 레퍼런스로 등록, 레퍼런스 간 비교 화면, 같은 레퍼런스의 프로젝트 간 재사용 금지 정책, 외부 규칙 데이터(WF-D16, UI UX Pro Max 등) |

### 7.3 위험

| 위험 | 대응 |
|---|---|
| 시안 품질 상한은 모델 판단 | 엔진은 비교 가능성·측정·기록·추적만 보장한다고 문서에 명시. 사람 선택이 최종 |
| frontend-design 업데이트로 지침이 바뀜 | `guidance.version` 기록. 엔진은 산출물 형식으로만 검사. 지침이 명세와 충돌하면 명세 우선(SMAPSH UXD-074 사례) |
| 탐색 단계가 진행 시간을 늘림 | 대상 수·시안 수 정책, `explore-skip`(사용자 문장) |
| 1차 장면이 SCR 없이 모호 | 기획 ID 앵커 + 선택 결과를 UXD로만 기록. 화면 확정은 UX Spec 구조 확인 |
| 구조 서명·축 차이 판정이 실제 "명확한 차이"를 다 잡지 못함 | 엔진 판정은 최소 기준. 모델 평가의 "시안 간 차이" 항목과 사용자 비교가 최종 |
| 레퍼런스 추출 값의 오판(색·크기 추정) | `estimated`·신뢰도·확인 규칙. 확인 전 사용 차단 |
| 레퍼런스 디자인의 과도한 모방(저작권·상표) | 자산 삽입 차단(바이트), 재해석 필수 기록, 모델 평가 확인 항목. 시각적 유사성 자체는 D4대로 차단하지 않으므로 최종 판단은 사용자 책임임을 등록 시 안내 |
| 개인정보 이미지 유출 | 원본 기본 Git 제외, 의심 시 추적 불가, 외부 전송 금지, 추출에 원문 미기록 |
| 텍스트·데이터 복제를 엔진이 기계적으로 못 잡음(OCR 비종속) | 요소 근거 규칙(`unbacked_element`, `sample`)과 모델 평가 확인 항목으로 보완. 한계로 명시 |
| Skill 간 계약 중복(`design-explore-report/v1` ↔ `pb-ui-report/v1`) | 필드 동일하게 유지하고 두 Skill 테스트에 같은 리포트 예시를 고정 |
| 기존 프로젝트 적용 시 연쇄 재승인 | 자동 적용 없음. 재개 전에 영향(무효화 단계·재검증 배치)을 `impact`로 먼저 보여 줌 |

## 8. Reference-driven Design 통합 시 EX0 설계와의 충돌 정리

| # | 충돌 | 영향 | 해결 |
|---|---|---|---|
| R1 | D4(시각 유사성 비차단) vs 이미지 자산·브랜드 복제 금지 | 유사성만으로는 막지 않으므로 과도한 모방 가능 | 바이트 수준 자산 삽입은 차단(`reference_asset_embedded`), 재해석 기록 필수, 모델 평가 확인. 시각 유사성은 계속 비차단 |
| R2 | D6(선택 시안 증거 Git 보존) vs 이미지 권리·개인정보 | 원본을 보존하면 저작권·개인정보 위험 | 원본은 기본 Git 제외, 해시·추출만 추적. 추적은 권리·개인정보 조건 충족 시 명시 명령으로만 |
| R3 | 2차 구조 고정(`structure_drift`) vs "레이아웃만 참고" | 2차에서 레이아웃 참고가 구조를 바꿀 수 있음 | 2차의 layout·navigation 범위는 비구조 축(격자·간격·영역 표현)으로 한정. 구조 변경은 CR(①) |
| R4 | D2(최소 2개, 명확히 다름) vs "이 이미지대로 하나만" | 단일 재현 요구와 충돌 | 해석이 다른 2개 이상을 요구. 단일 재현 모드는 두지 않음 |
| R5 | 축별 조합 선택(`--axes`) vs 레퍼런스 축 | 축 이름 불일치 | 레퍼런스 축 목록을 시안 축(`distinct_axes`)과 같은 어휘로 통일(palette·typography·components·spacing_density·layout·navigation·emphasis_mood) |
| R6 | 피드백 후 이미지 추가 vs 이미 선택된 라운드 | 선택 기록 덮어쓰기 위험 | 새 라운드(`--parent`), 기존 선택 `superseded_by` 보존 |
| R7 | 이미지 분석 vs 특정 이미지 모델 비종속 | 분석 품질이 모델마다 다름 | 엔진은 추출 계약만 검사(관찰/추정·신뢰도·확인). 추출 주체는 기록(`extracted_by`) |
| R8 | 1차(구조) vs 색·타이포 레퍼런스 | 1차에 시각 값이 섞이면 단계 분리 원칙 위반 | 1차는 구조 축만 사용, 시각 축은 2차로 이월(경고) |
