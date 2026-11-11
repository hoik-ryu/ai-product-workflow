# 디자인 워크플로 v2 로드맵 (`/product-design`)

- 상태: **로드맵(제안)**. 이 문서는 엔진 코드, 스킬, 테스트를 바꾸지 않습니다. 구현은 Milestone별로 따로 승인받아 진행합니다.
- 작성: 2026-11-10
- 근거
  - 시험 프로젝트(badminton-playbook)의 실험 기록입니다(§1.3). 수치는 그 프로젝트의 측정값이며 **엔진 기본값이 아닙니다**.
  - 개선 후보 ID: 기존 제안서의 ID(P·E 등)를 출처로 보존하고, 이 문서에서 **처음으로 WF-D01부터 번호**를 매깁니다. 이 문서 이전에 WF-D 목록 파일은 없었습니다.
  - A/B 실험 보고서의 D1–D15는 UX 명세 차이 분류(시험 사례)입니다. 엔진 개선 후보가 아니므로 이 번호 체계에 넣지 않습니다.

## 1. 현재 구조와 개선 필요성

### 1.1 현재 엔진(v1)
```
ux_planning(00) ──승인──▶ ux_spec(01–05, 구조 확인 체크포인트) ──승인──▶ preview(design-preview/ + 06)
                                                                       └─ preview-verify: 경계 검사 + pnpm build, 트리 해시 기록
```
- 상태는 `.ai-workflow/design.json`에 있고 `product_design.py`만 씁니다(Python 표준 라이브러리).
- 승인은 파일 sha256과 revision으로 기록합니다. 상위 단계를 다시 승인하면 하위 승인이 무효가 됩니다. `approved_modified`는 차단합니다.
- 시각 결정은 단계가 없습니다. 04 문서의 '시각 디자인 단계로 넘긴 항목'으로만 남습니다.
- 규칙 `reference/preview.md`
  - "토큰 변경 = UX 설계 변경"
  - Figma는 06 문서의 링크로만 남기고, 자동 생성하지 않습니다.

### 1.2 v1의 공백
| 공백 | 실험 근거 |
|---|---|
| 시각 결정을 기록·승인할 곳이 없음 | 글꼴·아이콘·치수·테마를 프로젝트 문서(VD)에서 따로 관리해야 했음 |
| 변경 성격 분류가 하나뿐 | 브랜드 색 하나를 바꿔도 UX Spec 재승인이 필요 |
| 시각 품질을 측정하는 단계가 없음 | 가림·넘침·안전 영역을 사람이 계산 |
| 렌더 경로가 Preview 하나 | Figma 생성 시도는 엔진 밖에서 했고, 한도로 중단되자 전환 규칙이 없었음 |
| 외부 도구 영향 검증 없음 | UI 라이브러리 CLI의 예상 밖 의존성·설정 덮어쓰기를 사람이 리허설로 확인 |
| 결함 수정이 재발 방지로 이어지지 않음 | 자동 검사가 놓친 결함을 사람이 찾은 뒤에야 검사를 추가 |

### 1.3 근거 실험(시험 프로젝트)
| 실험 | 결과 요약 | 기록(시험 프로젝트 저장소) |
|---|---|---|
| Figma A/B 시안 | 테마 모드 1개 제한, 브랜드·상태 색 충돌, 고정 버튼 가림 결함 | `docs/design-profile/reviews/SCR-211-design-experiment-AB.md` |
| C안 전체 Figma 생성 | 56개 프레임 중 14개에서 MCP 호출 한도로 중단. 스크립트 오류 1회 | `.../C-mint-hybrid-full-design.md` |
| Figma 스크립트 모의 실행 | 남은 42개 프레임 구조를 Figma 없이 추출(중립 화면 명세 후보) | `docs/design-profile/preview-handoff/` |
| Code-first PoC(1개 화면) | 3회 반복 끝에 자동 검사 결함 0건. 사람 확인 결함 1건 → 검사 추가 | `.../SCR-211-code-first-poc.md`, `experiments/c-preview-poc/review/results.json` |
| 선행 제안서 | 단계 설계(P0–P3), 테마 분리, Code-first 경로(E1–E10) | `docs/workflow-proposals/*.md` |

## 2. 설계 원칙
1. **범용 엔진**
   - 화면 크기, 색, 행 높이, 밀도 수치, 글꼴은 모두 **프로젝트 설정 값**으로 받습니다. 엔진에는 기본값으로 넣지 않습니다.
   - 엔진은 검사 방식과 판정 형식만 압니다.
2. **Code-first만으로 전체 흐름을 마칠 수 있어야 합니다**: Figma는 선택형 렌더러입니다. Figma가 없거나 중단돼도 승인까지 갈 수 있습니다.
3. **기존 승인 게이트 불변**
   - UX Planning, UX Spec, Preview의 승인 대상·해시·무효화 규칙을 바꾸지 않습니다.
   - 새 단계는 상위 승인 문서를 읽기만 합니다.
4. **외부 스킬·도구는 선택형입니다**
   - 대상: frontend-design, 외부 UX 규칙, Figma MCP, UI 라이브러리 CLI
   - 엔진의 필수 의존성이 아닙니다. 쓸 때는 출처와 버전을 기록합니다.
5. **실험과 정식 변경을 분리합니다**: 실험 산출물은 승인 경로 밖(`experiments/` 등)에 두거나 `experimental` 표시를 붙입니다. 실험 산출물은 승인할 수 없습니다.
6. **자동 판정과 사람 판정을 분리합니다**: 모든 검사 결과에 `measured`, `calculated`, `visually_reviewed` 구분을 남깁니다. 자동 검사 결함 0건을 시각 승인으로 간주하지 않습니다.
7. **결정적 처리는 스크립트가 합니다**: 상태 전이, 해시, 영향 분류 판정, 측정은 스크립트가 맡습니다. LLM은 설명, 제안, 승인 수집만 합니다(v1 원칙 유지).

## 3. 통합 개선 후보(WF-D)

| ID | 후보 | 출처(기존 ID) | Milestone |
|---|---|---|---|
| WF-D01 | 디자인 변경 영향 분류 | `engine-design-stages.md` P0 | M1 |
| WF-D02 | Design Direction 단계와 승인 게이트(실험 표시 포함) | `engine-design-stages.md` P1(§3), `code-first-path.md` §3.3 | M1 |
| WF-D03 | 개발자용 테마 설정(원시·의미 2층, 테마 파일) | `engine-design-stages.md` P1(테마), `theme-separation.md` | M1 |
| WF-D04 | 렌더러 경로 선택(Code-first 기본, Figma-first 선택) | `code-first-path.md` §3.1, E3 | M1 |
| WF-D05 | 승인 해시·revision 보호 확장(새 단계·테마·렌더 기록) | `engine-design-stages.md` §6, `theme-separation.md` §5 | M1 |
| WF-D06 | 렌더 원장과 중단 복구 | `code-first-path.md` E3, E4 | M2 |
| WF-D07 | Figma MCP 호출 예산과 도구 제약 프로필 | `code-first-path.md` E1, E10 | M2 |
| WF-D08 | Playwright 기반 Visual Review | `engine-design-stages.md` P2, `code-first-path.md` E8, PoC §7.5 | M2 |
| WF-D09 | 모바일·접근성 검사 세트(터치, 가림, 넘침, 대비, 안전 영역, 밀도, 부품 내부 넘침) | `engine-design-stages.md` P2(모바일 품질), PoC §3 | M2 |
| WF-D10 | 토큰 대비·의미 충돌 검사(테마 검사) | `code-first-path.md` E6, `theme-separation.md` §3 | M2 |
| WF-D11 | 결함 수정 시 회귀 검사 추가 규칙 | PoC §4·§7.5 | M2 |
| WF-D12 | 외부 UI 라이브러리 설치 영향 검증 | PoC §1.1·§7.5 | M2 |
| WF-D13 | 생성 스크립트 재현성(저장 → 조립 → 문법 검사 → 모의 실행 → 실행) | `code-first-path.md` E5 | M2 |
| WF-D14 | 중립 화면 명세(IR) 표준화 | `code-first-path.md` E2, PoC §7.2 | M3 |
| WF-D15 | Figma/React 컴포넌트 매핑과 인스턴스 검증 | `engine-design-stages.md` P3(토큰 검증), `code-first-path.md` E7 | M3 |
| WF-D16 | 외부 UX 규칙 출처 어댑터 | `engine-design-stages.md` P3 | M3 |
| WF-D17 | 시각 회귀 검증(스크린샷 비교) | 이번 로드맵 요청(새 항목) | M3 |
| WF-D18 | 명세 문구 공백 수집 | `code-first-path.md` E9 | M3 |

## 4. Milestone 1 — 디자인 생성 기반

### 4.1 기능
| ID | 내용 |
|---|---|
| WF-D01 | 디자인 변경을 다섯 가지로 분류하는 규칙과 `impact --design`(새 명령 옵션).<br>① 정보·행동 → UX Spec<br>② 토큰 의미·이름 → UX Spec<br>③ 테마 값 → 테마 게이트<br>④ 시각 표현 → Design Direction(VD)<br>⑤ 구현 메모 → 렌더 결과만<br>판정 근거를 함께 기록합니다(변경된 파일, 토큰 이름, CMP·UXD 참조). 자동으로 확정할 수 없으면 `needs_review`으로 냅니다 |
| WF-D02 | 새 단계 `design_direction`(산출물 `docs/design/07-design-direction.md`, 이름은 구현 때 확정).<br>내용: VD 목록(상태: 승인 / 후보 / 미결정), 밀도·터치·안전 영역 정책 값, 렌더 경로, 렌더 대상 화면·상태 목록, 적용 규칙 출처(버전), 실험 허용 목록, 변경 요청 분류(WF-D01) |
| WF-D03 | 프로젝트 테마 파일(경로는 설정).<br>원시 값(브랜드 팔레트)과 의미 토큰 덮어쓰기·추가를 담습니다. 04는 의미 토큰 이름과 **제약**(대비 쌍, 상태 색 구분)만 승인합니다. 테마 값을 바꾸면 ③으로 분류되고 Design Direction 이하만 다시 확인합니다. 관리자 UI는 없습니다(개발자 설정) |
| WF-D04 | `design_direction`의 `renderer: code | figma | both`(기본 `code`).<br>Figma-first는 검토용 렌더일 뿐이고, 최종 시각 승인은 기존처럼 `design-preview/` 트리 해시 + 06입니다 |
| WF-D05 | 새 해시 대상: 07 문서, 테마 파일, (M2) 렌더 원장·검토 결과.<br>무효화 연쇄: `ux_spec` 재승인 → `design_direction` → `preview`. 테마 변경 → `design_direction`은 유지하고 `preview` 검증만 무효. 기존 v1 무효화는 그대로 둡니다 |

### 4.2 입력·출력·상태·게이트
| 단계 | 입력 | 출력 | 상태 | 승인 게이트 |
|---|---|---|---|---|
| `design_direction`(새) | 승인된 01–05와 해시, 테마 파일, 디자인 프로필(정책 값), 선택형 규칙 출처 | 07 문서, `based_on_ux_spec` 해시, 테마 해시 | `locked → not_started → in_progress → awaiting_approval → approved`(+ outdated) | **디자인 방향 승인**: 승인 VD만 렌더에 사용. ①·②로 분류된 변경 요청이 남아 있으면 제출 차단, `reopen --stage ux_spec` 안내 |
| `preview`(기존) | v1 입력 + (v2) 승인된 07, 테마 | v1과 같음 | v1과 같음 | v1 게이트 + (v2) `design_direction` approved |

### 4.3 구현 순서
1. WF-D01 분류 규칙(reference 문서) → 스크립트 판정 함수(파일·토큰 이름 기준)와 `impact --design`
2. WF-D05 상태 스키마 확장(`stages.design_direction`, `config.workflow`)과 무효화 연쇄 → v1 회귀 테스트
3. WF-D02 단계 명령(begin, done, submit, approve, reopen 재사용)과 07 템플릿
4. WF-D03 테마 파일 스키마·해시 + 토큰 CSS 생성 규칙(preview 템플릿)
5. WF-D04 `renderer` 설정과 Preview 시작 게이트

### 4.4 완료 기준
- v1 프로젝트(`config.workflow` 없음)에서 모든 기존 테스트가 통과합니다. 동작 변화도 없습니다.
- v2 프로젝트에서 `ux_spec` 승인 → `design_direction` 승인 → `preview`까지 Figma 없이 진행됩니다.
- 테마 값만 바꾸면 `ux_spec` 승인이 유지되고 `preview` 검증만 무효가 됩니다.
- 영향 분류에서 판정할 수 없는 경우는 `needs_review`으로 나옵니다. 자동으로 ①–⑤ 중 하나로 확정하지 않습니다.

## 5. Milestone 2 — 품질 검증 자동화

### 5.1 기능
| ID | 내용 |
|---|---|
| WF-D08 | `preview-review`(새 명령)<br>• `design-preview/`를 빌드해 미리보기 서버로 띄우고, 프로젝트가 정한 뷰포트 목록에서 측정·스크린샷을 남깁니다<br>• 결과는 `docs/design/08-visual-review.md`(사람 판정 포함)와 기계 결과 JSON입니다. 검토한 트리 해시를 함께 기록합니다<br>• `preview submit` 조건: 같은 트리 해시에서 검토 통과(결함 0건 또는 의도적 예외 기록)<br>• Playwright와 브라우저는 **프로젝트의 `design-preview/` 안에** 설치합니다. 엔진은 검사 스크립트 템플릿만 둡니다 |
| WF-D09 | 검사 세트. 기준값은 모두 디자인 프로필에서 받습니다<br>• 행·요소 높이, 첫 화면 행 수(밀도 정책), 고정 요소 가림(맨 아래 스크롤·포커스 이동)<br>• 터치 영역: 자기 상자, 연결 label, 의사 요소 확장을 반영<br>• 글자 넘침·잘림·줄바꿈, 부품 내부 넘침<br>• 대비: 글자는 반투명 배경 합성, 비텍스트는 테두리와 채움 중 큰 값<br>• 안전 영역(가정값을 주입하는 방식), 콘솔 오류, 글꼴 적용 |
| WF-D10 | `theme-check`<br>• 의미 쌍 대비, 상태 색과의 색차 경고(기준값은 프로필)<br>• 'on-색' 규칙(글자 배경 금지 토큰)<br>• 테마에서 빠진 의미 토큰 탐지(예: 포커스 링이 이전 테마 값으로 남음)<br>• 렌더링 색·소스 색이 팔레트와 일치하는지(토큰 생성기가 팔레트 JSON을 냄) |
| WF-D11 | 결함 기록마다 `caught_by: automated | human`을 남깁니다. `human`이면 다음 중 하나가 필요합니다<br>• 그 결함을 잡는 검사를 추가하고, **결함이 있던 코드에서 검사가 실패하는지 확인한 기록**<br>• 검사로 만들 수 없는 이유 |
| WF-D12 | 외부 UI 라이브러리·생성기 적용 절차<br>• 레지스트리에서 install 계열 스크립트 확인<br>• 임시 복사본에서 리허설한 뒤 파일 변경·의존성 차이를 기록<br>• 미리보기 기능(`--dry-run` 등)과 코드 내용 확인(불러오는 모듈, 네트워크·프로세스 실행 코드)<br>• 대상 폴더 밖 변경이 0인지 확인하고 버전을 고정<br>• 예상 밖 변경 범위나 실행 스크립트가 있으면 중단·보고합니다 |
| WF-D06 | 렌더 원장(`design.json`의 `render` 또는 별도 파일)<br>• 화면·상태마다 `{renderer, status: done | pending | failed | paused, ref, ir_hash?, at}`를 기록합니다<br>• 한도 오류, 예산 소진, 연속 실패면 `paused`가 됩니다. 남은 항목은 사용자 승인 후 다른 렌더러로 옮기고, 화면마다 출처가 달라도 됩니다<br>• 승인 상태는 바뀌지 않습니다 |
| WF-D07 | Figma 경로 시작 전 예산 계획(화면 수 × 호출 수 + 확인 스크린샷)과 도구 제약 프로필(페이지 수, 변수 모드 수, 월 한도)을 기록합니다. 정해 둔 비율에서 멈출지 확인합니다 |
| WF-D13 | 생성 스크립트 규약: 저장소에 저장, 조립, 문법 검사, 모의 실행(가짜 API), 실행. 반환값에 스크립트 버전을 넣습니다. MCP가 코드를 본문으로만 받으므로, 대신 보내는 실행 주체에게 공통 블록을 대조하게 합니다 |

### 5.2 상태·게이트 추가
- `preview.review`: `{result: pass | fail, tree_hash, viewports, checks: {...}, defects: [{id, kind, caught_by, status}], human_review: {at, notes} | null}`
- 게이트: `preview submit`에는 `review.result == pass`, `review.tree_hash == 현재 트리 해시`, `human_review != null`이 모두 필요합니다(자동 통과만으로는 제출 불가).
- 렌더 원장의 `paused`는 `design_direction`과 `preview` 승인 상태에 영향을 주지 않습니다.

### 5.3 구현 순서
1. WF-D09 검사 함수를 표준화하고 고정 HTML 예제로 테스트(결함이 있는 예제·없는 예제)
2. WF-D08 `preview-review` 명령, 템플릿, 08 문서, 게이트
3. WF-D11 결함 기록 스키마와 회귀 규칙
4. WF-D10 `theme-check`(M1 테마 파일 필요)
5. WF-D12 외부 생성기 적용 절차(reference + 리허설 보조 스크립트)
6. WF-D06·D07·D13 Figma 경로 보조(선택형: Figma를 쓰지 않는 프로젝트는 건너뜀)

### 5.4 완료 기준
- Code-first만으로 다음을 마칠 수 있습니다: 검토 → 결함 수정 → 재검토 → 사람 확인 → `preview submit`.
- 검사 세트가 고정 예제의 알려진 결함을 모두 잡습니다(§8). 결함 없는 예제에서는 0건입니다.
- 사람이 찾은 결함에 대응 검사나 사유가 없으면 제출이 차단됩니다.
- 브라우저 설치 위치가 `design-preview/` 밖으로 나가지 않습니다(테스트로 확인).

## 6. Milestone 3 — 재사용성과 확장

| ID | 내용 | 완료 기준 |
|---|---|---|
| WF-D14 | 중립 화면 명세(IR) 표준. Design Direction의 출력이며, 렌더러 둘 다 IR에서 생성합니다<br>최소 필드: 화면·상태·플랫폼 ID / 영역과 스크롤 동작 / CMP + 변형 + 글자 속성 + 데이터 바인딩 / 의미 토큰 이름 / 밀도 정책 / 보이는 크기와 누름 영역 / 안전 영역 정책 / 접근성 이름 형식 / 실험 표시와 근거 ID / 문구 출처 | JSON Schema와 검증 명령이 있습니다. 렌더 결과(DOM 또는 Figma 노드)와 IR을 대조합니다 |
| WF-D15 | CMP ↔ React 부품 ↔ Figma 컴포넌트 대응표(프로젝트 파일)와 검사. 대응 누락, 직접 값 사용, 토큰 연결률, 변형별 기본 문구 규칙, 테마 변수 연결 | 대응표 누락 0. 검사가 모의 실행 또는 파일 감사로 동작합니다(Figma 호출 없이도 가능) |
| WF-D16 | 외부 UX 규칙 출처 어댑터: 이름, 고정 버전, 규칙 ID, 데이터 경로를 등록합니다. 읽기 전용이고 스크립트를 실행하지 않습니다. 권위 순서는 가장 아래이며, 따르지 않으면 '의도적 예외'로 기록합니다 | 등록하지 않아도 모든 단계가 동작합니다. 판정표에 규칙 ID와 버전이 인용됩니다 |
| WF-D17 | 시각 회귀: 승인된 Preview의 기준 스크린샷과 이후 렌더를 픽셀·영역 단위로 비교합니다. 허용 차이는 프로필 값입니다 | 의도한 변경은 기준 갱신 승인, 의도하지 않은 변경은 결함으로 보고 |
| WF-D18 | 렌더 전에 IR·명세에서 문구 공백과 자리 표시를 모아 UX Spec 개정 후보로 냅니다 | 공백 목록이 08 문서와 영향 분류(①)로 이어집니다 |

구현 순서: WF-D14 → WF-D15 → WF-D18 → WF-D17 → WF-D16.

## 7. 기존 엔진과의 호환성
| 항목 | 방침 |
|---|---|
| 버전 선택 | `design.json`의 `config.workflow: "v1" | "v2"`. **값이 없으면 v1.** 기존 프로젝트는 아무것도 바뀌지 않습니다 |
| v1 → v2 전환 | `migrate --to v2`(새 명령)<br>• 기존 승인·해시를 건드리지 않습니다<br>• `design_direction`을 `not_started`로 더합니다<br>• `preview`가 이미 승인된 프로젝트는 승인을 유지하고 `review: null`로 둡니다(다음 preview 개정부터 적용)<br>• 실행 전 백업은 v1 파일 안전 규칙을 따릅니다 |
| 기존 명령 | `begin`·`done`·`submit`·`approve`·`reopen`·`impact`·`rebase`·`status`의 동작과 출력 형식을 유지합니다. 새 단계는 같은 명령에 `--stage design_direction`으로 붙입니다 |
| `preview.md` 규칙 | v1의 "토큰 변경 = UX 설계 변경"은 v1에서만 그대로입니다. v2에서는 WF-D01 분류를 따릅니다(의미·이름 변경은 계속 UX 설계 변경) |
| 다른 Skill | `/product-start`·`/product-init`의 상태 파일은 읽기만 합니다. `/product-build`(미구현) 연결 조건은 `preview` approved로 같습니다 |
| 외부 의존성 | 엔진 스크립트는 계속 Python 표준 라이브러리만 씁니다. Node·Playwright·UI 라이브러리는 프로젝트의 `design-preview/` 의존성입니다 |

## 8. 필요한 테스트
| 범위 | 내용 |
|---|---|
| 상태·게이트(스크립트 단위) | v2 전이표 전체, 무효화 연쇄(ux_spec → design_direction → preview), 테마 변경 시 preview 검증만 무효, `approved_modified` 차단, `migrate` 전후 해시 불변 |
| v1 회귀 | 기존 `tests/product_design_test.py`와 시나리오가 v1 프로젝트에서 그대로 통과 |
| 영향 분류 | 시험 사례: 시험 프로젝트 A/B 실험의 D1–D15(UX 명세 차이 15건)를 **분류 정답 사례로만** 씁니다. 자동 분류 9건, 조건부 4건, `needs_review` 1건(결함 1건 제외)이 기대값 |
| 검사 세트(고정 예제) | 결함 예제: 구분선 때문에 행 높이 +1, 고정 하단 탭에 가린 마지막 행·포커스, 44 미만 누름 영역, 의사 요소로 넓힌 누름 영역(통과해야 함), 반투명 배경 대비, 채움으로만 구분되는 입력칸 경계(통과해야 함), 부품 밖으로 나간 손잡이, 줄바꿈된 한 줄 행, 팔레트 밖 색, 콘솔 오류 |
| 회귀 규칙 | 사람이 찾은 결함의 검사가 결함 코드에서 실패하는지 자동 확인 |
| 외부 생성기 | 가짜 레지스트리 패키지: install 스크립트 포함 → 중단, 대상 밖 파일 변경 → 중단, 정상 → 통과 |
| 렌더 원장 | 한도 오류 흉내 → `paused`, 경로 전환 후 `pending`만 처리, 승인 상태 불변 |
| 환경 | 샌드박스에서 스크린샷이 멈추는 경우의 대체 경로(CDP 캡처) 동작, 브라우저 설치 경로 검사 |

## 9. 리스크와 범위 제외

### 9.1 리스크
| 리스크 | 대응 |
|---|---|
| 측정 흔들림(웹 글꼴 로딩, 애니메이션) | `document.fonts.ready` 대기, 모션 끄기, 같은 브라우저 버전 기록 |
| 브라우저 용량(약 600MB)과 설치 시간 | 프로젝트 안 설치, 빌드 산출물처럼 지워도 되는 경로로 취급 |
| 샌드박스·CI 환경 차이(스크린샷 멈춤) | 표준 캡처 실패 시 CDP 캡처로 대체, 환경을 결과에 기록 |
| 외부 레지스트리·생성기 변화(새 의존성, 설정 덮어쓰기) | WF-D12 리허설과 버전 고정, 결과에 생성기 버전 기록 |
| 자동 검사 0건을 승인으로 오인 | 사람 판정 필수 게이트(§5.2), 결과의 판정 구분 |
| IR 표준이 너무 일찍 굳음 | M3까지 IR은 '후보 스키마'로 두고 두 개 이상 프로젝트에서 확인한 뒤 확정 |
| Figma 플랜·한도가 바뀜 | 도구 제약 프로필을 값으로 둠, Figma는 선택형 |
| 범위 확대로 v1 회귀 | `config.workflow` 기본 v1, v1 테스트를 모든 PR의 조건으로 |

### 9.2 범위 제외
- 관리자용 테마 변경 UI, 다크 모드
- Figma 양방향 자동 동기화, Code Connect(유료 플랜 기능)
- Chromium 외 브라우저의 시각 비교
- `/product-build`(제품 구현) 자체
- 외부 디자인 스킬의 자동 실행이나 필수화
- 프로젝트별 디자인 결정(색, 글꼴, 밀도 수치)의 엔진 기본값화
