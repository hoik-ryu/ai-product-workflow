#!/bin/zsh
R=$(cd $(dirname $0); pwd); cd $R
sid(){ awk '/^SID/{print $2}' $R/logs/$1.txt; }
r(){ $R/run.sh $R/$1 $2 "$3" $4 > $R/logs/$2.txt 2>&1; echo "### $2"; sed -n '2,4p' $R/logs/$2.txt | cut -c1-200; sed -n '/---- check/,$p' $R/logs/$2.txt; python3 -I $R/kocheck.py $R/$1; }
snap(){ (cd $1; cat .ai-workflow/state.yaml docs/planning/*.md 2>/dev/null | shasum); }
G(){ git -C $1 -c user.name=t -c user.email=t@example.com "${@:2}"; }
ENG="$ENGINE/skills/product-start"
echo "===== PHASE A"; ./mk.sh main >/dev/null; ./mk.sh s08 >/dev/null; ./mk.sh s10 >/dev/null
mkdir -p s08/docs/planning; echo "# 기존 PRD (사람이 작성)" > s08/docs/planning/02-prd.md; H08=$(shasum s08/docs/planning/02-prd.md)
mkdir -p s10/skills/product-start; echo x > s10/skills/product-start/SKILL.md
r main s01 "/product-start 동네 도서관 좌석 예약 앱을 만들고 싶어요" & r s08 s08 "/product-start 배드민턴 앱" > logs/s08.out & r s10 s10 "/product-start 테스트 아이디어" > logs/s10.out & wait
cat logs/s08.out logs/s10.out; [[ $H08 == $(shasum s08/docs/planning/02-prd.md) ]] && echo "S08 existing file UNCHANGED"; echo "S10 .ai-workflow exists? $(test -e s10/.ai-workflow && echo YES || echo NO)"
echo "===== PHASE B"; r main s02 "질문은 건너뛰고 PRD 바로 써줘" $(sid s01)
ls main/docs/planning
r main s03 "/product-start"; S3=$(sid s03)
H=$(snap main); r main s04 "좋네요" $S3; [[ $H == $(snap main) ]] && echo "S04 STATE+DOCS UNCHANGED"
r main s05a "수정 요청: 도서관은 1곳, 플랫폼은 모바일 웹, 체크인은 QR이고 예약 시작 후 15분 내 미체크인 시 자동 취소. 관리자 화면은 MVP에 포함." $S3
r main s05b "진행" $S3; ls main/.ai-workflow/backup; grep -m1 '^revision' main/.ai-workflow/backup/01-discovery.md
r main s06 "승인" $S3
python3 -I trace.py main
echo "===== PHASE C"; ./mk.sh s07 >/dev/null; cp -R main/docs main/.ai-workflow s07/; rm s07/docs/planning/0[345]-*.md
python3 -I - s07/.ai-workflow/state.yaml <<'PY'
import sys,re;p=sys.argv[1];t=open(p).read()
t,n=re.subn(r'(\n  planning:\n    status: )awaiting_approval([^\n]*\n    revision: )1',r'\1in_progress\g<2>0',t)
t=re.sub(r'artifacts_done: \[\][^\n]*','artifacts_done:\n      - docs/planning/02-prd.md',t,count=1)  # 줄 끝 주석까지 바꿈(주석이 경로에 붙어 YAML이 깨지는 것 방지)
t='\n'.join(l for l in t.split('\n') if not ('stage: planning' in l and 'submitted' in l)); open(p,'w').write(t); print('s07 fixture replaced',n)
PY
shasum s07/docs/planning/02-prd.md > s07.sha
./mk.sh s09 >/dev/null; cp -R main/.ai-workflow s09/
r s07 s07 "/product-start" > logs/s07.out & r s09 s09 "/product-start" > logs/s09.out & r main s12 "승인" $S3 > logs/s12.out & wait
cat logs/s07.out logs/s09.out logs/s12.out; shasum -c s07.sha | sed 's#.*/##'; python3 -I trace.py s07
echo "===== PHASE D"; G main add docs .ai-workflow; G main commit -qm "fixture approved"
for n in s11 s13 s17; do cp -R main $n; ln -sfn $ENG $n/.claude/skills/product-start; done
echo "- 추가 메모: 스터디 카페도 지원?" >> s11/docs/planning/01-discovery.md
python3 -I - s17/docs/planning/03-user-stories.md <<'PY'
import sys,re;p=sys.argv[1];t=open(p).read();t2,n=re.subn(r'(\*\*우선순위\*\*: )Should',r'\1Must',t,count=1)
if not n: t2=t+'\n- 수동 메모 추가\n'
open(p,'w').write(t2);print('s17 edited, should->must:',n)
PY
cp s17/docs/planning/03-user-stories.md s17.03.dirty
A11=$(snap s11); A13=$(snap s13); A17=$(snap s17)
r s11 s11 "/product-start" > logs/s11.out & r s13 s13 "/product-start 배드민턴 로테이션 학습 앱" > logs/s13.out & r s17 s17a "/product-start" > logs/s17a.out & r main s14a "/product-start" > logs/s14a.out & wait
cat logs/s11.out logs/s13.out logs/s17a.out logs/s14a.out
[[ $A11 == $(snap s11) ]] && echo "S11 UNCHANGED"; [[ $A13 == $(snap s13) ]] && echo "S13 UNCHANGED"; [[ $A17 == $(snap s17) ]] && echo "S17a UNCHANGED"
echo "===== PHASE E"
r s17 s17b "(a) 재검토로 진행해줘. 수동 변경을 유지하고 관련 문서도 맞춰줘." $(sid s17a) > logs/s17b.out & r main s14b "수정 요청: 2번째 Must FR의 설명에 '모바일 웹 기준'이라는 문구만 추가해줘" $(sid s14a) > logs/s14b.out & wait
cat logs/s17b.out logs/s14b.out; echo "--- s17b plan:"; grep -E "revision|백업" logs/s17b.txt | head -6; echo "--- s14b plan:"; grep -E "revision|백업" logs/s14b.txt | head -6
r s17 s17c "진행" $(sid s17a) > logs/s17c.out & r main s14c "진행" $(sid s14a) > logs/s14c.out & wait
cat logs/s17c.out logs/s14c.out
echo "S16 s17 backups: $(ls s17/.ai-workflow/backup | tr '\n' ' ')"; cmp s17/.ai-workflow/backup/03-user-stories.md s17.03.dirty && echo "S16 backup == pre-edit dirty content"
echo "S14 main backups (expect only 01): $(ls main/.ai-workflow/backup | tr '\n' ' ')"; git -C main diff --stat
python3 -I trace.py main; python3 -I trace.py s17
r main s18 "승인" $(sid s14a)
G main add docs .ai-workflow; G main commit -qm "planning r2 approved"
echo "===== PHASE F (interactive)"; ./mk.sh inter >/dev/null
printf '{\n  "permissions": {\n    "additionalDirectories": ["%s"]\n  }\n}\n' "$ENGINE/skills" > inter/.claude/settings.local.json
expect inter.exp logs/inter.log inter > /dev/null 2>&1
python3 -I check.py inter; ls -A inter/.ai-workflow 2>&1
perl -pe 's/\e\[[0-9;?]*[ -\/]*[@-~]//g; s/\e\][^\a]*\a//g; s/\e[()][0-9A-Z]//g; s/\r/\n/g' logs/inter.log | grep -v '^\s*$' | awk '!seen[$0]++' | grep -E "^ *[0-9]\.[^ ]" | head -5
echo "===== DONE"
