#!/bin/zsh
# run.sh <제품 경로> <로그 이름> <프롬프트> [세션 ID] — claude -p 한 턴 실행 후 상태 요약(check.py)
P=$1; OUT=$2; PROMPT=$3; SID=${4:-}; H=$(cd "$(dirname "$0")"; pwd); L=$W/logs
cd "$P"
ARGS=(-p "$PROMPT" --model sonnet --output-format json --permission-mode acceptEdits --add-dir "$ENGINE/skills"
  --allowedTools "Bash(python3:*)" "Bash(git status:*)" "Bash(git diff:*)" "Bash(git log:*)" "Bash(git branch:*)" "Bash(ls:*)" "Bash(cat:*)" "Bash(grep:*)" "Bash(find:*)" "Bash(mkdir:*)")
[[ -n $SID ]] && ARGS+=(--resume $SID)
claude "${ARGS[@]}" < /dev/null > "$L/$OUT.json" 2>&1
python3 -I -c "import json;d=json.load(open('$L/$OUT.json'));print('SID',d.get('session_id'),'turns',d.get('num_turns'),'cost',round(d.get('total_cost_usd',0),3));print(d.get('result'))" 2>/dev/null || tail -5 "$L/$OUT.json"
echo "---- check:"; python3 -I "$H/check.py" "$P" "$W/protected.json"
