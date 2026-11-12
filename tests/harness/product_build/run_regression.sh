#!/bin/zsh
# /product-build 대화 검증(P1–P5). 실제 `claude -p --model sonnet`(headless)을 씁니다. 약 10–20분, 모델 비용이 듭니다.
# 사용법: tests/harness/product_build/run_regression.sh [작업 폴더]   — 엔진 저장소와 다른 제품 저장소는 건드리지 않습니다.
set -u
H=$(cd "$(dirname "$0")"; pwd)
export ENGINE=$(cd "$H/../../.."; pwd)
export W=${1:-$(mktemp -d -t product-build-regression)}
for c in claude git python3; do command -v $c >/dev/null || { echo "필요한 명령이 없습니다: $c"; exit 2; }; done
mkdir -p "$W/logs"
echo "작업 폴더: $W (로그: $W/all.log)"
zsh "$H/run_all.sh" > "$W/all.log" 2>&1
python3 -I "$H/summarize.py" "$W/all.log"
