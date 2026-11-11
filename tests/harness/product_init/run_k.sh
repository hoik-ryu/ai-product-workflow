#!/bin/zsh
# /product-init Skill 회귀(K1–K10). 실제 claude -p, 네트워크(보일러플레이트 Git 태그), Docker(K7b db·smoke)가 필요합니다.
# 사용법: BOILERPLATE_SRC=<보일러플레이트 Git URL(manifest와 v1.0.0 태그 포함)> tests/harness/product_init/run_k.sh [작업 폴더]
set -u
H=$(cd "$(dirname "$0")"; pwd)
export ENGINE=$(cd "$H/../../.."; pwd)
SRC=${BOILERPLATE_SRC:?BOILERPLATE_SRC 환경변수(보일러플레이트 Git URL)가 필요합니다}
R=${1:-$(mktemp -d -t product-init-regression)}
mkdir -p "$R/logs"; cp "$H/run.sh" "$R/"; chmod +x "$R/run.sh"
for c in claude git python3; do command -v $c >/dev/null || { echo "필요한 명령이 없습니다: $c"; exit 2; }; done
docker info >/dev/null 2>&1 || echo "경고: Docker가 꺼져 있어 K7b(db·smoke)는 실패로 기록됩니다."
W=$R/work
python3 -I "$H/mk.py" "$R" > /dev/null
sid(){ awk '/^SID/{print $2}' "$R/logs/$1.txt"; }
r(){ "$R/run.sh" "$1" "$2" "$3" "${4:-}" > "$R/logs/$2.txt" 2>&1; echo "### $2"; cut -c1-400 "$R/logs/$2.txt"; echo; }
{
r $W/k2_unapproved k1 "/product-init $SRC v1.0.0"
echo "K1 boilerplate.json exists? $(test -e $W/k2_unapproved/.ai-workflow/boilerplate.json && echo YES || echo NO)"
r $W/k2_main k2 "/product-init $SRC v1.0.0"; S=$(sid k2)
r $W/k2_main k3 "slug는 badminton-playbook, 제목은 Badminton Playbook으로 해 주세요." $S
r $W/k2_main k4 "좋아요" $S
r $W/k2_main k5 "적용 승인. 전용 브랜치 생성도 승인합니다." $S
r $W/k2_main k6 ".gitignore만 병합 승인합니다. README.md는 그대로 두세요." $S
r $W/k2_main k7a "fe, be, db, smoke 검증을 진행하고 싶어요. 실행 전에 명령을 보여 주세요." $S
r $W/k2_main k7b "검증 실행 승인합니다. 네 단계 모두 실행해 주세요." $S
r $W/k2_main k8 "/product-init"
echo "// user edit" >> $W/k2_main/frontend/src/main.tsx
r $W/k2_main k9 "/product-init"
echo "K9 user edit preserved? $(tail -1 $W/k2_main/frontend/src/main.tsx | grep -q 'user edit' && echo YES || echo NO)"
echo "K9 engine check user_modified: $(python3 -I "$ENGINE/skills/product-init/scripts/product_init.py" check --project $W/k2_main | python3 -I -c 'import json,sys;print(",".join(json.load(sys.stdin).get("cross_verify",{}).get("user_modified",[])))')"
python3 - $W/k2_main/frontend/src/main.tsx <<'PY'
import sys;p=sys.argv[1];t=open(p).read();open(p,'w').write(t.replace("// user edit\n",""))
PY
r $W/k2_main k10 "/product-start"
echo "README unchanged? $(git -C $W/k2_main diff --quiet HEAD -- README.md docs .ai-workflow/state.yaml && echo YES || echo NO)"
echo "===== DONE"
} > "$R/all.log" 2>&1
python3 -I "$ENGINE/skills/product-init/scripts/product_init.py" cleanup --project "$W/k2_main" --remove-volumes --confirm >/dev/null 2>&1 || true
echo "작업 폴더: $R"; python3 -I "$H/summarize.py" "$R/all.log"
