#!/bin/zsh
# /product-start 회귀(S01–S19) 실행기. 실제 `claude -p`(headless, --model sonnet)와 `expect`(S19 대화형)를 씁니다.
# 시간 약 30–40분, 모델 사용 비용이 듭니다. 사용법: tests/harness/product_start/run_regression.sh [작업 폴더]
# 작업 폴더를 주지 않으면 임시 폴더를 만듭니다. 엔진 저장소와 제품 저장소는 건드리지 않습니다.
set -u
H=$(cd "$(dirname "$0")"; pwd)
export ENGINE=$(cd "$H/../../.."; pwd)
W=${1:-$(mktemp -d -t product-start-regression)}
for c in claude expect git python3; do command -v $c >/dev/null || { echo "필요한 명령이 없습니다: $c"; exit 2; }; done
mkdir -p "$W/logs"
cp "$H"/{run_all.sh,run.sh,mk.sh,check.py,kocheck.py,trace.py,inter.exp} "$W/"
chmod +x "$W"/{run_all.sh,run.sh,mk.sh}
python3 -I -c "import json,hashlib;print(json.dumps({'README.md':hashlib.sha256(b'# Existing product repo\n').hexdigest(),'src/main.py':hashlib.sha256(b\"print('hello')\n\").hexdigest()}))" > "$W/sentinels.json"
echo "작업 폴더: $W (로그: $W/all.log)"
(cd "$W" && zsh ./run_all.sh > all.log 2>&1)
python3 -I "$H/summarize.py" "$W/all.log"
