# 변경 요청(Change Request)과 승인 패치(Amendment) — M1

승인된 디자인을 바꿀 때 변경 유형(A–E)과 영향 범위에 맞는 승인·검증만 요구합니다. **승인 체계를 없애는 기능이 아니라 승인 범위를 정하는 기능입니다.**

- 구현: `scripts/pd_change.py`(유형 분류·CR·패치 체인·유효 승인 기준), `scripts/pd_pixel.py`(이미지 전후 비교), `scripts/pd_screens.py`(영향 화면 실제 브라우저 검증)
- M1 범위: 분류·영향 표시(A–E 전부), **Type B 실행**, 안전성(잠금·stale·체인 무결성·Worktree 충돌 감지), /product-build 최소 연동
- Type C(범위 한정 디자인 변경): M1 CR로는 실행하지 않고 **`/product-change` 변경 패키지**로 처리합니다(§10). 계약에 적은 화면·디자인 단위 안에서만 바꾸고, 사용자 승인 2회(계약·최종 통합)로 Design Direction·Preview 단계 재승인 없이 패치를 기록합니다. 처음 M2로 설계했던 부분 승인(화면·VD·컴포넌트 단위 승인, 부분 Preview 승인, Build 배치 단위 재승인)은 이 경로로 구현되었습니다.
- M3: Worktree 간 독립 CR 통합, 패치 병합·rebase 고도화, 동시 변경 요청 관리
- 미구현 범위·알려진 한계: §9. 기존 프로젝트 적용·활성화·복원 절차: `docs/roadmap/m1-change-request-adoption.md`

## 1. 원칙

1. 기존 승인 기록(`approved`·`submitted`·`last_approved`·revision·해시·history)은 **바꾸지 않습니다.**
2. 승인된 패치는 `changes.chain`에 **덧붙이기만** 합니다.
3. **유효 승인 기준(effective baseline)** = 단계 승인 기록 + 그 승인 revision을 기준으로 한 패치를 순서대로 적용한 값입니다.
   - 계산은 `pd_change.effective()` 하나뿐입니다. cross_verify·require_valid(cross_verify 경유)·official_design·check·status가 이 함수를 쓰고, /product-build는 `status` 출력의 `changes`를 읽습니다.
4. 체인에 문제가 있으면(삭제·순서 변경·내용 수정·위조·기준 불일치) **이전 기준으로 조용히 돌아가지 않고** `amendment_chain_broken`으로 차단합니다.
5. 사용자 유형 선택은 **최소 요구 유형보다 낮출 수 없습니다.** 더 엄격한 유형은 언제나 고를 수 있습니다.
6. 파일 개수·변경 줄 수로 판단하지 않습니다. 바뀌는 **계약의 성격**(ID·토큰·구조·상태·자산 메타·픽셀)으로 판단합니다.
7. 기능이 꺼진 프로젝트(`config.changes` 없음)와 v1은 기존 동작 그대로입니다.

## 2. 변경 유형

| 유형 | 판정 기준 | M1 처리 |
|---|---|---|
| **A** Implementation Fix | 승인 산출물(00–07·프리뷰 트리·자산·테마·기획·state.yaml) **바이트 불변**. 제품 코드·테스트만 | 디자인 CR 없음. /product-build guard·verify(회귀) |
| **B** Minor Patch | 승인 산출물이 바뀌지만 계약 불변: 자산 가장자리 보정(픽셀 비교 `edge_only`), 07의 후속 자산 참조 치환, 문장만 바뀐 문서(사전 확인 필요), 프리뷰 렌더링 보정(사전 확인 필요) | `change` CR → 패치(사용자 최종 확인 1회) |
| **C** Scoped Design Change | 특정 화면·컴포넌트 계약: 기존 버튼 위치·크기·디자인, 기존 정보의 표시 위치, 기능 유지 레이아웃, 이미지 비율·구도, 07 VD 변경, 프리뷰 manifest | 분류·영향 화면 표시 + `/product-change` 변경 패키지 안내(디자인 범위 계약, 승인 2회, 단계 재승인·재탐색 없음). 패키지를 쓸 수 없을 때만 `reopen`(`route.fallback`) |
| **D** Design System Change | 04 토큰 이름·값, 테마 파일, `tokens.css`, 04 CMP 계약, 01 IA 라우트(공통 내비게이션), 07 정책 값, 레지스트리 공통 규칙 | 기존 `reopen`·재승인(v2 테마 규칙 포함) |
| **E** Requirement / Functional | 버튼 실제 동작, 권한·접근 제어, 새 기능·비즈니스 정보 추가, 사용자 흐름(03), AC·추적(05, 02 추적), 화면 상태 표(02), 데이터 정책, 기획 문서 | /product-start 재검토(T9) → `rebase` |

**C와 E의 경계**: 단일 화면에서 일어나도 기능·사용자 행동 계약(동작·권한·정보 항목·흐름·AC)이 바뀌면 E입니다.

### 2.1 요청 사실(`facts[].kind`) → 최소 유형

| kind | 최소 |
|---|---|
| `render_fix`(target product)·`test_fix`·`defect`·`implementation_note` | A |
| `render_fix`(target preview) | B(conditional) |
| `asset_patch` op `mask`·`edge`·`matte` | B(실제 픽셀로 다시 확인) |
| `asset_patch` op `ratio`·`composition`·`crop`·`replace`·`new` | C |
| `asset_patch` 그 밖(retouch 등) | C(conditional, 대안 B) |
| `typo` | B(conditional) |
| `placement`·`dimension`·`style`·`layout`, `info` op `reorder`·`relocate`·`restyle` | C |
| `info` op `relabel` | C(conditional, 대안 E) |
| `info` op `add`·`remove`·`change`, `behavior`·`permission`·`flow`·`acceptance`·`data_policy`·`feature` | E |
| `token_name`·`token_value`·`component_contract`·`navigation` | D |
| `notation` | E(needs_review, 보수적) |
| 알 수 없는 kind, 승인 문서에 없는 참조 | D(기획 ID 참조가 있으면 E), needs_review |

`asset_patch`: `{"kind": "asset_patch", "asset": "AST-010", "op": "mask", "successor": true, "to": "AST-011"(선택)}`. `successor`면 새 자산을 등록해 07 VD 관련의 참조를 바꾸는 방식(예: AST-010 → AST-011), 아니면 제자리 교체입니다. `to`가 없으면 기준 이후 새로 등록된 자산이 하나일 때만 연결합니다.

### 2.2 실제 파일 차이 → 최소 유형(`change plan --base`·CR 평가)

| 바뀐 것 | 규칙 |
|---|---|
| 기획 문서·state.yaml | E |
| 테마 파일, 04 토큰 표·CMP 블록, 01 라우트 표, 07 정책 값, `tokens.css` 이름·값, 레지스트리 공통 규칙 | D |
| 03 표, 05 표, 02 화면 추가·삭제·상태 표·추적 | E(02 경로는 D) |
| 02 화면 블록 표현 변경 | C(conditional, 대안 E) |
| 07 VD 블록 | C |
| 07에서 후속 자산 ID 치환만(다른 바이트 동일) | B |
| 제목·표·ID·front matter가 같고 문장만 바뀐 문서 | B(conditional — **구조 일치만으로 B 확정 안 함**, 사람이 의미 불변 확인) |
| 프리뷰 이미지: 같은 경로가 범위 자산(이전 → 패치/후속)으로 바뀜 | B(참조 관계 유지) |
| 프리뷰 이미지: 승인 자산과 연결 안 됨, 추가·삭제 | C |
| 프리뷰 코드: 의미 해시(sem-2) 같음 | A |
| 프리뷰 코드: 의미 변경 | B(conditional, 대안 C) |
| 프리뷰 manifest | C |
| 자산: 메타(종류·역할·출처·참조·묘사·대체·형식·라이선스) 변경 | C |
| 자산: 픽셀 `edge_only`·`identical` | B |
| 자산: `interior`·`dimensions_changed`·비교 불가(PNG 외 형식 등) | C |
| 새 자산(후속 연결 없음)·자산 삭제 | C |
| 판정 불가(기준 내용 확인 불가 등) | D(needs_review) |

### 2.3 이미지 픽셀 비교(`pd_pixel.compare`)

PNG 8비트(회색·RGB·회색+알파·RGBA, 인터레이스 없음)만 판정합니다. 결과: 판정(`identical`·`edge_only`·`interior`·`dimensions_changed`), 바뀐 픽셀 수·비율·경계 상자, RGB·알파 변경 수와 최대 변화량, 가장자리 띠 두께(짧은 변 1%와 2px 중 큰 값).
- 그 밖의 형식(JPEG·WebP·SVG·팔레트 PNG)은 `analyzable: false` → **Type B로 확정하지 않음(C)**.
- 같은 크기·형식만으로 같은 디자인이라고 보지 않습니다. 내부 픽셀이 하나라도 바뀌면 C입니다.

### 2.3a CSS 속성 분류(`css_contract`, 프리뷰 `.css` 의미 변경)

| 바뀐 속성 | 판정 |
|---|---|
| 레이아웃 계약(display·flex·grid·position·크기·정렬·overflow·z-index 등) | C |
| 시각 결정(color·background·font-family·font-weight·opacity·box-shadow 등) | C |
| 선택자 추가·삭제(렌더링 품질 속성만 담은 경우 제외) | C(conditional, 대안 B) |
| 간격·크기 미세 보정(padding·margin·gap·border-radius·font-size·line-height 등) | B(conditional — 계약 안인지 사람 확인) |
| 렌더링 품질만(image-rendering·font-smoothing·mask·backface-visibility·will-change 등) | B(확정) |
| 분류되지 않은 속성 | B(conditional, 대안 C) |

같은 선택자 블록이 여러 번 나오면 캐스케이드처럼 합쳐서 비교합니다. `.tsx`·`.js` 의미 변경은 B(conditional, 대안 C)입니다.

### 2.3b 문장 변경의 의미(`text_semantics`)

| 바뀐 것 | 판정 |
|---|---|
| 역할·권한·접근 필드 줄(`- **역할**` 등) | E(접근 제어 변경) |
| 정책·권한·범위 단어(필수·금지·허용·권한·관리자·회원·삭제·공개·must·only·admin 등) | E(needs_review — 오탈자로 위장한 기능·정책 변경 방지) |
| 숫자 | C(conditional, 대안 B) |
| 요청 사실 `typo`의 `from` → `to` 치환과 실제 차이가 정확히 같음(한 번만 나오는 문자열, 유사도 0.6 이상) | B(확정, `typo_verified`) |
| 그 밖에 제목·표·ID가 같은 문장 변경 | B(conditional) |

### 2.4 종합

- `minimum` = 요청 사실과 실제 차이의 최솟값 중 가장 높은 유형. `recommended` = `minimum`.
- `pre_confirmation_required`: conditional·needs_review가 있거나, 실제 차이가 요청보다 높은 유형을 요구할 때. **이때만** 사용자 확인을 받습니다.
  - 대상이 구체적인 요청(파일·화면을 지정한 `render_fix` preview, `from`·`to`를 적은 `typo`)은 요청만으로 결과를 알 수 없을 뿐 의도는 명확하므로(`deferrable`) **작업 전에 묻지 않고** 실제 차이로 판정합니다. 실제 차이가 확정(classified)되면 질문이 없고, 여전히 판정 불가(conditional)면 제출 전에 `change scope --accept --note`로 확인을 받습니다. 이 확인은 그 차이(digest)에만 유효하며, 이후 파일이 바뀌면 다시 받습니다.
- 영향 범위: 화면(요청 참조·자산이 쓰이는 화면[VD 관련·레지스트리 refs·프리뷰 사본]·프리뷰 import closure), 상태·컴포넌트(02), AC(05), 토큰, 문서. 공통 파일(어느 화면 closure에도 없음)이나 알 수 없는 범위는 `screens: null`(전체 영향, 보수적)입니다.

## 3. CLI

```bash
SK=<엔진>/skills/product-design/scripts/product_design.py
python3 $SK change plan   --project "$PWD" --request <프로젝트 밖 요청 JSON> [--base HEAD | --id CR-001]   # 읽기 전용
python3 $SK change enable --project "$PWD" [--confirm --note "<사용자 동의 문장>"]                        # 기본 dry-run
python3 $SK change open   --project "$PWD" --request <요청> --scope-note "<사용자 최초 요청 원문>" [--type B] [--pre-confirm "<사용자 확인 문장>"]
python3 $SK change scope  --project "$PWD" --id CR-001 [--accept --note "<범위 확대 재확인 문장>"]
python3 $SK change verify --project "$PWD" --id CR-001
python3 $SK change submit --project "$PWD" --id CR-001
python3 $SK change approve --project "$PWD" --id CR-001 --note "<결과를 본 뒤 사용자 최종 확인 문장>"
python3 $SK change cancel --project "$PWD" --id CR-001 --reason "<사유>"     # 파일이 기준으로 돌아간 뒤
python3 $SK change rebase --project "$PWD" --id CR-001                      # 다른 패치 승인 뒤, 겹치지 않을 때만
python3 $SK change status --project "$PWD" [--id CR-001]
python3 $SK change disable --project "$PWD" [--confirm --note …]            # 패치·진행 중 CR이 없을 때만
```

- 기존 `reopen`·`approve`·`impact --design` 명령은 그대로입니다. 진행 중 CR이 있으면 `reopen`은 `change_pending`으로 막힙니다.
- 승인된 Design Direction의 자산은 원래 교체·권리 재확인이 막혀 있습니다(`assets_locked_by_approval`). **진행 중 Type B CR이 선언한 자산**(제자리 교체)과 **후속 자산**(새 자산의 권리 확인)만 허용합니다. 바뀌기 전 권리 기록은 CR에 보관하고 `cancel` 때 되돌립니다.

### 3.1 CR 상태

```
open ─수정─▶ in_progress ─verify─▶ verified ─submit─▶ awaiting_confirmation ─approve─▶ approved(패치 AMD-n)
  │             │  최소 유형 상승 → escalated(완료 불가, cancel 후 정식 경로)
  │             │  범위 밖 변경 → scope_expanded(재확인 --accept 또는 되돌림)
  └─────────────┴─ cancel(파일 복원 후) → cancelled
```

| 검사 | 시점 | 오류 |
|---|---|---|
| 최소 유형 > 선택 유형 | open·scope·verify·submit·approve | `change_type_insufficient`·`change_escalated` |
| C·D·E·A 실행 | open | `change_type_not_executable`(경로 안내) |
| 모호한 판정에 사전 확인 없음 | open·verify | `pre_confirmation_required` |
| 범위 밖 파일 | scope·verify·submit·approve | `scope_expanded` |
| 기준 상태가 유효 승인 기준과 다름 | open | `baseline_not_clean` |
| 범위 파일이 커밋되지 않음 | open | `uncommitted_scope_files` |
| 다른 진행 중 CR과 같은 파일·자산·화면(또는 범위 불명) | open | `cr_conflict` |
| 검증 이후 파일 변경 | submit·approve | `verification_stale` |
| 제출 이후 변경 | approve | `changed_since_submit` |
| 연 뒤 유효 기준·승인 revision 변경 | submit·approve | `cr_stale`(겹치지 않으면 `rebase`) |
| 최종 확인 문장 없음 / 작업 전 동의 문장 재사용 | approve | `final_confirmation_required`·`confirmation_reused` |
| 체인 문제 | 모든 상태 변경 | `amendment_chain_broken` |

### 3.2 사용자 개입(최소화) — 엔진이 작업을 멈추고 사용자 문장을 요구하는 횟수 기준

| 상황 | 작업 전 | 작업 중·제출 전 | 완료 | 합계 |
|---|---|---|---|---|
| Type A | 없음 | 없음 | 없음(기존 Build 승인 정책) | 0 |
| 명확한 Type B(마스크 보정·렌더링 품질 CSS·정확한 오탈자 치환, 파생 자산 권리 상속) | 요청 원문을 **작업 범위 동의**로 기록(`--scope-note`, 질문 아님) | 없음 | **최종 패치 확인**(`--note`, 패치 + 권리 상속을 함께 확인) | **1** |
| 실제 차이를 자동 판정할 수 없는 B(간격 미세 보정·문장 변경 등) | 없음(대상이 구체적이면) 또는 `--pre-confirm` | 차이 확인(`change scope --accept --note`) | 최종 확인 | 2 |
| 의도 자체가 모호한 요청(needs_review 등) | `--pre-confirm` | — | 최종 확인 | 2 |
| 권리 상속 조건이 아닌 자산(외부·다른 라이선스·파생 불확실) | — | 권리 확인(`explore-asset confirm`) | 최종 확인 | 2 |
| 작업 중 범위 확대 | — | 재확인(`--accept --note`) | — | +1 |
| 최소 유형 상승 | — | 재분류 → 정식 경로 | — | — |

작업 범위 동의(`consent.scope`), 작업 전·차이 확인(`consent.pre_confirmation`·`diff_confirmation`), 최종 결과 확인(`approval`)은 따로 기록하며, 앞선 문장을 최종 확인으로 받지 않습니다(`confirmation_reused`). 엔진은 사용자 문장을 만들거나 다른 확인의 의미로 넓히지 않습니다.

### 3.3 파생 자산의 권리 상속

`explore-asset add --derived-from <승인 자산>`(후속 자산) 또는 진행 중 Type B CR의 `explore-asset replace`(제자리)에서, 다음을 **모두** 만족하면 별도 권리 확인 없이 부모의 승인 근거를 연결합니다.
- 진행 중 Type B CR이 부모 자산을 선언함
- 부모가 유효 승인 스냅샷에 있고 권리 근거(라이선스·사용자 문장)가 있음
- 종류·역할·출처·형식·라이선스가 부모와 같음
- 출처가 직접 제작(`self_made`·`model_drawn`) — 외부 라이선스·스톡·생성 도구·레퍼런스 파생은 상속하지 않음
- 픽셀 비교가 `edge_only`·`identical`(부모의 경미한 보정임이 확인됨)

기록: 레지스트리 `rights.inherited_from`, 상태 `exploration.asset_rights.<ID>.inherited_from{asset, statement(부모 원문 참조), confirmed_at, cr, pixels}`, `statement`는 비움(새 문장을 만들지 않음). 이 상속은 승인 전에는 공식이 아니며, 최종 패치 확인(`approval.covers: ["patch", "rights_inheritance"]`)과 함께 패치(`rights_inheritance`)로 기록됩니다. 조건이 하나라도 아니면 `rights.status: confirmation_required`와 사유를 내고 기존대로 `explore-asset confirm`이 필요합니다.

### 3.4 영향 화면 실제 검증(`pd_screens.py`)

- `change verify`는 **전체 앱 빌드**(`preview_build`)와 **영향 화면 시각 검증**(`screen_verification`)을 따로 기록합니다.
- 화면 검증: 저장소 밖 임시 사본에 화면 단독 엔트리(`__pd_measure.html`: `registry`의 `screens[id].render(state)`만 `data-target`으로 렌더)를 붙여 프로젝트 vite 설정으로 빌드(작은 이미지도 파일로 내보냄), 127.0.0.1 로컬 서버로 띄우고, **사용자가 확인한 측정 명령**(`config.exploration.measure_cmd`, 지문 확인)을 실행합니다. 승인된 프리뷰 트리는 바꾸지 않습니다.
- 대상: CR 영향 화면 × manifest 상태 × 설정 뷰포트. 공통 파일 변경 등 범위를 알 수 없으면 manifest 전 화면으로 확대(`expanded_to_all`).
- 판정(차단): 렌더 실패, 콘솔 오류, 접근성 critical, 가로 스크롤, 내용 잘림, 이미지 깨짐·비율 왜곡(object-fit fill에서 2% 초과)·뷰포트 밖 잘림, 패치한 이미지가 그 화면에 기대 원본 크기로 렌더되지 않음, 레이아웃·이미지 미측정(이미지가 바뀐 경우). 경고: 접근성 serious, 조상 overflow에 의한 이미지 잘림, 스크린샷 없음.
- 측정이 실제로 끝나지 않으면(`not_run`·`invalid`) 통과로 기록하지 않습니다. 측정 환경이 없을 때만 `--screen-waiver "<사용자 문장>"`으로 진행할 수 있고, 결과는 `waived`(status not_run·passed false + waiver)로 따로 남습니다.
- 결과(run_id·리포트·명세 sha256·화면·뷰포트·판정)는 검증 기록에 들어가고, 제출 스냅샷의 `verification_digest`·`screen_verification`과 패치의 `verification_digest`·`screen_verification`으로 연결됩니다. 리포트·스크린샷은 `.ai-workflow/changes/<CR>/runs/<run_id>/`.
- 측정 어댑터 템플릿(`templates/measure-adapters/chrome-cdp`)은 이미지 사실(`images`)을 기록합니다. 이 필드가 없는 이전 어댑터는 이미지가 바뀐 검증에서 `images_not_measured`(차단)입니다.

## 4. 데이터 모델(`.ai-workflow/design.json`, 기능을 켰을 때만)

```json
{
  "config": { "changes": { "enabled": true, "at": "…", "statement": "<사용자 동의>" } },
  "changes": {
    "seq": 1,
    "items": { "CR-001": {
      "id": "CR-001", "uid": "<무작위>", "status": "approved", "purpose": "…",
      "request": { "path": "…", "sha256": "…", "items": [ … ] },
      "type": { "recommended": "B", "minimum": "B", "selected": "B", "possible": ["B", "C", "D", "E"], "selected_by": "recommended", "reasons": [ … ] },
      "consent": { "scope": { "statement": "<요청 원문>", "kind": "initial_request" }, "pre_confirmation": { … }? },
      "base": { "files": { "<승인 산출물>": "sha256" }, "registry": { "AST-…": "<항목 sha>" }, "head_commit": "…",
                "effective_digest": "…", "chain_head": { "count": 0, "digest": null }, "stage_revisions": { … } },
      "scope": { "files": [ … ], "assets": ["AST-001"], "successors": { "AST-001": "AST-002" }, "screens": ["SCR-001"], "screens_known": true,
                 "accepted_expansions": [ { "statement": "…", "files": [ … ] } ] },
      "verification": { "result": "pass", "diff_digest": "…", "screens": [ … ], "checks": [ … ], "steps": [ … ] },
      "submitted": { "stages": { … }, "file_transitions": { … }, "screens": [ … ], "pixels": [ … ], "diff_digest": "…", "digest": "…" },
      "approval": { "statement": "<최종 확인>", "kind": "final_patch_confirmation" },
      "amendment": "AMD-001", "amendment_digest": "…", "rights_backup": { … }?, "history": [ … ] } },
    "chain": [ {
      "id": "AMD-001", "seq": 1, "uid": "…", "cr": "CR-001", "cr_uid": "…", "type": "B", "kind": "patch", "base_head": { … },
      "stages": {
        "design_direction": { "base_revision": 1, "files": { "docs/design/07-design-direction.md": { "before": "…", "after": "…" } },
                              "assets": { "AST-001": { "before": { …스냅샷… }, "after": null }, "AST-002": { "before": null, "after": { … } } } },
        "preview": { "base_revision": 1, "files": { "design-preview/": { "before": "<트리>", "after": "<트리>" } }, "semantic": { "before": "…", "after": "…" } } },
      "file_transitions": { "<경로>": ["<이전>", "<이후>"] }, "screens": ["SCR-001"],
      "submitted_digest": "…", "verification_digest": "…", "consent_digest": "…", "statement": "<최종 확인>", "at": "…",
      "prev": null, "digest": "<sha256(본문)>" } ],
    "head": { "count": 1, "digest": "<마지막 패치 digest>" }
  }
}
```

- **체인 검사**: `seq`가 위치와 같음, `prev`가 직전 digest, `digest` = 본문 sha256, ID 중복 없음, CR과 서로 연결(uid·승인·digest), `head`가 체인 끝과 같음, history에 `change_approved`(digest 앞 12자) 기록. 적용할 때 각 패치의 `before`가 그 시점 유효 기준과 같아야 합니다.
- **승인 revision 기준**: 패치는 `base_revision`이 현재 승인 revision과 같은 단계에만 적용됩니다. 단계를 D·E로 다시 열어 새 revision이 승인되면 이전 패치는 자연스럽게 대체되고, 기록은 남습니다.
- **진행 중 변경**: 활성 CR 범위 안의 승인 산출물 변경은 `pending_change`(문제, check 종료 2)로 보고합니다. 범위 밖 변경은 `approved_modified` 그대로입니다. 미승인 변경 자산은 공식 자산이 아닙니다(07이 변경 중이면 공식 근거 전체를 인정하지 않음).
- **검증 가정 상태**: `change verify`의 프리뷰 검사는 패치가 승인됐다고 가정한 상태 복사본으로 합니다(저장 안 함).

## 5. 안전성

| 위험 | M1 처리 |
|---|---|
| 같은 컴퓨터의 동시 쓰기 | `save_state`가 O_EXCL 잠금(`.ai-workflow/.design.lock`) + 읽은 뒤 바뀌었으면 `state_conflict`(덮어쓰지 않음). 끝난 프로세스의 잠금만 정리 |
| 부분 쓰기 | 원자적 저장(임시 파일 → rename), `enable`·`approve`는 실패 시 이전 바이트로 복원 |
| 서로 다른 Worktree에서 같은 CR ID·패치 번호 | 로컬 잠금으로 막을 수 없음. 병합 시: 충돌 표시 → `state_unreadable`, 같은 키 손 병합 → `state_duplicate_keys`, 독립 패치를 이어 붙임 → `amendment_chain_broken`. **자동 병합하지 않음(M3)** |
| 이미 바뀐 기준에서 만든 패치 | `cr_stale`·체인 `prev`/`before` 불일치로 거부 |
| 같은 자산·화면을 다루는 CR | open 때 `cr_conflict`. 같은 저장소의 겹치지 않는 CR은 동시 진행 가능, 먼저 승인된 뒤 나머지는 `rebase`(겹치면 거부, 프리뷰 트리를 함께 바꾸는 경우도 거부) |
| 의도적 위조 | 아래 §5.1 |

### 5.1 위협 모델 — 보장하는 것과 보장하지 않는 것

digest(SHA-256)는 **내용 지문**입니다. **암호학적 서명이 아니고 사용자 인증도 아닙니다.** 비밀 키가 없으므로 상태 파일을 쓸 수 있는 사람(또는 프로그램)은 내용을 고친 뒤 digest를 다시 계산할 수 있습니다.

| 보장함(엔진이 감지·차단) | 보장하지 않음 |
|---|---|
| 승인 산출물이 유효 승인 기준과 다른 상태로 승인·진행되는 것(해시 비교) | 상태 파일을 직접 고쳐 승인·패치 기록 전체를 일관되게 다시 만든 위조(기존 단계 승인 해시와 같은 수준의 한계) |
| 패치 체인의 일부 삭제·순서 변경·내용 수정(일관되게 다시 계산하지 않은 경우), CR·history와 맞지 않는 패치 | 승인 문장을 실제로 사용자가 말했는지(엔진은 Claude가 전달한 문장을 기록할 뿐 사람을 인증하지 않음) |
| 패치가 승인 기록과 다른 파일·이전 해시를 가리키는 것(적용 시 `before` 불일치) | Git 이력 자체의 변조, 다른 사람이 같은 권한으로 저장소를 바꾸는 것 |
| 제출·검증 이후 파일 변경, 오래된 기준에서 만든 CR, 같은 컴퓨터의 동시 쓰기, 병합 충돌·중복 키 | 서로 다른 Worktree의 상태를 미리 막는 것(병합 후에만 감지) |
| 승인 전 변경 자산이 공식 자산·Build 기준으로 쓰이는 것 | 측정 어댑터가 사실을 거짓으로 기록하는 것(측정 명령 지문으로 바뀜만 감지) |

대조 수단: history의 `change_approved`(digest 앞 12자), CR ↔ 패치 상호 참조(uid·digest), Git 커밋 이력. 강한 보장(서명·인증)이 필요하면 커밋 서명·브랜치 보호 같은 저장소 수준 통제를 함께 씁니다.

## 6. /product-build 연동(M1 최소)

- `design_info`가 `status`의 `changes`(유효 기준·패치·진행 중 CR)를 읽습니다. `pending_change`는 단계 승인을 깨지 않습니다.
- 계획 입력 기준선: 계획 승인 이후 승인된 패치로 **설명되는** 디자인 문서 변경(이전 해시 → 패치 체인 → 현재 해시)은 계획 무효가 아닙니다. 진행 중 CR 범위 파일도 계획 무효가 아니고, 영향 배치만 막습니다. 그 밖의 변경은 기존대로 outdated입니다.
- 재검증: 배치 검증 이후 승인된 패치의 영향 화면이 배치 화면과 겹치면(또는 패치 범위 불명) 그 배치만 `stale`(`freshness`). 검증 기록에 `design_amendments`(그 시점 패치 수)를 남깁니다.
- 차단: 진행 중 CR이 영향 주는 화면 배치(또는 범위 불명)는 `batch-start`·`resume`·`execute-gate`·`verify`·`approve batch`에서 `design_change_pending`. 체인 문제는 `design_amendment_chain_broken`. 화면 없는 배치는 영향 없음.
- Type A는 기존 `guard`(보호 경로)·`verify`·`ledger`를 그대로 씁니다.

## 7. 마이그레이션·호환

- 마이그레이션은 필요 없습니다. `change enable`이 `config.changes`와 빈 `changes`를 **추가만** 합니다(기존 필드 보존 검사 `_preserved`, 실패 시 복원). dry-run이 기본이며, 상태 파일이 Git 추적·clean이 아니면 `.ai-workflow/backup/design/design.json.pre-changes`에 백업합니다.
- 끄기(`disable`)는 패치·진행 중 CR이 없을 때만 됩니다. 패치가 생긴 뒤 되돌리려면 백업·Git 이력으로 복원합니다.
- v1 프로젝트는 대상이 아닙니다(`changes_requires_v2`).

## 8. 시나리오와 마일스톤

| # | 시나리오 | M1 | 비고 |
|---|---|---|---|
| 1 | 승인 명세대로 제품 버그 수정 → 승인 유지 | ✅ | Type A |
| 2 | 동일 이미지 가장자리 마스크 → 경미한 패치 | ✅ | Type B(후속 자산·제자리 교체) |
| 3 | 동일 이미지 비율 변경 → 부분 디자인 변경 | ◐ CR은 분류·차단 | `/product-change` 패키지로 실행 |
| 4 | 특정 화면 배너 교체 → 해당 화면만 영향 | ◐ CR은 분류·영향 화면 | `/product-change` 패키지로 실행(그 화면만 실측) |
| 5 | 전역 컬러 토큰 → 전체 재승인 | ✅ 분류·B 차단, 기존 경로 | |
| 6 | 공통 컴포넌트 변경 → 사용 화면 전파 | ◐ 분류(D)·공통 파일 = 전체 화면 | 단위 승인 M2 |
| 7 | 기능·권한 변경 → 상위 재승인 | ✅ 분류·B/C 차단, 기존 경로 | |
| 8 | 잘못된 하위 유형 선택 → 차단·재분류 | ✅ | |
| 9 | 변경 중 범위 확대 → 재계산 | ✅ | |
| 10 | 승인되지 않은 자산 교체 → 차단 | ✅ | |
| 11 | 패치 후 기존 승인 해시·이력 | ✅ | |
| 12 | 부분 Preview 승인 후 전체 승인 상태 | ◐ Type B 영향 화면 실제 브라우저 검증 + effective_status | 부분 Preview 승인 M2 |
| 13 | 기존 프로젝트 승인 상태 마이그레이션 | ✅ dry-run·복원 | |
| 14 | 기존 워크플로 전체 회귀 | ✅ | |
| 15 | 여러 CR 동시 진행·stale | ◐ 같은 저장소: 감지·rebase / Worktree 간: 감지·차단 | 통합 M3 |

## 9. M2·M3 미구현 범위와 알려진 한계

**미구현(필요성이 확인되면 재개)**
- (구현됨, 경로 변경) Type C 부분 승인·부분 Preview 승인·Build 배치 단위 재승인은 M1 CR이 아니라 `/product-change` 변경 패키지로 구현되었습니다. M1 CR(`change open`)은 C를 분류·영향 표시만 하고 패키지 경로를 안내합니다(`route.owner: /product-change`, 패키지를 쓸 수 없을 때만 `route.fallback`의 `reopen`).
- M3: Worktree 간 독립 CR 통합, 패치 자동 병합·rebase, 동시 변경 요청 관리 고도화. M1은 병합 후 충돌을 감지·차단만 합니다(같은 저장소의 겹치지 않는 CR만 `rebase` 가능, 둘 다 프리뷰 트리를 바꾸면 거부).

**알려진 한계**
1. digest는 서명·인증이 아닙니다(§5.1). 상태 파일 전체를 일관되게 다시 만든 위조는 막지 못합니다.
2. 픽셀 판정은 8비트 비인터레이스 PNG만 합니다. JPEG·WebP·SVG·팔레트 PNG는 Type B로 확정하지 않습니다(C). 가장자리 띠 두께는 엔진 고정값입니다.
3. CSS·정책 단어·숫자 판정은 보수적입니다. 무해한 변경도 사용자 확인이나 상위 유형으로 갈 수 있습니다(예: 정책 단어 '만'이 들어간 문장).
4. 영향 화면 검증은 현재 결과를 절대 기준으로 판정합니다(승인 시점 측정과 비교하지 않음). 승인 당시 있던 결함도 Type B 검증을 막을 수 있습니다.
5. 영향 화면 검증에는 확인된 측정 명령·Chrome·프리뷰 `node_modules`가 필요합니다. 없으면 통과할 수 없고, 사용자 면제(`--screen-waiver`, `waived` 기록)로만 진행합니다. 탐색 설정이 없는 v2 프로젝트는 측정 명령 등록 전에 설정을 만들어야 합니다(적용 절차: `docs/roadmap/m1-change-request-adoption.md` §5).
6. 이전 측정 어댑터는 이미지 측정(`images`)이 없어, 이미지가 바뀐 Type B 검증이 막힙니다. 템플릿 갱신과 측정 명령 재확인이 필요합니다.
7. CR은 승인 상태를 커밋한 뒤, 수정 전에 엽니다(`baseline_not_clean`·`uncommitted_scope_files`). 이미 고친 뒤라면 `change plan --base HEAD`로 분류만 할 수 있습니다.
8. 진행 중 CR의 범위를 마지막 평가 이후 확정할 수 없으면 모든 화면 배치를 막습니다. `change scope`로 다시 평가하면 영향 없는 배치는 진행할 수 있습니다.
9. /product-build의 재검증 표시(stale)는 패치 체인 원본을 직접 읽습니다(배치를 다시 검증하게 만드는 보수적 방향만). 패치를 '인정'하는 판단은 `status`의 유효 기준만 씁니다.
10. 패치가 생긴 뒤 구 엔진으로 되돌리면 패치된 파일이 `approved_modified`로 차단됩니다. 패치 이전 커밋으로 산출물·상태를 함께 되돌려야 합니다(적용 절차 §7).

## 10. 변경 패키지(`/product-change`) 연동

**Type C 처리 경로**(디자인만 바뀌고 기획 ID 변경이 없는 경우): `/product-change`에서 `ids`를 비우고 `design.screens`(영향 화면, 공용 컴포넌트를 바꾸면 그 컴포넌트를 쓰는 화면 포함)·`design.units`(바뀌는 VD·CMP 등)·`build.regression`(영향 화면 배치)을 적은 계약으로 엽니다. 이후 계약 1차 승인 → `change open --package` → 수정 → `change verify`(영향 화면 실측) → `change submit` → 회귀 → 최종 통합 2차 승인 → finalize. 기획 단계는 건너뛰고, 디자인 단계 revision은 그대로이며 패치(kind `package`)만 추가됩니다. 단계 제출이 아니므로 디자인 탐색 의무(`exploration_required`)도 적용되지 않습니다. 토큰·테마를 바꾸려면 계약 `design.units`에 `"tokens"`가 있어야 합니다(Type D 성격이므로 계약에 명시). Type B Amendment 경로와 D·E의 기존 처리 정책은 그대로이며, 기획 변경을 포함하는 패키지는 기존 조건 그대로 쓸 수 있습니다.

- `change open --package CP-###`: 진행 중 패키지의 계약 승인이 유효할 때만 엽니다. 범위 = 계약 디자인 단위·화면 + 엔진 영향 범위(영향 단위·화면·씨앗·폐기 ID·추가 ID).
- 범위 검사(`contract_scope_exceeded`): 디자인 문서의 바뀐 ID(펜스 코드 제외, VD 블록 차이 포함)가 범위 밖이면 멈춥니다. 바뀐 줄이 모두 허용 하위 ID 행(예: FLOW-005-S7d)이면 상위 블록(FLOW-005) 변경으로 보지 않습니다. 프리뷰 파일은 허용 화면 closure 안, 토큰·테마는 계약 `tokens`가 있을 때만.
- 패키지 CR은 `change approve`로 승인하지 않습니다(`package_cr_final_only`). `change submit`까지 한 뒤 패키지 최종 통합 승인 → `change package-finalize --package`가 영향 단계만 범위 rebase하고 Amendment(kind `package`, `package` 필드)를 덧붙입니다. 실패하면 되돌립니다(`rollback_on_failure`).
- 패키지 CR의 변경 diff에서는 기획 문서와 `state.yaml`을 다른 범위로 세지 않습니다(기획은 패키지가 따로 관리).

