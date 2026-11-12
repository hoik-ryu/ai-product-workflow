#!/bin/zsh
# P1–P5 대화 시나리오. W(작업 폴더)·ENGINE은 run_regression.sh가 정합니다.
set -u
H=$(cd "$(dirname "$0")"; pwd)
PB=(python3 -I "$ENGINE/skills/product-build/scripts/product_build.py")  # zsh는 문자열 변수를 단어로 나누지 않으므로 배열로
sid() { python3 -I -c "import json;print(json.load(open('$W/logs/$1.json')).get('session_id',''))"; }
D=$(python3 -I "$H/mk.py" "$W" | tail -1)
echo "PRODUCT $D"
echo "### p1"; zsh "$H/run.sh" "$D" p1 "/product-build"
echo "### p2"; zsh "$H/run.sh" "$D" p2 "구현 계획 r1을 승인합니다. 이어서 구현을 진행해 주세요." "$(sid p1)"
echo "### p3"   # 세션 중단 재현: B1을 (사용자 확인 받은 세션이) 시작해 B1-T1까지 끝낸 뒤 잠금을 남긴 채 끊김
OUT=$(cd "$D" && "${PB[@]}" batch-start --project "$D" --batch B1 --owner crashed-session --confirm-risk --note "사용자 확인: 연락처 수정 구현 진행")
echo "P3_START $OUT" | head -c 400; echo
LOCK=$(echo "$OUT" | python3 -I -c "import json,sys;print(json.load(sys.stdin)['lock_id'])")
[[ -n $LOCK ]] || { echo "P3_SETUP_FAILED"; exit 1; }
mkdir -p "$D/app/me"
printf 'import re\n\n\ndef update_contact(profile, phone):\n    if not re.fullmatch(r"[0-9-]+", phone or ""):\n        raise ValueError("연락처는 숫자와 하이픈만 쓸 수 있습니다")\n    profile = dict(profile)\n    profile["phone"] = phone\n    return profile\n' > "$D/app/me/profile.py"
(cd "$D" && "${PB[@]}" task-done --project "$D" --batch B1 --task B1-T1 --lock "$LOCK" >/dev/null)
echo "CRASH_LOCK $LOCK"
python3 -I "$H/check.py" "$D" "$W/protected.json"
echo "### p4"; zsh "$H/run.sh" "$D" p4 "/product-build resume"
echo "### p5"; zsh "$H/run.sh" "$D" p5 "중단된 이전 세션은 이미 종료되었고 다른 세션은 없습니다. 잠금을 넘겨받아 이어서 진행해 주세요." "$(sid p4)"
echo "### p6"   # 원장: 접수 권한 범위(AC-004, B2)를 차단 정책으로 등록(분석 결과) → 새 세션이 결정을 추측하지 않고 영향을 보여 주는지
(cd "$D" && "${PB[@]}" ledger add --project "$D" --type policy --title "접수 권한 범위" --desc "AC-004: 직원 역할만인지, 관리자도 포함인지 기획에 없음" --acs AC-004 --blocking --rationale "권한 정책" >/dev/null)
zsh "$H/run.sh" "$D" p6 "/product-build"
echo "### p7"; zsh "$H/run.sh" "$D" p7 "POL-001은 직원과 관리자 모두 접수할 수 있는 것으로 결정합니다. 기록만 하고 B2는 아직 시작하지 마세요." "$(sid p6)"

