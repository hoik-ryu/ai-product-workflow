# 선택형 브라우저 검증 어댑터 예시: React + Vite + Playwright

엔진 코드가 아닙니다. `/product-build`는 이 파일을 설치하거나 실행하지 않습니다. 엔진은 브라우저 단계가 낸 `pb-ui-report/v1` 리포트의 형식만 검사하고 판정합니다.
다른 스택에서는 같은 형식의 리포트를 쓰는 프로젝트 명령이면 무엇이든 됩니다.

## 쓰는 방법(프로젝트가 결정)
1. 이 폴더의 `pb-ui-playwright.mjs`, `ui-scenarios.example.json`을 프로젝트의 `tools/pb-ui/`로 복사하고, 시나리오를 그 프로젝트의 화면·상태·선택자에 맞게 고칩니다.
2. 도구 설치는 **사용자 확인 후** 합니다(의존성 변경). 예: `npm i -D playwright @axe-core/playwright`, `npx playwright install chromium`. `@axe-core/playwright`가 없으면 접근성 결과는 비어 있고 엔진이 `a11y_not_checked`로 보고합니다.
3. 프로필(`docs/build/build-profile.toml`)에 단계를 추가합니다. 프로필은 계획 승인 해시 대상이라 **계획을 다시 제출·승인**해야 합니다.

```toml
[browser]
enabled = true
viewports = ["mobile", "desktop"]

[[verify.steps]]
name = "browser"
stage = "browser"
run = "npm run build && node tools/pb-ui/pb-ui-playwright.mjs tools/pb-ui/ui-scenarios.json"
cwd = "."
requires = ["browser"]          # verify --available browser일 때만 실행, 없으면 not_run
timeout = 600
report = { format = "pb-ui", file = "ui.json" }
# optional = true 로 두면 미실행이어도 verify를 막지 않습니다(not_run은 기록).
```

## 시나리오와 증거
- `state`는 02 문서의 상태 ID(`SCR-001-ST1`)입니다. 통과한 결과는 그 상태의 E2 근거가 됩니다. `acs`를 적으면 AC 증거(M2 판정)에도 들어갑니다.
- `interactions`의 `name`은 02 문서의 행동 이름을 그대로 씁니다. 02 행동은 핵심 상호작용이라 `core: false`로 낮출 수 없습니다.
- 차단: 렌더 실패, 콘솔 오류, 접근성 critical, 핵심 상호작용 실패. 보고(경고): 접근성 serious, 가로 넘침, 터치 영역 위반, 핵심이 아닌 상호작용 실패.
- 스크린샷은 참고 자료입니다. 스크린샷만 있는 결과는 증거가 아닙니다.

## 주의
- 이 예시는 실제 프로젝트에서 실행해 본 코드가 아닙니다(엔진 테스트는 브라우저 없이 리포트 대역으로 검사). 사용 전에 반드시 검토하고 테스트하세요.
- 운영 환경에 직접 적용하지 마세요. 로컬·CI의 격리된 미리보기 서버를 대상으로 합니다.
