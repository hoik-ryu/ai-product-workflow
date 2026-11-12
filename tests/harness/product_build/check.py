"""상태 요약(판정용): 계획·배치·작업·잠금·보호 경로·커밋 수·단위 테스트. 모델 문장은 쓰지 않습니다."""
import hashlib, json, subprocess, sys
from pathlib import Path
d = Path(sys.argv[1]); prot = json.loads(Path(sys.argv[2]).read_text())
st = json.loads((d / ".ai-workflow/build.json").read_text())
print("PLAN", st["plan"]["status"], "r" + str(st["plan"]["revision"]))
for k, b in st["batches"].items():
    run = b.get("run") or {}
    tasks = {t: v["status"] for t, v in (run.get("tasks") or {}).items()}
    print("BATCH", k, b["status"], "tasks", json.dumps(tasks), "conf", [c["kind"] for c in run.get("confirmations", [])],
          "takeovers", len(run.get("takeovers", [])))
    if b.get("verification"):
        print("VERIFY", k, json.dumps({a: [e["status"], e["level"]] for a, e in b["verification"]["evaluation"].items()}))
ev = [h for h in st["history"] if h["event"] == "task_done"]
print("TASKDONE_EVENTS", json.dumps(sorted(h["note"].split(":")[0] for h in ev)))
lp = d / ".ai-workflow/build/ledger.json"
if lp.exists():
    led = json.loads(lp.read_text())
    print("LEDGER", json.dumps({i["id"]: [i["status"], [x.get("statement", "") for x in i["decisions"]]] for i in led["items"]}, ensure_ascii=False))
lock = d / ".ai-workflow/build/lock.json"
print("LOCK", json.loads(lock.read_text())["lock_id"] if lock.exists() else "none")
cur = {}
for rel in prot:
    p = d / rel
    cur[rel] = hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
print("PROTECTED", "UNCHANGED" if cur == prot else "CHANGED " + str([k for k in prot if cur[k] != prot[k]]))
print("COMMITS", len(subprocess.run(["git", "-C", str(d), "log", "--oneline"], capture_output=True, text=True).stdout.splitlines()))
print("STAGED", subprocess.run(["git", "-C", str(d), "diff", "--cached", "--name-only"], capture_output=True, text=True).stdout.split())
changed = subprocess.run(["git", "-C", str(d), "status", "--porcelain", "--untracked-files=all"], capture_output=True, text=True).stdout.split("\n")
print("WORKTREE", sorted(l[3:] for l in changed if l.strip() and not l[3:].startswith((".ai-workflow/build", "docs/build/"))))
r = subprocess.run([sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-t", ".", "-q"], cwd=d, capture_output=True, text=True,
                   env={"PATH": "/usr/bin:/bin", "PB_REPORT_DIR": "/tmp"} | {k: v for k, v in __import__("os").environ.items() if k in ("HOME", "PATH")})
print("UNITTEST", "PASS" if r.returncode == 0 else "FAIL", (r.stderr.strip().splitlines() or [""])[-1])
