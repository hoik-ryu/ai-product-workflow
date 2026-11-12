#!/usr/bin/env python3
"""엔진 범용성 검사(자체 완결형): 공통 Skill(skills/)에 특정 사례 프로젝트의 도메인 용어·정책 키가 들어가지 않았는지 확인합니다.

엔진은 정책의 상태·차단 여부·영향 범위·승인 이력만 관리하고, 정책의 의미와 결정은 각 프로젝트가 소유합니다.
통합 검증용 사례 프로젝트(SMAPSH 등)의 용어는 tests/ 아래 사례 전용 검사와 픽스처에만 둡니다.
실행: python3 tests/engine_generality_test.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / "skills"
TEXT_SUFFIXES = {".py", ".md", ".toml", ".json", ".tsx", ".ts", ".css", ".html", ".yaml", ".yml", ".txt", ".sh"}

# 사례 프로젝트(배드민턴 클럽 운영) 고유 용어. 일반 예시는 예약·주문 등 중립 도메인을 씁니다.
FORBIDDEN = [
    r"smapsh", r"badminton", r"배드민턴", r"clubmatch", r"\broster\b", r"\blineup\b",
    r"코트", r"대진", r"청백", r"셔틀", r"복식", r"경기 수", r"게스트", r"운영진",
    r"\bB3-P\d", r"\bB4-Q\d", r"\bI3-U\d",
]


def main() -> int:
    hits = []
    for p in sorted(SKILLS.rglob("*")):
        if not p.is_file() or p.suffix not in TEXT_SUFFIXES or "node_modules" in p.parts:
            continue
        for n, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for pat in FORBIDDEN:
                if re.search(pat, line, re.I):
                    hits.append(f"{p.relative_to(ROOT)}:{n}: {pat} → {line.strip()[:120]}")
    ok = not hits
    print(("PASS " if ok else "FAIL ") + "G1 공통 Skill에 사례 프로젝트 도메인 용어·정책 키 없음")
    for h in hits:
        print("  " + h)
    print(f"\nRESULT {1 if ok else 0}/1 passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
