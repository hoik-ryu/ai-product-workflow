"""/product-init 보조 스크립트 테스트 (자체 완결형).

실행: python3 tests/product_init_test.py
- 가짜 보일러플레이트 저장소와 제품 저장소를 임시 디렉터리에 만들어 테스트합니다. 엔진 저장소나 실제 프로젝트는 건드리지 않습니다.
- Docker가 꺼져 있으면 db 단계가 docker_unavailable 오류로 기록되는지 확인합니다.
"""
import hashlib, json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = str(ROOT / "skills/product-init/scripts/product_init.py")
BASE = Path(tempfile.mkdtemp(prefix="product-init-test-"))
FAKEBP = BASE / "fakebp"
WORK = BASE / "work"
results = []


def sh(*cmd, cwd=None, check=True):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and p.returncode != 0:
        raise RuntimeError(f"{cmd}: {p.stderr}")
    return p.stdout


def G(repo, *args):
    return sh("git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com", *args)


def pi(*args):
    p = subprocess.run([sys.executable, "-I", SCRIPT, *args], capture_output=True, text=True)
    try:
        out = json.loads(p.stdout)
    except json.JSONDecodeError:
        out = {"raw": p.stdout + p.stderr}
    return p.returncode, out


FAKE_MANIFEST = """schema_version = 1
name = "fakebp"
version = "1.0.0"
[apply]
exclude = []
[[substitutions]]
from = "fullstack-boilerplate"
to = "{project_slug}"
files = ["frontend/app.txt", ".env.example"]
[[merge]]
path = ".gitignore"
strategy = "append-missing-lines"
required = [".env", "node_modules/", ".venv/"]
[[merge]]
path = "README.md"
strategy = "append-section"
section_title = "개발 환경 (fakebp)"
[verify]
env_file = ".env.example"
ignored_paths = []
[verify.ports]
POSTGRES_PORT = 55432
[verify.stages]
fe = [ { run = "test -f app.txt", cwd = "frontend" }, { run = "echo failing-check && false", cwd = "frontend" } ]
be = [ { run = "sleep 1 && sh run.sh", cwd = "backend" } ]
db = [ { run = "{compose} up -d --wait db" } ]
"""


def build_fakebp():
    """보호 경로·비밀 파일·실패하는 검증 명령을 일부러 포함한 가짜 보일러플레이트(v1.0.0, v1.0.1=위험 manifest)."""
    d = FAKEBP
    files = {
        "frontend/app.txt": "fe app for fullstack-boilerplate\n", "backend/main.py": "be app\n",
        "backend/run.sh": "#!/bin/sh\necho hi\n", "README.md": "# fullstack-boilerplate\nboilerplate readme\n",
        ".gitignore": ".env\n.env.*\n!.env.example\nnode_modules/\n.venv/\n", ".env.example": "APP_NAME=fullstack-boilerplate\n",
        ".env.production": "SECRET=should-not-copy\n", "docs/planning/99-evil.md": "evil\n", ".ai-workflow/evil.json": "{}\n",
        ".claude/settings.json": "{}\n", "skills/product-start/SKILL.md": "x\n", "boilerplate.manifest.toml": FAKE_MANIFEST,
    }
    for p, c in files.items():
        (d / p).parent.mkdir(parents=True, exist_ok=True)
        (d / p).write_text(c)
    os.chmod(d / "backend/run.sh", 0o755)
    sh("git", "init", "-q", "-b", "main", cwd=d)
    G(d, "add", "-A"); G(d, "add", "-f", ".env.production"); G(d, "commit", "-qm", "fakebp 1.0.0"); G(d, "tag", "v1.0.0")
    G(d, "switch", "-q", "-c", "bad")
    bad = FAKE_MANIFEST.replace('version = "1.0.0"', 'version = "1.0.1"').replace(
        'db = [ { run = "{compose} up -d --wait db" } ]', 'db = [ { run = "{compose} down -v" }, { run = "docker volume rm x" } ]')
    (d / "boilerplate.manifest.toml").write_text(bad)
    G(d, "commit", "-qam", "bad manifest"); G(d, "tag", "v1.0.1"); G(d, "switch", "-q", "main")


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (f"  -- {detail}" if detail and not cond else ""))


PLANNING = {
    "01-discovery.md": "---\ndoc: discovery\nrevision: 2\n---\n# 제품 Discovery\n",
    "02-prd.md": "---\ndoc: prd\nrevision: 2\n---\n# PRD\n| FR-001 | 예약 | Must | GOAL-001 |\n",
    "03-user-stories.md": "---\ndoc: user-stories\nrevision: 2\n---\n### US-001: 예약\n",
    "04-user-flows.md": "---\ndoc: user-flows\nrevision: 2\n---\n## FLOW-001: 예약\n",
    "05-acceptance-criteria.md": "---\ndoc: acceptance-criteria\nrevision: 2\n---\n### AC-001: 예약\n",
}


def make_product(name, planning_status="approved", gitignore="node_modules/\n"):
    d = WORK / name
    if d.exists():
        shutil.rmtree(d)
    (d / "docs/planning").mkdir(parents=True)
    (d / ".ai-workflow").mkdir()
    sh("git", "init", "-q", cwd=d)
    (d / "README.md").write_text("# Badminton Playbook\n제품 README\n")
    (d / ".gitignore").write_text(gitignore)
    for f, c in PLANNING.items():
        (d / "docs/planning" / f).write_text(c)
    h = {f: sha(d / "docs/planning" / f) for f in PLANNING}
    plan_hashes = "\n".join(f'        docs/planning/{f}: "{h[f]}"' for f in list(PLANNING)[1:])
    (d / ".ai-workflow/state.yaml").write_text(f"""schema_version: 1
workflow: ai-product-workflow
current_stage: design
stages:
  discovery:
    status: approved
    revision: 2
    approved:
      revision: 2
      at: "2026-11-06T00:00:00Z"
      hashes:
        docs/planning/01-discovery.md: "{h['01-discovery.md']}"

  planning:
    status: {planning_status}
    revision: 2
    based_on_discovery_revision: 2
    artifacts_done: []
    approved:
      revision: 2
      at: "2026-11-06T00:00:00Z"
      hashes:
{plan_hashes}

  design:
    status: not_started

history: []
""")
    G(d, "add", "-A")
    G(d, "commit", "-qm", "approved planning")
    return d


def snapshot(source, ref, sha_, dest_name):
    dest = Path(tempfile.mkdtemp(prefix="pi-snap-")) / dest_name
    return pi("snapshot", "--source", str(source), "--ref", ref, "--sha", sha_, "--dest", str(dest)), dest


def planned(name, **kw):
    d = make_product(name, **kw)
    _, r = pi("resolve", "--source", str(FAKEBP), "--ref", "v1.0.0")
    (_, s), dest = snapshot(FAKEBP, "v1.0.0", r["commit"], "src")
    code, plan = pi("plan", "--project", str(d), "--snapshot", str(dest), "--source", str(FAKEBP), "--ref", "v1.0.0",
                    "--sha", r["commit"], "--slug", "badminton-playbook", "--title", "Badminton Playbook")
    return d, dest, r["commit"], code, plan


def state(d):
    return json.loads((d / ".ai-workflow/boilerplate.json").read_text())


def main():
    FAKEBP.mkdir(parents=True)
    WORK.mkdir(parents=True)
    build_fakebp()

    # ---- 차단 조건
    d = make_product("no_state")
    (d / ".ai-workflow/state.yaml").unlink(); G(d, "commit", "-qam", "rm state")
    code, out = pi("check", "--project", str(d))
    check("I01 /product-start 상태 없음 → 차단", code == 2 and out["gate"]["error"] == "no_workflow_state", out)

    d, dest, sha_, code, out = planned("unapproved", planning_status="awaiting_approval")
    check("I02 planning 미승인 → plan 차단", code == 2 and out.get("error") == "planning_not_approved", out.get("message"))
    check("I02b 차단 시 상태 파일 미생성", not (d / ".ai-workflow/boilerplate.json").exists())

    d = make_product("hash_mismatch")
    (d / "docs/planning/03-user-stories.md").write_text(PLANNING["03-user-stories.md"] + "수정\n"); G(d, "commit", "-qam", "edit 03")
    code, out = pi("check", "--project", str(d))
    check("I03 승인 해시 불일치 → 차단", code == 2 and "03-user-stories.md" in out["gate"]["message"], out["gate"].get("message"))

    d = make_product("dirty")
    (d / "notes.txt").write_text("wip")
    code, out = pi("check", "--project", str(d))
    check("I04 미커밋 변경 → 차단", code == 2 and out.get("error") == "dirty_worktree", out)

    d = make_product("engine")
    (d / "skills/product-start").mkdir(parents=True); (d / "skills/product-start/SKILL.md").write_text("x")
    code, out = pi("check", "--project", str(d))
    check("I05 엔진 저장소 → 차단", code == 2 and out.get("error") == "engine_repo", out)

    # ---- 계획(분류)
    d, dest, sha_, code, plan = planned("main")
    readme0, gi0 = sha(d / "README.md"), sha(d / ".gitignore")
    st0 = {p: sha(p) for p in [d / ".ai-workflow/state.yaml", *sorted((d / "docs/planning").iterdir())]}
    check("I06 plan 성공", code == 0, plan)
    prot = set(plan.get("protected", []))
    check("I06a 보호 경로 분류", prot == {"docs/planning/99-evil.md", ".ai-workflow/evil.json", ".claude/settings.json", "skills/product-start/SKILL.md"}, prot)
    exc = {e["path"]: e["reason"] for e in plan.get("excluded", [])}
    check("I06b 비밀 env·manifest 제외", exc.get(".env.production") == "secret_env" and exc.get("boilerplate.manifest.toml") == "manifest", exc)
    conf = {c["path"]: c for c in plan.get("conflicts", [])}
    check("I06c README·.gitignore 충돌 분류", set(conf) == {"README.md", ".gitignore"}, list(conf))
    check("I06d 필수 설정 누락 보고", set(conf.get(".gitignore", {}).get("missing_required", [])) == {".env", ".venv/"}, conf.get(".gitignore"))

    # ---- 승인 없는 적용 차단
    code, out = pi("apply", "--project", str(d), "--snapshot", str(dest))
    check("I07 승인 없는 apply → 차단", code == 2 and out.get("error") == "not_approved", out)
    code, out = pi("approve", "--project", str(d), "--plan-id", "deadbeef")
    check("I07b 다른 plan id 승인 → 거부", code == 2 and out.get("error") == "plan_id_mismatch", out)
    code, out = pi("merge", "--project", str(d), "--snapshot", str(dest), "--path", ".gitignore", "--confirm-plan-id", plan["plan_id"])
    check("I07c 적용 전 merge → 거부", code == 2 and out.get("error") == "not_applied", out)
    check("I07d 차단 후 파일 미생성", not (d / "frontend").exists())

    # ---- 승인 → 브랜치 → 중단 → 재개
    pi("approve", "--project", str(d), "--plan-id", plan["plan_id"])
    code, out = pi("branch", "--project", str(d), "--name", "init/fakebp-v1.0.0")
    check("I08 승인 후 브랜치 생성", code == 0 and sh("git", "-C", str(d), "branch", "--show-current").strip() == "init/fakebp-v1.0.0", out)
    code, out = pi("apply", "--project", str(d), "--snapshot", str(dest), "--stop-after", "1")
    check("I08a 중단 시뮬레이션(1개 기록 후)", code == 3 and state(d)["status"] == "applying" and len(state(d)["files_done"]) == 1, out)
    code, out = pi("apply", "--project", str(d), "--snapshot", str(dest))
    s = state(d)
    adds = [a["path"] for a in s["plan"]["add"]]
    check("I08b 재개 후 완료", code == 0 and s["status"] == "applied" and len(s["files_done"]) == len(adds), out)
    check("I08c 기록 SHA = 실제 파일", all(sha(d / f["path"]) == f["sha256"] for f in s["files_done"]))
    check("I08d 충돌 파일 보존(README, .gitignore)", sha(d / "README.md") == readme0 and sha(d / ".gitignore") == gi0)
    check("I08e 보호 경로·비밀 파일 미생성", not any((d / p).exists() for p in ["docs/planning/99-evil.md", ".ai-workflow/evil.json", ".claude/settings.json", "skills/product-start/SKILL.md", ".env.production"]))
    check("I08f /product-start 상태·기획 문서 불변", all(sha(p) == h for p, h in st0.items()))
    check("I08g 이름 치환", "badminton-playbook" in (d / "frontend/app.txt").read_text() and "fullstack-boilerplate" not in (d / ".env.example").read_text())
    check("I08h 실행 권한 보존", os.access(d / "backend/run.sh", os.X_OK))
    code, out = pi("check", "--project", str(d))
    check("I08i 적용 후 교차 검증 일치", code == 0 and out["cross_verify"]["consistent"], out.get("cross_verify"))

    # ---- 병합
    code, out = pi("merge", "--project", str(d), "--snapshot", str(dest), "--path", ".gitignore", "--confirm-plan-id", "wrong")
    check("I11 승인 증거 없는 merge → 거부", code == 2 and out.get("error") == "not_confirmed", out)
    code, out = pi("merge", "--project", str(d), "--snapshot", str(dest), "--path", ".gitignore", "--confirm-plan-id", plan["plan_id"])
    gi = (d / ".gitignore").read_text()
    check("I11a .gitignore 누락 줄만 추가", code == 0 and ".env\n" in gi and ".venv/" in gi and gi.count("node_modules/") == 1 and gi.startswith("node_modules/\n"), gi)
    check("I11b Git 추적·clean 파일은 백업 없음", out.get("backup") is None, out)
    code, out = pi("merge", "--project", str(d), "--snapshot", str(dest), "--path", "README.md", "--confirm-plan-id", plan["plan_id"])
    rd = (d / "README.md").read_text()
    check("I11c README append-section(기존 내용 유지)", code == 0 and rd.startswith("# Badminton Playbook\n제품 README\n") and "## 개발 환경 (fakebp)" in rd, rd[:200])
    code, out = pi("merge", "--project", str(d), "--snapshot", str(dest), "--path", "README.md", "--confirm-plan-id", plan["plan_id"])
    check("I11d 중복 병합 거부", code == 2 and out.get("error") == "already_merged", out)
    code, out = pi("check", "--project", str(d))
    check("I11e 병합 후 교차 검증 일치", code == 0, out.get("cross_verify"))

    # ---- 검증 기록 / Docker 안전
    code, out = pi("verify", "--project", str(d), "--stage", "fe")
    s = state(d)
    check("I12 검증 실패 기록(fe)", code == 2 and s["status"] == "verify_failed" and s["verification"]["fe"]["result"] == "fail"
          and "false" in s["verification"]["fe"]["failed_step"] and s["verification"]["fe"]["tail"], s["verification"].get("fe"))
    code, out = pi("verify", "--project", str(d), "--stage", "be")
    check("I12a 검증 통과 기록(be)", code == 0 and state(d)["verification"]["be"]["result"] == "pass", out)
    # ---- 동시 실행: 상태 잠금(다른 단계 검증이 앞선 기록을 덮어쓰지 않음)
    holder = subprocess.Popen([sys.executable, "-I", "-c",
                               "import fcntl,os,sys,time;fd=os.open(sys.argv[1],os.O_RDONLY);fcntl.flock(fd,fcntl.LOCK_EX);print('locked',flush=True);time.sleep(30)",
                               str(d / ".ai-workflow")], stdout=subprocess.PIPE, text=True)
    holder.stdout.readline()
    before = (d / ".ai-workflow/boilerplate.json").read_bytes()
    code, out = pi("verify", "--project", str(d), "--stage", "be")
    check("I12g 다른 명령 실행 중이면 state_busy로 거부, 상태 불변", code == 2 and out.get("error") == "state_busy"
          and (d / ".ai-workflow/boilerplate.json").read_bytes() == before, out)
    code, out = pi("verify", "--project", str(d), "--stage", "be", "--dry-run")
    code2, out2 = pi("status", "--project", str(d))
    check("I12h 잠금 중에도 dry-run·status(읽기)는 가능", code == 0 and out.get("dry_run") and "verification" in out2, out)
    holder.kill(); holder.wait()
    at_before = {k: v["at"] for k, v in state(d)["verification"].items() if isinstance(v, dict)}
    procs = {stg: subprocess.Popen([sys.executable, "-I", SCRIPT, "verify", "--project", str(d), "--stage", stg],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for stg in ("fe", "be")}
    outs = {stg: json.loads(pr.communicate()[0]) for stg, pr in procs.items()}
    ver = state(d)["verification"]
    ran = [stg for stg, o in outs.items() if o.get("error") != "state_busy"]
    lost = [stg for stg in ran if ver[stg]["at"] == at_before.get(stg) and ver[stg]["at"] != outs[stg]["verification"]["at"]]
    check("I12i fe·be 동시 실행 시 실행된 단계 기록이 모두 남음(덮어쓰기 없음)", ran and not lost
          and all(ver[stg]["at"] == outs[stg]["verification"]["at"] for stg in ran), {"ran": ran, "outs": {k: o.get("error") or o["verification"]["result"] for k, o in outs.items()}})
    code, out = pi("verify", "--project", str(d), "--stage", "db", "--dry-run")
    steps = " ".join(x["run"] for x in out.get("steps", []))
    check("I12b Docker 명령 프로젝트명 격리", "docker compose -p badminton-playbook-init-verify --env-file .env.example up -d --wait db" in steps, steps)
    check("I12c 기본 정리에 -v 없음", out.get("cleanup") == "docker compose -p badminton-playbook-init-verify --env-file .env.example down --remove-orphans", out.get("cleanup"))
    # 볼륨 삭제 허용 여부는 Docker 단계 실행 기록에 달려 있으므로 db 실행 전에 확인합니다.
    code, out = pi("cleanup", "--project", str(d), "--dry-run")
    check("I12e 검증 기록 없는 프로젝트 볼륨 삭제 불허", out.get("volume_removal_allowed") is False and not re.search(r"\s(-v|--volumes)(\s|$)", out.get("down", "")), out)
    code, out = pi("verify", "--project", str(d), "--stage", "db")
    s = state(d)
    docker_ok = subprocess.run(["docker", "info"], capture_output=True).returncode == 0
    if not docker_ok:
        check("I12d Docker 미가동 시 error 기록", code == 2 and s["verification"]["db"]["result"] == "error" and s["verification"]["db"]["reason"] == "docker_unavailable", s["verification"].get("db"))
    else:
        # 가짜 보일러플레이트에는 compose 파일이 없어 db 단계는 실패해야 하고, 실패가 기록되어야 합니다.
        check("I12d Docker 가동 시 db 실패 기록", code == 2 and s["verification"]["db"]["result"] == "fail" and s["status"] == "verify_failed", s["verification"].get("db"))
        code, out = pi("cleanup", "--project", str(d), "--dry-run")
        check("I12f 검증 프로젝트 기록 후에만 볼륨 삭제 허용 표시", out.get("volume_removal_allowed") is True and not re.search(r"\s(-v|--volumes)(\s|$)", out.get("down", "")), out)

    # ---- 재개 시 사용자 변경 감지
    d2, dest2, sha2, code, plan2 = planned("modified")
    pi("approve", "--project", str(d2), "--plan-id", plan2["plan_id"])
    pi("apply", "--project", str(d2), "--snapshot", str(dest2), "--stop-after", "2")
    done = state(d2)["files_done"]
    victim = d2 / done[0]["path"]
    victim.write_text("사용자가 수정한 내용\n")
    code, out = pi("apply", "--project", str(d2), "--snapshot", str(dest2))
    check("I09 적용 파일 변경 → state_mismatch(user_modified)", code == 2 and out.get("error") == "state_mismatch" and done[0]["path"] in out.get("user_modified", []), out)
    check("I09a 사용자 변경 내용 보존", victim.read_text() == "사용자가 수정한 내용\n")
    victim.unlink()
    code, out = pi("apply", "--project", str(d2), "--snapshot", str(dest2))
    check("I09b 기록 파일 삭제 → state_mismatch(missing)", code == 2 and done[0]["path"] in out.get("missing", []), out)
    d3, dest3, sha3, code, plan3 = planned("unexpected")
    pi("approve", "--project", str(d3), "--plan-id", plan3["plan_id"])
    pi("apply", "--project", str(d3), "--snapshot", str(dest3), "--stop-after", "1")
    (d3 / "src_extra.txt").write_text("other work")
    code, out = pi("apply", "--project", str(d3), "--snapshot", str(dest3))
    check("I09c 계획 밖 변경 → state_mismatch(unexpected)", code == 2 and "src_extra.txt" in out.get("unexpected_changes", []), out)
    (d3 / "src_extra.txt").unlink()
    remaining = [a for a in state(d3)["plan"]["add"] if a["path"] not in {f["path"] for f in state(d3)["files_done"]}]
    same, diff = remaining[0], remaining[1]
    (d3 / same["path"]).parent.mkdir(parents=True, exist_ok=True)
    data = (dest3 / same["path"]).read_bytes().replace(b"fullstack-boilerplate", b"badminton-playbook")
    (d3 / same["path"]).write_bytes(data)
    (d3 / diff["path"]).parent.mkdir(parents=True, exist_ok=True)
    (d3 / diff["path"]).write_text("다른 내용")
    code, out = pi("apply", "--project", str(d3), "--snapshot", str(dest3))
    st3 = state(d3)
    check("I09d 계획 후 생긴 동일 파일 → 채택", any(f["path"] == same["path"] and f.get("note") == "adopted_identical" for f in st3["files_done"]), st3["files_done"])
    check("I09e 계획 후 생긴 다른 파일 → runtime 충돌(보존)", any(c["path"] == diff["path"] for c in st3["runtime_conflicts"]) and (d3 / diff["path"]).read_text() == "다른 내용", out)

    # ---- 태그 SHA 불일치
    moved = WORK / "fakebp_moved"
    sh("git", "clone", "-q", str(FAKEBP), str(moved))
    d4, dest4, sha4, code, plan4 = planned("tagmove")
    st4 = state(d4); st4["source"]["repo"] = str(moved); (d4 / ".ai-workflow/boilerplate.json").write_text(json.dumps(st4))
    (moved / "frontend/app.txt").write_text("tampered\n"); G(moved, "commit", "-qam", "tamper"); G(moved, "tag", "-f", "v1.0.0")
    (_, out), _dest = snapshot(moved, "v1.0.0", sha4, "src2")
    check("I10 태그가 옮겨진 스냅샷 → sha_mismatch", out.get("error") == "sha_mismatch" and out.get("expected") == sha4, out)
    code, out = pi("status", "--project", str(d4), "--check-remote")
    check("I10a status --check-remote → tag_moved", code == 2 and out.get("tag_moved") is True, out)

    # ---- manifest 검증
    d5 = make_product("badmanifest")
    _, r = pi("resolve", "--source", str(FAKEBP), "--ref", "v1.0.1")
    (_, s5), dest5 = snapshot(FAKEBP, "v1.0.1", r["commit"], "src")
    code, out = pi("plan", "--project", str(d5), "--snapshot", str(dest5), "--source", str(FAKEBP), "--ref", "v1.0.1", "--sha", r["commit"])
    errs = " ".join(out.get("errors", []))
    check("I13 위험 명령 포함 manifest 거부", code == 2 and out.get("error") == "manifest_invalid" and "down -v" in errs and "volume rm" in errs, out)
    code, out = pi("resolve", "--source", str(FAKEBP), "--ref", "main")
    check("I13a 브랜치명 ref 거부", code == 2 and out.get("error") == "tag_not_found", out)
    d6 = make_product("vermismatch")
    _, r = pi("resolve", "--source", str(FAKEBP), "--ref", "v1.0.0")
    (_, s6), dest6 = snapshot(FAKEBP, "v1.0.0", r["commit"], "src")
    code, out = pi("plan", "--project", str(d6), "--snapshot", str(dest6), "--source", str(FAKEBP), "--ref", "v2.0.0", "--sha", r["commit"])
    check("I13b 태그·manifest version 불일치 거부", code == 2 and out.get("error") == "version_mismatch", out)

    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\nRESULT {passed}/{len(results)} passed  (임시 디렉터리: {BASE})")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
