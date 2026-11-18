#!/usr/bin/env python3
"""전체 테스트 실행·집계: 스위트별 PASS / FAIL / SKIP을 나눠 세고, 실행 환경 조건(pnpm·Docker·Chrome·Node·PD_FULL)을 함께 보고합니다.

판정
- FAILED(종료 1): FAIL 줄이 하나라도 있거나 스위트가 0이 아닌 코드로 끝남(RESULT 줄 없이 끝난 경우 포함)
- INCOMPLETE(종료 3): 실패는 없지만 SKIP이 있음 — 필수 검증 일부가 환경 조건 때문에 실행되지 않았으므로 "전체 통과"로 표시하지 않습니다.
  --allow-skip이면 SKIP이 있어도 종료 0(표시는 INCOMPLETE 그대로)
- PASSED(종료 0): 모든 스위트가 FAIL·SKIP 없이 끝남

스위트 출력 규약: 각 검사는 'PASS 이름' / 'FAIL 이름' / 'SKIP 이름' 줄로 출력합니다(기존 스위트 공통).
실행: python3 tests/run_all.py [--allow-skip] [--only 이름조각] [--e2e-real-browser]
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def environment() -> dict:
    def ok(cmd):
        try:
            return subprocess.run(cmd, capture_output=True, timeout=20).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False
    chrome = any(Path(p).exists() for p in ("/Applications/Google Chrome.app", "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser"))
    node = shutil.which("node")
    node_ver = subprocess.run([node, "--version"], capture_output=True, text=True).stdout.strip() if node else None
    return {
        "pnpm": bool(shutil.which("pnpm")),
        "docker_running": bool(shutil.which("docker")) and ok(["docker", "info"]),
        "chrome": chrome,
        "node": node_ver,
        "PD_FULL": os.environ.get("PD_FULL") == "1",
    }


CONDITIONS = {
    "pnpm": "product_design_test·dd·v2·impact·theme의 프리뷰 빌드·승인 검사(없으면 SKIP), E2E Preview 승인 경로(없으면 프리뷰 면제 경로로 진행)",
    "docker_running": "product_init_test I12f(Docker 실행 검증, 꺼져 있으면 SKIP)",
    "PD_FULL": "product_design_theme_test F1–F3(프리뷰 승인 기록 렌더러·테마, PD_FULL=1이 아니면 SKIP)",
    "chrome": "product_workflow_e2e_test --real-browser(실제 Chrome 측정, 기본 실행에는 포함되지 않음)",
    "node": "실제 Chrome 측정 어댑터는 Node 20 이상(--experimental-websocket) 필요",
}


def run_suite(path: Path, extra: list[str]) -> dict:
    t0 = time.time()
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    p = subprocess.run([sys.executable, str(path), *extra], capture_output=True, text=True, env=env)
    out = p.stdout + p.stderr
    lines = out.splitlines()
    c = {k: sum(1 for x in lines if x.startswith(k + " ")) for k in ("PASS", "FAIL", "SKIP")}
    has_result = any(x.startswith("RESULT") or x.rstrip().endswith(" passed") for x in lines)
    return {"name": path.name, "exit": p.returncode, "secs": round(time.time() - t0), **c, "result_line": has_result,
            "fails": [x for x in lines if x.startswith("FAIL ")][:10], "skips": [x for x in lines if x.startswith("SKIP ")][:10],
            "tail": "\n".join(lines[-5:]) if p.returncode != 0 and not c["FAIL"] else ""}


def main() -> int:
    args = sys.argv[1:]
    only = args[args.index("--only") + 1] if "--only" in args else None
    suites = sorted(p for p in HERE.glob("*_test.py") if not only or only in p.name)
    env = environment()
    print("실행 환경:")
    for k, v in env.items():
        print(f"  {k}: {v}  — {CONDITIONS.get(k, '')}")
    print()
    rows = []
    for s in suites:
        extra = ["--real-browser"] if s.name == "product_workflow_e2e_test.py" and "--e2e-real-browser" in args else []
        r = run_suite(s, extra)
        rows.append(r)
        flag = "FAIL" if (r["FAIL"] or r["exit"] != 0 or not r["result_line"]) else ("SKIP" if r["SKIP"] else "ok")
        print(f"{flag:4} {r['name']:45} PASS {r['PASS']:4}  FAIL {r['FAIL']:3}  SKIP {r['SKIP']:3}  exit {r['exit']}  {r['secs']}s")
        for x in r["fails"] + r["skips"]:
            print("       " + x[:200])
        if r["tail"]:
            print("       " + r["tail"].replace("\n", "\n       ")[:800])
    tot = {k: sum(r[k] for r in rows) for k in ("PASS", "FAIL", "SKIP")}
    failed = [r["name"] for r in rows if r["FAIL"] or r["exit"] != 0 or not r["result_line"]]
    skipped = [r["name"] for r in rows if r["SKIP"]]
    verdict = "FAILED" if failed else ("INCOMPLETE" if skipped else "PASSED")
    print(f"\n합계: 스위트 {len(rows)}개 · PASS {tot['PASS']} · FAIL {tot['FAIL']} · SKIP {tot['SKIP']}")
    if failed:
        print("실패 스위트: " + ", ".join(failed))
    if skipped:
        print("SKIP이 있는 스위트(필수 검증 일부 미실행): " + ", ".join(skipped))
    print(f"판정: {verdict}")
    if verdict == "FAILED":
        return 1
    if verdict == "INCOMPLETE":
        return 0 if "--allow-skip" in args else 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
