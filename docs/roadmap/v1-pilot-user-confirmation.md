# v1.0 파일럿: 사용자 확인 절차와 권한 설정 제안

상태: **제안**(적용하지 않음, 격리 환경 검증 완료 — 5절). 권한 설정 변경은 사용자가 검토·확인한 뒤 사용자가 적용합니다. AI가 만든 설정은 운영 환경에 그대로 적용하지 말고 테스트 프로젝트에서 먼저 확인하세요.

## 1. 왜 필요한가

엔진은 `--note`·`--confirm` 같은 사용자 확인 문장을 **누가 썼는지 구별할 수 없습니다**. Claude가 문장을 지어 넣으면 엔진 기록상으로는 사용자 승인과 같아 보입니다. Claude Code 문서에도 스크립트가 "사람이 확인했다"는 사실을 검증할 수단(환경 변수·필드)은 없습니다. 그래서 두 가지를 분리해 운영합니다.

| 구분 | 무엇을 보장 | 누가 |
|---|---|---|
| 명령 실행 허가 | 승인·선택 명령이 실행되기 직전에 사람이 화면에서 확인 | Claude Code 권한(`ask`)·hook |
| 제품 워크플로 승인 기록 | 무엇을 언제 승인했는지(해시·스냅샷·사용자 문장) | 엔진(design.json·state.yaml) |

권한 확인을 통과했다고 제품 승인이 되는 것은 아니고, 엔진 승인 기록이 있다고 사람이 확인했다는 증거가 되는 것도 아닙니다. 파일럿에서는 둘 다 둡니다.

## 2. 사람이 확인해야 하는 명령

| 영역 | 명령 |
|---|---|
| 승인·재검토 | `product_design.py approve`, `reopen`, `migrate --confirm`, `rebase --confirm`; `ps_state.py approve`, `submit`, `reopen`, `migrate-snapshot` |
| 선택·건너뛰기 | `explore-choose`, `explore-skip`, `explore-adopt` |
| 정책·설정 | `explore-config`(탐색 켜기·측정 명령 지문), `explore-ref policy`, `explore-asset style` |
| 개인정보·권리 | `explore-ref privacy --by user`, `explore-ref confirm`, `explore-ref track`, `explore-asset confirm` |
| 외부 전송 | `explore-renderer enable`, `explore-renderer allow-transfer`(Figma 등) |

Skill 지시(product-design `reference/exploration.md` 15절): 확인 항목에는 사용자가 이번 대화에서 실제로 한 말만 옮기고 지어내지 않습니다.

## 3. 권한 규칙 제안(`.claude/settings.json`, 프로젝트 공유)

Claude Code 문서 기준(permissions, permission-modes, settings): 평가 순서는 deny → ask → allow이고 범위 간 규칙은 합쳐지며, 하위 범위의 allow가 상위 범위의 ask·deny를 뒤집지 못합니다. 명시적 `ask` 규칙은 auto 모드·bypassPermissions에서도 확인 창을 띄우고, `dontAsk` 모드에서는 거부됩니다. 프로젝트 `ask`·`deny`는 워크스페이스 신뢰 승인 전에도 적용됩니다.

```json
{
  "permissions": {
    "ask": [
      "Bash(python3 *product_design.py approve *)",
      "Bash(python3 *product_design.py reopen *)",
      "Bash(python3 *product_design.py migrate *)",
      "Bash(python3 *product_design.py rebase *)",
      "Bash(python3 *product_design.py explore-choose *)",
      "Bash(python3 *product_design.py explore-skip *)",
      "Bash(python3 *product_design.py explore-adopt *)",
      "Bash(python3 *product_design.py explore-config *)",
      "Bash(python3 *product_design.py explore-renderer *)",
      "Bash(python3 *product_design.py explore-asset confirm *)",
      "Bash(python3 *product_design.py explore-asset style *)",
      "Bash(python3 *product_design.py explore-ref privacy *)",
      "Bash(python3 *product_design.py explore-ref confirm *)",
      "Bash(python3 *product_design.py explore-ref track *)",
      "Bash(python3 *product_design.py explore-ref policy *)",
      "Bash(python3 *ps_state.py approve *)",
      "Bash(python3 *ps_state.py submit *)",
      "Bash(python3 *ps_state.py reopen *)",
      "Bash(python3 *ps_state.py migrate-snapshot *)"
    ]
  }
}
```

한계(문서에 명시됨): Bash 규칙은 보안 경계가 아닙니다. `python`(3 없이)·절대 경로 인터프리터·`env X=1 …`·`bash -c "…"`·`sh -c`로 실행하면 위 규칙에 걸리지 않을 수 있습니다. 그래서 아래 hook을 함께 두는 것을 권합니다.

## 4. hook 제안(PreToolUse, 문자열 전체 검사)

`.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      { "matcher": "Bash", "hooks": [ { "type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR\"/.claude/hooks/confirm-gated-cmds.py" } ] }
    ]
  }
}
```

`.claude/hooks/confirm-gated-cmds.py`(제안 — 만들지 않았음):

```python
import json, re, sys
cmd = (json.load(sys.stdin).get("tool_input") or {}).get("command", "")
GATED = re.compile(r"(product_design|ps_state)\.py\b.*?\s(approve|reopen|submit|migrate(-snapshot)?|rebase|"
                   r"explore-(choose|skip|adopt|config|renderer)|explore-asset\s+(confirm|style)|"
                   r"explore-ref\s+(privacy|confirm|track|policy))\b", re.S)
if GATED.search(cmd):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask",
                                             "permissionDecisionReason": "제품 워크플로 승인·선택·확인 명령입니다. 사용자 본인의 결정인지 확인하세요."}}))
```

확인하지 못한 점: hook이 bypassPermissions에서도 실행되는지, `acceptEdits`에서 ask가 적용되는지는 문서에서 확인하지 못했습니다. 파일럿 시작 전 테스트 프로젝트에서 실제로 확인 창이 뜨는지 시험하세요. hook도 문자열 검사라 완전한 방어는 아닙니다(스크립트 파일을 새로 써서 간접 실행하는 경우 등).

## 5. 격리 환경 검증 결과(Claude Code 2.1.322, 2026-11-18)

임시 프로젝트(가짜 엔진 스크립트: 실행되면 표시 파일에만 기록)에서 `claude -p`로 확인했습니다. 실제 저장소·사용자 설정은 바꾸지 않았고, 설정은 명령줄 `--settings`로만 넣었습니다(`--setting-sources project`, 사용자 설정 미사용). 넓은 allow(`Bash(python3 *)`·`Bash(env *)`·`Bash(bash *)`·`Bash(/usr/bin/python3 *)`)를 함께 두어 "allow가 넓어도 승인 명령은 확인되는가"를 봤습니다.

| 설정 \ 명령 | 읽기(`status`) | `approve` 직접 | `ps_state approve` | `env X=1 python3 …` | `bash -c '…'` | `/usr/bin/python3 …` |
|---|---|---|---|---|---|---|
| ask 규칙만 | 실행 | 확인 필요 | 확인 필요 | 확인 필요 | **실행됨(우회)** | 확인 필요 |
| hook만 | 실행 | 확인 필요 | 확인 필요 | 확인 필요 | 확인 필요 | 확인 필요 |
| ask 규칙 + hook | 실행 | 확인 필요 | 확인 필요 | 확인 필요 | 확인 필요 | 확인 필요 |

- 세 권한 모드(default·acceptEdits·bypass(`--dangerously-skip-permissions`)) 모두 같은 결과였습니다. **hook은 bypass 모드에서도 실행되어 ask를 적용**했고, 규칙의 ask도 bypass에서 적용됐습니다.
- 비대화형(`-p`)에서는 "확인 필요"가 확인 창 없이 거부로 처리됩니다. 대화형 확인 창 동작(사용자가 허용·거부)은 이 검증에 포함되지 않았습니다 — 파일럿 첫날 사람이 직접 한 번 확인하세요.
- 작업 공간 신뢰 전에는 프로젝트 `.claude/settings.json`의 **allow가 무시되고 ask·deny는 적용**됐습니다(일반 읽기 명령까지 확인 필요가 됨). 파일럿 프로젝트는 신뢰 승인 후 사용합니다.
- 일반 읽기 명령(`status`·`check` 등)은 ask 대상이 아니어서 그대로 실행됩니다.
- 남는 우회: 새 스크립트 파일을 써서 그 안에서 엔진을 부르는 간접 실행, 명령 문자열에 엔진 이름이 드러나지 않는 실행(예: 변수·별칭), `dontAsk`·`auto` 모드는 시험하지 않았습니다. hook·규칙은 실수 방지 장치이지 보안 경계가 아닙니다.
- 권장: **ask 규칙 + hook을 함께** 둡니다(규칙만으로는 `bash -c` 우회가 확인됨).

## 6. 파일럿 운영 규칙

- 권한 모드는 기본(default) 또는 auto로 하고, `bypassPermissions`·`dontAsk`는 쓰지 않습니다.
- 승인 요청 때 Claude는 무엇을 승인하는지(revision·바뀐 파일·자산 스냅샷)를 먼저 보여 주고, 사용자의 답을 그대로 `--note`에 옮깁니다.
- 승인 기록(state.yaml·design.json)은 Git 커밋으로 남기고, 사람이 diff를 확인합니다.

출처: https://code.claude.com/docs/en/permissions.md · https://code.claude.com/docs/en/permission-modes.md · https://code.claude.com/docs/en/settings.md · https://code.claude.com/docs/en/hooks.md
