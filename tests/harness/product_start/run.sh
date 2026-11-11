#!/bin/zsh
P=$1; OUT=$2; PROMPT=$3; SID=$4; L=$(cd $(dirname $0); pwd)/logs; H=$(cd $(dirname $0); pwd)
cd $P
ARGS=(-p "$PROMPT" --model sonnet --output-format json --permission-mode acceptEdits --add-dir "$ENGINE/skills"
  --allowedTools "Bash(shasum:*)" "Bash(date:*)" "Bash(git:*)" "Bash(mkdir:*)" "Bash(ls:*)" "Bash(cat:*)" "Bash(cp:*)" "Bash(find:*)" "Bash(cmp:*)" "Bash(test:*)" "Bash(cut:*)" "Bash(grep:*)" "Bash(python3:*)" "Bash(mktemp:*)")
[[ -n $SID ]] && ARGS+=(--resume $SID)
claude "${ARGS[@]}" < /dev/null > $L/$OUT.json 2>&1
python3 -I -c "import json,sys;d=json.load(open('$L/$OUT.json'));print('SID',d.get('session_id'),'cost',round(d.get('total_cost_usd',0),3));print(d.get('result'))" 2>/dev/null || tail -5 $L/$OUT.json
echo "---- check:"; python3 -I $H/check.py $P
