#!/usr/bin/env python3
"""/product-init Skill 회귀 로그(all.log) 자동 판정(K1–K10). 상태 요약 줄과 파일 비교 줄만 근거로 씁니다.
블록 경계는 run_k.sh가 찍는 `### k<번호>[a-z]` 줄만 인정합니다(모델 응답 안의 `### ` 제목에 잘리지 않도록).
K8은 K7 결과와 무관하게 "재개 후 상태가 k7b 직후와 같은가"로 판정합니다(K7 실패가 K8로 번지지 않도록)."""
import re, sys
log = open(sys.argv[1], encoding="utf-8", errors="replace").read()
blocks = {m.group(1): m.group(2) for m in re.finditer(r"^### (k\d+[a-z]?)\n(.*?)(?=^### k\d+[a-z]?\n|^===== |\Z)", log, re.M | re.S)}
def status(k):
    m = re.search(r"^status (\w+) approved (\w+) files_done (\d+) merges (\[.*?\]) branch (\S+) verify (\{.*\})$", blocks.get(k, ""), re.M)
    return m.groups() if m else None
s3, s4, s5, s6, s7, s8, s9 = (status(k) for k in ("k3", "k4", "k5", "k6", "k7b", "k8", "k9"))
four_pass = lambda s: bool(s) and all(f"'{x}': 'pass'" in s[5] for x in ("fe", "be", "db", "smoke"))
checks = {
    "K1 미승인 기획 → 차단(상태 파일 없음)": "K1 boilerplate.json exists? NO" in log,
    "K2 출처 확인 단계(상태 파일 없음)": "no boilerplate.json" in blocks.get("k2", ""),
    "K3 계획만(승인 전, 파일 미적용)": bool(s3) and s3[0] == "planned" and s3[1] == "False" and s3[2] == "0",
    "K4 '좋아요'는 승인 아님": bool(s4) and s4[0] == "planned" and s4[1] == "False",
    "K5 적용 승인 + 브랜치 + 파일 적용": bool(s5) and s5[0] == "applied" and s5[1] == "True" and int(s5[2]) > 0 and s5[4].startswith("init/"),
    "K6 .gitignore만 병합": bool(s6) and s6[3] == "['.gitignore']",
    "K7 fe·be·db·smoke 검증 통과(Docker 필요)": bool(s7) and s7[0] == "verified" and four_pass(s7),
    "K8 새 세션 재개 보고(상태 유지: k7b 직후와 동일)": bool(s7) and bool(s8) and s8 == s7,
    "K9 사용자 수정 감지(엔진 check)·보존": re.search(r"^K9 engine check user_modified: .*frontend/src/main\.tsx", log, re.M) is not None
                                   and "K9 user edit preserved? YES" in log,
    "K10 /product-start 정상, README·기획 불변": "README unchanged? YES" in log,
}
for k, v in checks.items():
    print(("PASS " if v else "FAIL ") + k)
print(f"RESULT {sum(checks.values())}/{len(checks)} passed")
sys.exit(0 if all(checks.values()) else 1)
