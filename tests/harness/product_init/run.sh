#!/bin/zsh
# run.sh <제품 경로> <로그 이름> <프롬프트> [세션 ID] — claude -p 한 턴 실행 후 boilerplate.json 상태 요약
P=$1; OUT=$2; PROMPT=$3; SID=${4:-}; L=$(cd "$(dirname "$0")"; pwd)/logs
cd "$P"
ARGS=(-p "$PROMPT" --model sonnet --output-format json --permission-mode acceptEdits --add-dir "$ENGINE/skills"
  --allowedTools "Bash(python3:*)" "Bash(mktemp:*)" "Bash(git:*)" "Bash(ls:*)" "Bash(cat:*)" "Bash(grep:*)" "Bash(find:*)" "Bash(shasum:*)" "Bash(date:*)")
[[ -n $SID ]] && ARGS+=(--resume $SID)
claude "${ARGS[@]}" < /dev/null > "$L/$OUT.json" 2>&1
python3 -I -c "import json;d=json.load(open('$L/$OUT.json'));print('SID',d.get('session_id'),'cost',round(d.get('total_cost_usd',0),3));print(d.get('result'))" 2>/dev/null || tail -5 "$L/$OUT.json"
echo "---- state:"; python3 -I -c "
import json,os;p='.ai-workflow/boilerplate.json'
if os.path.exists(p):
  s=json.load(open(p));print('status',s['status'],'approved',s['approval']['approved'],'files_done',len(s['files_done']),'merges',[m['path'] for m in s['merges']],'branch',s.get('branch'),'verify',{k:v.get('result') for k,v in s.get('verification',{}).items() if isinstance(v,dict)})
else: print('no boilerplate.json')"
git status --porcelain | grep -v '^?? .claude' | head -5; echo "branch: $(git branch --show-current)"
