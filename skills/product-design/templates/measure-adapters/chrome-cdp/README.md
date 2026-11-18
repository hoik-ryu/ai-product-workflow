# 디자인 탐색 측정 어댑터 예시: Chrome DevTools Protocol(의존성 없음)

`/product-design explore-verify`가 실행하는 **프로젝트 측정 명령**의 예시입니다. 엔진 코드가 아니며 엔진은 이 파일을 설치·실행 결정하지 않습니다. 계약은 `reference/exploration.md` 10절(`design-explore-measure-spec/v1` → `design-explore-report/v1`).

## 쓰는 법(사용자 확인 후)

1. 프로젝트의 `tools/pd-measure/`로 복사하고 내용을 검토합니다(생성된 코드는 검토·테스트 후 사용).
2. 필요 조건: Chrome 또는 Chromium(경로는 `CHROME_PATH`로 지정 가능), Node 22 이상(Node 20.10 이상은 `--experimental-websocket`).
3. 측정 명령 등록: `explore-config --measure-cmd "node --experimental-websocket tools/pd-measure/pd-measure-cdp.mjs" --note "<사용자 문장>" --confirm`
4. `explore-verify --round S01` — 방식은 `--method emulation|iframe|window`로 바꿀 수 있습니다.

## 하는 일

- 측정 명세의 시안 × 대상 × 뷰포트마다 엔진이 만든 대상별 파생 페이지(원본 시안 불변)를 열어 **사실만** 기록합니다: 실제 뷰포트(innerWidth·innerHeight·devicePixelRatio), 렌더 여부, 콘솔·리소스 오류, `data-el` 요소 상자, 고정·sticky 요소 상자, 적중 검사(요소를 가운데로 스크롤한 뒤 `elementFromPoint`), 터치 영역, 텍스트 대비, 기본 접근성 규칙(버튼·링크 이름, 이미지 대체 텍스트, 입력 라벨, 문서 언어) 개수, 뷰포트 크기 PNG 스크린샷.
- 차단·경고 판정은 하지 않습니다(엔진 몫). 요청 뷰포트를 실제값으로 복사하지 않습니다.
- Chrome이나 WebSocket이 없으면 `status: "not_run"`을 써서 엔진이 미실행으로 기록하게 합니다(경고 후 선택 허용).
- 외부 네트워크를 쓰지 않고, 레퍼런스 원본 이미지를 입력으로 받지 않습니다. 임시 브라우저 프로필은 끝나면 지웁니다.

## 방식

| 방식 | 설명 |
|---|---|
| `emulation`(기본) | `Emulation.setDeviceMetricsOverride`로 390×844@2 같은 모바일 뷰포트를 정확히 재현. headless 창의 최소 크기 제한을 받지 않음 |
| `iframe` | 큰 창 안에 요청 크기의 iframe을 두고 그 문서를 잼(에뮬레이션이 없는 도구와 같은 방식). `--allow-file-access-from-files`로 같은 출처 접근 |
| `window` | 창 크기만 지정. headless 브라우저는 최소 창 너비가 있어 실제 뷰포트가 요청과 달라질 수 있음 → 엔진이 `viewport_mismatch`로 측정 무효 처리(재현·진단용) |

## 한계

- 접근성은 기본 DOM 규칙만 셉니다(axe 같은 전체 검사가 아님, `a11y_tool`에 표시). 필요하면 프로젝트가 다른 도구로 바꿔도 같은 리포트 형식이면 됩니다.
- 대비는 단색 배경만 계산합니다(그라데이션·이미지 배경 위 글자는 `null`).
- 정적 HTML 시안 기준입니다(스크립트 없는 시안 계약). 상호작용은 "누를 수 있는 위치에 보이는가"(적중 검사)만 확인합니다.
