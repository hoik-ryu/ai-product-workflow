---
name: product-start
description: 자연어 제품 아이디어를 명시적 승인 게이트와 재개 가능한 상태 관리를 갖춘 Product Discovery와 Product Planning 문서(PRD, User Story, User Flow, Acceptance Criteria)로 만듭니다. 사용자가 아이디어와 함께 /product-start를 실행하거나, 진행 중인 제품 기획 워크플로를 재개할 때 사용합니다.
argument-hint: "[제품 아이디어]  (생략하면 재개)"
disable-model-invocation: true
---

# /product-start — 아이디어 → Discovery → 승인 → Planning → 승인

사용자의 **제품 프로젝트**(현재 작업 디렉터리)에서 ai-product-workflow의 Milestone 1을 실행합니다.

보조 파일은 이 파일과 같은 디렉터리(이 Skill의 기본 디렉터리)에 있습니다. 각 단계에서 지시할 때 읽습니다.

- `reference/state-machine.md`: 상태, 전이, 승인 규칙, 재개 시 교차 검증
- `reference/file-safety.md`: 덮어쓰기 확인, Git, 백업
- `reference/id-conventions.md`: 요구사항 ID와 추적성 점검
- `reference/interview-guide.md`: Discovery 질문 방법
- `templates/`: `state.yaml`과 문서 `01`–`05`
- `scripts/ps_state.py`: 상태 파일의 시각·승인 기록 도우미(`python3 -I`로 실행, JSON 출력). **history 항목과 `approved.{revision, at, hashes}`는 이 스크립트로만 씁니다.**

프로젝트 경로(제품 프로젝트 루트 기준):

- 상태: `.ai-workflow/state.yaml`(기준 원본), `.ai-workflow/discovery-notes.md`(인터뷰 기록)
- 산출물: `docs/planning/01-discovery.md` … `05-acceptance-criteria.md`

이번 실행의 사용자 입력: `$ARGUMENTS`

## 반드시 지킬 규칙

0. **시각과 승인 기록은 직접 쓰지 않습니다.** history 항목, `approved.at`, 승인 해시는 `scripts/ps_state.py`가 실제 시스템 UTC 시각과 파일 내용으로 기록합니다. 시각을 추측하거나 손으로 적지 않습니다(`created_at`도 `ps_state.py now` 값). 상태·revision 등 시각이 없는 값만 직접 고칩니다.

1. **게이트**: discovery가 `approved`가 되기 전에는 planning 문서(02–05)를 생성하거나 작성하지 않습니다. "파일에 초안만 쓰는 것"도 포함합니다. planning이 `approved`가 되기 전에는 마일스톤 완료로 처리하지 않습니다.
2. **명시적 승인만 인정**합니다. 기준은 `state-machine.md`에 따릅니다. 애매한 응답은 다시 묻습니다. 수정 요청은 항상 새 revision과 새 승인으로 이어집니다.
3. **사실을 지어내지 않습니다**: 사용자가 말하지 않은 내용은 별도 섹션의 `ASM-`(가정) 또는 `Q-`(미결 질문)로 기록합니다. 모든 문장에 태그를 달지는 않습니다.
4. **임의로 덮어쓰지 않습니다**: 기존 산출물은 모두 `file-safety.md`를 따릅니다.
5. **상태를 먼저 기록합니다**: 전이가 일어나거나 파일을 쓸 때마다 즉시 `state.yaml`을 갱신합니다.
6. **상태와 파일이 불일치하면 보고하고 멈춥니다.** 스스로 고치지 않습니다.
7. **언어**: 산출물 본문, 헤딩, 사용자와의 대화는 `project.language`로 작성합니다. 기본값은 한국어(`ko`)이며, 사용자가 다른 언어를 명시한 경우에만 그 언어를 씁니다. 다른 언어로 쓰는 경우에도 섹션 순서·번호·표 구조는 템플릿과 같게 유지합니다. 요구사항 ID, front matter 키, YAML 키·상태값, 우선순위 값(Must/Should/Could)은 언어와 관계없이 영어 그대로 둡니다.
8. 이력이나 작업 트리를 바꾸는 Git 명령(commit, push, checkout, reset, stash)은 실행하지 않습니다.
9. **이 Skill에 명시된 파일만 씁니다**: `.ai-workflow/state.yaml`, `.ai-workflow/discovery-notes.md`, `.ai-workflow/backup/<file>`, `docs/planning/01`–`05`. 보조 스크립트, 임시 파일, 추가 문서는 프로젝트에 만들지 않습니다. 추적성·해시 점검은 파일을 직접 읽거나 `shasum`, `grep`, `ls`로 합니다.

## 0단계 — 사전 점검(매 실행)

1. 현재 디렉터리에 `skills/product-start/SKILL.md`가 있으면 제품 프로젝트가 아니라 워크플로 엔진 저장소 안입니다. 제품 프로젝트에서 실행하라고 안내하고 멈춥니다.
2. `reference/state-machine.md`를 읽습니다.
3. `.ai-workflow/state.yaml`이 있으면 `state-machine.md`의 **재개 시 교차 검증**을 수행합니다. 불일치가 있으면 기대한 상태와 실제 상태, 선택지를 보고하고 멈춥니다.
4. 상태 파일이 없는데 `docs/planning/`에 파일이 있으면, 그 파일들을 보고하고 멈춥니다. 아무것도 쓰지 않습니다.
5. 현재 위치를 2–4줄로 요약합니다. 단계, 상태, revision, 다음에 할 일을 포함합니다.

그다음 아래 표에 따라 분기합니다.

| 상태 | 이동 |
|---|---|
| 상태 파일 없음, `$ARGUMENTS`에 아이디어 있음 | 1단계 |
| 상태 파일 없음, 아이디어 없음 | 아이디어를 한 문장으로 요청하고 멈춤 |
| 상태 파일 있음, `$ARGUMENTS`에 새 아이디어 있음 | 현재 상태를 보여 주고 기존 프로젝트를 이어갈지 묻습니다. 기존 상태 파일은 절대 초기화하지 않습니다. 새로 시작하려면 다른 디렉터리를 쓰거나 사용자가 직접 `.ai-workflow/`와 `docs/planning/`을 옮기도록 안내합니다. 멈춤 |
| discovery `in_progress` | 2단계(`discovery-notes.md`에서 인터뷰를 이어가거나 초안 작성) |
| discovery `awaiting_approval` | 3단계 |
| discovery `approved`, planning `not_started` / `outdated` | 4단계 |
| planning `in_progress` | 4단계(`artifacts_done`의 마지막 파일 다음부터) |
| planning `awaiting_approval` | 5단계 |
| planning `approved` | 6단계 |

사용자가 대화로 답하면(질문 답변, 승인, 수정 요청) `/product-start`를 다시 요구하지 말고 해당 단계에서 이어갑니다.

## 1단계 — 초기화

1. `language`를 정합니다. 기본값은 `ko`이고, 사용자가 산출물 언어를 명시한 경우에만 그 언어 코드를 씁니다. 짧은 `name`을 정합니다. 정할 수 없을 때만 묻습니다.
2. `templates/state.yaml`로 `.ai-workflow/state.yaml`을 만듭니다(discovery `in_progress`, planning `locked`, design `locked`, history는 비워 둔 채). `created_at`은 `python3 -I <Skill 디렉터리>/scripts/ps_state.py now`의 값을 그대로 씁니다. 그다음 `ps_state.py event --project . --stage discovery --event started --revision 0 --note "idea received"`로 history를 기록합니다.
3. `.ai-workflow/discovery-notes.md`를 만들고 `## 아이디어` 아래에 아이디어 원문을 그대로 적습니다.
4. 2단계로 이동합니다.

## 2단계 — 인터뷰와 Discovery 초안

1. `reference/interview-guide.md`와 `discovery-notes.md`를 읽습니다.
2. 필수 주제가 아직 남아 있고 `interview_round` < 3이면 다음 라운드 질문을 하고, state의 `interview_round`를 1 올린 뒤 **멈추고 답을 기다립니다**. 사용자가 답하면 그 라운드(질문과 답변 원문)를 `discovery-notes.md`에 덧붙이고 이 단계를 반복합니다.
3. 그렇지 않으면 notes의 내용만으로 `templates/01-discovery.md`에 따라 `docs/planning/01-discovery.md` 초안을 씁니다. 답이 없는 항목은 `ASM-`/`Q-`로 둡니다(가이드 참조). `reference/id-conventions.md`를 읽습니다.
   - 파일이 없으면 새로 씁니다.
   - 파일이 있으면(수정 사이클) `file-safety.md`를 적용합니다: 설명 → 확인 → 필요 시 백업 → 쓰기.
4. discovery `revision`을 1 올리고(front matter와 일치), 상태를 `awaiting_approval`로 바꾼 뒤 `ps_state.py event --stage discovery --event submitted --revision <N> --note ...`로 history를 기록합니다. 3단계로 이동합니다.

## 3단계 — Discovery 승인 게이트

대화창에 다음을 제시합니다.

- 5–10줄 요약(문제, 사용자, 핵심 시나리오, MVP 범위)
- **가정(ASM 목록)**과 **미결 질문(Q 목록)**, 각각 한 줄씩
- 파일 경로, revision
- 선택지: **승인 / 수정 요청**. AskUserQuestion 도구를 쓸 수 있으면 사용하고, 아니면 일반 텍스트로 묻습니다.

그리고 멈춰서 기다립니다.

- 명시적 승인 → `ps_state.py approve --project . --stage discovery --revision <제시한 N> --note "<승인 요지>"`를 실행합니다. 스크립트가 해시·`approved.{revision, at, hashes}`·상태(`approved`)·planning 잠금 해제(`locked` → `not_started`, `outdated`면 유지)·history `approved`를 기록합니다. 거부되면(revision·front matter 불일치 등) 그 이유를 보고하고 멈춥니다. 4단계로 이동합니다.
- 수정 요청 → Q/ASM에 대한 답은 `discovery-notes.md`에 기록합니다. 상태를 `in_progress`로 바꾸고 `ps_state.py event --stage discovery --event changes_requested --revision <N> --note "<요청 요약>"`으로 기록합니다. 2단계 3번(수정 → 확인 → 재제출)으로 이동합니다.
- 애매한 응답 → 다시 묻고, 아무것도 바꾸지 않습니다.

## 4단계 — Planning 문서 생성

전제 조건: discovery가 `approved`**이고** 그 파일의 해시가 여전히 일치해야 합니다. 아니면 보고하고 멈춥니다.

1. planning이 `not_started`/`outdated`이면 discovery revision N을 기준으로 파일 4개(02–05)를 생성한다고 알립니다. 그중 이미 있는 파일이 있으면(outdated 사이클) 어떤 파일을 수정하는지, 변경 근거(discovery rN → rM)가 무엇인지 설명하고 `file-safety.md`에 따라 확인을 받습니다. 확인되면 상태를 `in_progress`로, `based_on_discovery_revision: N`, `artifacts_done: []`로 하고 `ps_state.py event --stage planning --event generated ...`로 기록합니다.
2. `templates/`에 따라 02 → 03 → 04 → 05 순서로 생성합니다. `id-conventions.md`를 따릅니다. `artifacts_done`에 이미 있는 파일은 건너뜁니다(재개). 파일을 **하나 쓸 때마다** state의 `artifacts_done`에 추가합니다.
3. 추적성 점검(`id-conventions.md`)을 수행하고 결과를 05 문서의 `커버리지 점검(Coverage Check)` 섹션에 씁니다.
4. planning `revision`을 1 올리고 상태를 `awaiting_approval`로 바꾸고 `artifacts_done`을 비운 뒤 `ps_state.py event --stage planning --event submitted ...`로 기록합니다. 5단계로 이동합니다.

## 5단계 — Planning 승인 게이트

제시할 내용: 개수(FR/NFR/US/FLOW/AC), Must FR 목록, Planning 중 새로 생긴 ASM/Q, 추적성 점검 결과, 파일 경로, revision. **승인 / 수정 요청**을 묻고 멈춰서 기다립니다.

- 명시적 승인 → `ps_state.py approve --project . --stage planning --revision <제시한 N> --note "<승인 요지>"`를 실행합니다. 스크립트가 파일 4개의 해시, planning `approved`, design `locked` → `not_started`, `current_stage: design`, history `approved`를 기록합니다(승인된 discovery revision을 기준으로 하지 않으면 거부). 6단계로 이동합니다.
- 수정 요청 → 상태를 `in_progress`로 바꾸고 `ps_state.py event --stage planning --event changes_requested ...`로 기록합니다. 영향받는 파일과 하위 ID를 파악합니다(예: FR이 바뀌면 해당 US, FLOW, AC). 설명 → 확인 → `file-safety.md`에 따라 반영 → 추적성 재점검 → `revision`을 1 올림 → `awaiting_approval` → 다시 제시합니다. Planning 파일 4개는 단계 revision을 공유합니다. 그래서 내용이 바뀌지 않는 파일도 front matter `revision`만 올라간다는 사실을 설명에 포함해야 합니다.
- 수정 요청이 실제로는 Discovery의 사실(문제, 사용자, 범위)에 관한 것이면 → Discovery를 다시 열어야 하고(T7), 그러면 planning이 `outdated`가 된다는 점을 설명하고 먼저 확인을 받습니다.

## 6단계 — Milestone 1 완료

승인된 revision, 파일 목록, 아직 해결되지 않은 Q/ASM, Design 단계가 열렸다는 사실(Milestone 1에서는 구현하지 않음)을 보고합니다. 산출물 커밋을 제안합니다. 예: `git add docs/planning .ai-workflow && git commit -m "..."`(실행은 사용자가 합니다).

사용자가 승인된 문서를 바꾸려 하면 영향을 확인받은 뒤 `state-machine.md`의 T7(discovery) 또는 T9(planning)를 적용합니다.
