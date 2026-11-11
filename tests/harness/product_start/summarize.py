#!/usr/bin/env python3
"""/product-start 회귀 로그(all.log) 자동 판정: tests/scenarios.md의 S01–S19 기대 결과를 로그의 검사 출력으로 확인합니다.
사용법: python3 summarize.py <all.log>   (19/19면 종료 코드 0)
판정 근거는 run_all.sh가 남기는 check.py·kocheck.py·trace.py 출력과 파일 비교 줄입니다. 모델 응답 문장은 판정에 쓰지 않습니다.
"""
import re
import sys

log = open(sys.argv[1], encoding="utf-8", errors="replace").read()
blocks = {}
for m in re.finditer(r"^### (\S+)\n(.*?)(?=^### |^===== |\Z)", log, re.M | re.S):
    blocks[m.group(1)] = m.group(2)
phase_f = log.split("===== PHASE F", 1)[1] if "===== PHASE F" in log else ""


def st(name, stage):
    m = re.search(rf"^\s+{stage}: status=(\w+) rev=(\w+)", blocks.get(name, ""), re.M)
    return (m.group(1), m.group(2)) if m else (None, None)


def ok_common(name):
    return "ALLOWLIST OK | SENTINELS OK" in blocks.get(name, "")


def hashes(name):
    return dict(re.findall(r"hash docs/planning/(\S+): (MATCH|MISMATCH)", blocks.get(name, "")))


def fm(name):
    return dict(re.findall(r"fm (\S+): revision=(\w+)", blocks.get(name, "")))


def korean_ok(name, n):
    k = re.search(r"^KOREAN (.*)$", blocks.get(name, ""), re.M)
    return bool(k) and k.group(1).count(":OK") == n and ":NG" not in k.group(1)


trace_lines = re.findall(r"^FR \d+ US \d+ FLOW \d+ AC \d+ \| (.*)$", log, re.M)
checks = {
    "S01": ok_common("s01") and st("s01", "discovery") == ("in_progress", "0") and st("s01", "planning")[0] == "locked" and not fm("s01"),
    "S02": ok_common("s02") and st("s02", "discovery") == ("awaiting_approval", "1") and set(fm("s02")) == {"01-discovery.md"},
    "S03": ok_common("s03") and st("s03", "discovery") == ("awaiting_approval", "1"),
    "S04": "S04 STATE+DOCS UNCHANGED" in log and st("s04", "discovery") == ("awaiting_approval", "1"),
    "S05": ok_common("s05b") and st("s05b", "discovery") == ("awaiting_approval", "2") and re.search(r"^revision: 1$", blocks.get("s05b", ""), re.M) is not None,
    "S06": ok_common("s06") and st("s06", "discovery")[0] == "approved" and st("s06", "planning") == ("awaiting_approval", "1")
           and hashes("s06").get("01-discovery.md") == "MATCH" and korean_ok("s06", 5),
    "S07": ok_common("s07") and st("s07", "planning") == ("awaiting_approval", "1") and "02-prd.md: OK" in log
           and all(v == "1" for k, v in fm("s07").items() if k != "01-discovery.md") and len(fm("s07")) == 5,
    "S08": ok_common("s08") and "S08 existing file UNCHANGED" in log,
    "S09": ok_common("s09") and hashes("s09").get("01-discovery.md") == "MISMATCH" and not fm("s09"),
    "S10": "S10 .ai-workflow exists? NO" in log and re.search(r"ALLOWLIST VIOLATION \['skills/product-start/SKILL.md'\] \| SENTINELS OK", blocks.get("s10", "")) is not None,
    "S11": ok_common("s11") and hashes("s11").get("01-discovery.md") == "MISMATCH" and "S11 UNCHANGED" in log,
    "S12": ok_common("s12") and st("s12", "planning") == ("approved", "1") and st("s12", "design")[0] == "not_started"
           and list(hashes("s12").values()).count("MATCH") == 5,
    "S13": ok_common("s13") and "S13 UNCHANGED" in log,
    "S14": ok_common("s14c") and st("s14c", "planning") == ("awaiting_approval", "2")
           and re.search(r"^S14 main backups \(expect only 01\): 01-discovery\.md\s*$", log, re.M) is not None,
    "S15": bool(trace_lines) and all(l == "FR w/o US: [] | US w/o AC: [] | US w/o FLOW: [] | undefined: []" for l in trace_lines),
    "S16": "S16 backup == pre-edit dirty content" in log,
    "S17": ok_common("s17a") and hashes("s17a").get("03-user-stories.md") == "MISMATCH" and "S17a UNCHANGED" in log
           and st("s17c", "planning") == ("awaiting_approval", "2") and set(fm("s17c").values()) == {"2"},
    "S18": ok_common("s18") and st("s18", "planning") == ("approved", "2") and list(hashes("s18").values()).count("MATCH") == 5,
    "S19": "ALLOWLIST OK | SENTINELS OK" in phase_f and re.search(r"discovery: status=in_progress rev=0", phase_f) is not None,
}
common_ok = all("SENTINELS OK" in b for b in blocks.values())
for k, v in checks.items():
    print(("PASS " if v else "FAIL ") + k)
passed = sum(checks.values())
print(f"\n공통(모든 실행의 기존 파일 해시 불변): {'OK' if common_ok else 'FAIL'}")
print(f"RESULT {passed}/{len(checks)} passed")
sys.exit(0 if passed == len(checks) and common_ok else 1)
