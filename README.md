# ai-product-workflow

요구사항에서 디자인, 구현, 검증까지 이어지는 AI 기반 제품 개발 워크플로입니다.

Claude Code Skill로 자연어 제품 아이디어를 **Product Discovery → 사용자 승인 → Product Planning(PRD, User Story, User Flow, Acceptance Criteria) → 사용자 승인**까지 연결합니다.

> 현재 범위: **Milestone 1 (아이디어 → PRD)**. Figma 디자인, Design System, Boilerplate, 구현 단계는 이후 마일스톤에서 다룹니다.

## 특징

- `/product-start` 단일 진입점: 신규 시작, 중단 후 재개, 승인 처리를 모두 이 명령 하나로 합니다.
- 명시적 승인 게이트: Discovery 승인 전에는 Planning 문서를 만들지 않습니다. Planning이 승인돼야 Design 단계가 열립니다.
- 상태 파일 기반 재개: `.ai-workflow/state.yaml`과 실제 파일(존재 여부, revision, 승인 해시)을 매번 교차 검증합니다.
- 사실과 가정 분리: 사용자가 확인하지 않은 내용은 `ASM-`(가정)이나 `Q-`(미결) ID로 별도 관리합니다.
- 요구사항 추적성: `GOAL → FR → US → FLOW → AC` 추적 매트릭스와 누락 점검을 제공합니다.
- 파일 보호: 기존 파일은 설명과 확인 없이 덮어쓰지 않습니다. Git으로 보호되지 않는 파일만 단일 슬롯에 백업합니다.

## 저장소 구조

```
skills/product-start/
  SKILL.md                 진입점(절차·게이트·규칙)
  reference/               state-machine, file-safety, id-conventions, interview-guide
  templates/               state.yaml, 01-discovery … 05-acceptance-criteria
docs/architecture.md       설계
tests/scenarios.md         테스트 시나리오와 실행 기록
```

## 설치(제품 프로젝트에서 사용)

엔진 저장소와 제품 프로젝트는 분리해서 사용합니다. 엔진 저장소 안에서는 실행되지 않습니다.

**A. 프로젝트 단위(권장, 전역 설정 변경 없음, 검증 완료)**

제품 프로젝트 루트에서 실행합니다. `ENGINE`은 이 저장소의 절대 경로입니다.

```bash
ENGINE=/path/to/ai-product-workflow
mkdir -p .claude/skills
ln -s "$ENGINE/skills/product-start" .claude/skills/product-start
```

심볼릭 링크로 연결하면 Skill의 `reference/`와 `templates/`가 프로젝트 밖에 있게 됩니다. 그래서 엔진 경로 읽기를 허용해야 합니다. `.claude/settings.local.json`(개인 로컬 설정)에 다음을 추가합니다.

```json
{
  "permissions": {
    "additionalDirectories": ["/path/to/ai-product-workflow/skills"]
  }
}
```

- 처음 실행하면 폴더 신뢰 확인 창에 "이 폴더가 작업 공간에 디렉터리 1개를 추가한다"는 경고가 표시됩니다. 경로를 확인한 뒤 **Yes, I trust this folder**를 선택합니다.
- 링크와 로컬 설정은 각자의 머신 경로를 담고 있으므로 커밋하지 않습니다. 예를 들어 `.git/info/exclude`에 `.claude/skills/product-start`와 `.claude/settings.local.json`을 추가합니다.
- headless(`claude -p`)에서는 위 설정 대신 `--add-dir /path/to/ai-product-workflow/skills` 옵션을 사용할 수 있습니다.

**B. 사용자 전역**: 모든 프로젝트에서 사용할 수 있습니다. `~/.claude`를 변경합니다.

```bash
ln -s /path/to/ai-product-workflow/skills/product-start ~/.claude/skills/product-start
```

이 경우에도 엔진 경로 읽기 허용(`additionalDirectories`)이 필요합니다. 프로젝트별 `.claude/settings.local.json`에 추가하거나 `~/.claude/settings.json`에 추가합니다.

## 사용법

```text
/product-start 배드민턴 동호회 로테이션을 학습하는 플랫폼을 만들고 싶어요
```

1. 질문에 답합니다. "모르겠다", "알아서 해줘"도 괜찮습니다. 답하지 않은 항목은 가정이나 미결 항목으로 남습니다.
2. Discovery 요약을 검토하고 **승인** 또는 **수정 요청**을 합니다.
3. 승인하면 `docs/planning/02`~`05`가 생성됩니다. 검토 후 다시 **승인** 또는 **수정 요청**을 합니다.
4. 중단했다면 인자 없이 `/product-start`를 실행하면 이어서 진행합니다.

제품 프로젝트에 생성되는 파일:

```
.ai-workflow/state.yaml            상태(기준 파일)
.ai-workflow/discovery-notes.md    인터뷰 원문 기록
.ai-workflow/backup/               (필요할 때만) 덮어쓰기 전 백업
docs/planning/01-discovery.md
docs/planning/02-prd.md
docs/planning/03-user-stories.md
docs/planning/04-user-flows.md
docs/planning/05-acceptance-criteria.md
```

산출물은 AI가 생성한 초안입니다. 승인 전에 반드시 사람이 검토해 주세요. 외부에 공유하기 전에는 기밀 정보나 개인정보가 들어 있지 않은지 확인해 주세요.
