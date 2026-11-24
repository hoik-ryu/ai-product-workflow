"""변경 요청(CR)·Type B 패치 테스트 공용 픽스처(자체 완결형, import 전용).

실제 CLI로만 승인 상태를 만듭니다: v2 시작(게이트·탐색 기본 활성) → 탐색 건너뛰기(사용자 문장 시뮬레이션)
→ UX Planning·UX Spec 승인 → PNG 자산 등록·권리 확인 → Design Direction 승인(자산 스냅샷) → 프리뷰(자산 사본 사용)
→ preview-verify(pnpm 빌드) → 프리뷰 승인. pnpm 빌드가 안 되는 환경이면 preview_ok=False를 돌려줍니다.

모든 승인·확인 문장은 이 임시 프로젝트 안의 테스트 시뮬레이션입니다.
"""
from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
import sys
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent
sys.path.insert(0, str(HERE))
import product_design_test as T  # noqa: E402
import product_design_dd_test as DDT  # noqa: E402

PD = ENGINE / "skills/product-design/scripts/product_design.py"
PB = ENGINE / "skills/product-build/scripts/product_build.py"
THEME = "design-profile/theme.json"
BANNER = "design-preview/src/assets/banner.png"
NOTE = "사용자 승인(테스트 시뮬레이션)"


def run(script: Path, *args) -> tuple[int, dict]:
    p = subprocess.run([sys.executable, "-I", str(script), *map(str, args)], capture_output=True, text=True,
                       env={"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "")})
    try:
        return p.returncode, json.loads(p.stdout)
    except json.JSONDecodeError:
        return p.returncode, {"raw": (p.stdout + p.stderr)[-3000:]}


def pd(d: Path, *args) -> tuple[int, dict]:
    a = list(args)
    if a and a[0] == "approve" and "--note" not in a:
        a += ["--note", NOTE]
    return run(PD, *a, "--project", d)


def pb(d: Path, *args) -> tuple[int, dict]:
    return run(PB, *args, "--project", d)


def ok(d: Path, *args) -> dict:
    code, out = pd(d, *args)
    assert code == 0, (args, out)
    return out


def state(d: Path) -> dict:
    return json.loads((d / ".ai-workflow/design.json").read_text())


# ---------------------------------------------------------------- PNG(RGBA, 비압축 필터 0)
def png_rgba(w: int, h: int, pixel) -> bytes:
    """pixel(x, y) -> (r, g, b, a)."""
    raw = b"".join(b"\x00" + b"".join(bytes(pixel(x, y)) for x in range(w)) for y in range(h))

    def chunk(t, data):
        return struct.pack(">I", len(data)) + t + data + struct.pack(">I", zlib.crc32(t + data) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def banner_pixel(x: int, y: int, w: int = 48, h: int = 16):
    """원본 배너: 가운데 원(구도) + 바깥 배경. 가장자리 1px은 반투명(결함)."""
    cx, cy = w / 2, h / 2
    inside = (x - cx) ** 2 / (w / 3) ** 2 + (y - cy) ** 2 / (h / 3) ** 2 <= 1
    rgb = (14, 107, 79) if inside else (220, 240, 232)
    edge = x == 0 or y == 0 or x == w - 1 or y == h - 1
    return (*rgb, 128 if edge else 255)


def banner_fixed(x, y, w=48, h=16):
    """마스크 보정: 가장자리 1px 알파만 255로. 내부 픽셀·구도 동일."""
    r, g, b, _ = banner_pixel(x, y, w, h)
    return (r, g, b, 255)


def banner_recomposed(x, y, w=48, h=16):
    """같은 크기, 원 위치 이동(구도 변경)."""
    cx, cy = w / 4, h / 2
    inside = (x - cx) ** 2 / (w / 3) ** 2 + (y - cy) ** 2 / (h / 3) ** 2 <= 1
    return ((14, 107, 79) if inside else (220, 240, 232)) + (255,)


BANNER_V1 = lambda: png_rgba(48, 16, banner_pixel)  # noqa: E731
BANNER_MASK = lambda: png_rgba(48, 16, banner_fixed)  # noqa: E731
BANNER_RECOMPOSED = lambda: png_rgba(48, 16, banner_recomposed)  # noqa: E731
BANNER_WIDE = lambda: png_rgba(64, 16, lambda x, y: banner_pixel(x, y, 64, 16))  # noqa: E731


SCR1_TSX = """import banner from "../assets/banner.png"
import "./SCR-001.css"

export function Screen1({ state }: { state: string }) {
  return <section className="scr1"><img className="scr1-banner" src={banner} alt="" /><h1>로그인</h1><p>상태: {state}</p></section>
}
"""
SCR1_CSS = """.scr1 {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
}
.scr1-banner {
  width: 96px;
  height: 32px;
  image-rendering: pixelated;
}
"""
CDP = ENGINE / "skills/product-design/templates/measure-adapters/chrome-cdp/pd-measure-cdp.mjs"
MEASURE_CMD = "node --experimental-websocket tools/pd-measure/pd-measure-cdp.mjs"


def approved_project(root: Path, name: str = "club", with_preview: bool = True) -> tuple[Path, bool]:
    """v2 + 게이트 + 탐색(건너뜀) + DD(PNG 자산 AST-001 승인) + 프리뷰 승인(가능하면)."""
    d = T.make_product(root, name)
    (d / "design-profile").mkdir()
    (d / THEME).write_text('{"brand": {"primary": "#1D5BD0"}}\n')
    T.G(d, "add", "-A"); T.G(d, "commit", "-qm", "theme (user)")
    ok(d, "start", "--workflow", "v2", "--theme-file", THEME)
    T.write_00(d, 1)
    ok(d, "explore-skip", "--phase", "structure", "--note", "구조 탐색 없이 진행(테스트 시뮬레이션)")
    ok(d, "done", "--path", T.UXP); ok(d, "submit", "--stage", "ux_planning"); ok(d, "approve", "--stage", "ux_planning", "--revision", "1")
    ok(d, "begin", "--stage", "ux_spec")
    T.write_spec(d, 1)
    for f in T.SPEC:
        ok(d, "done", "--path", f)
    ok(d, "checkpoint"); ok(d, "submit", "--stage", "ux_spec"); ok(d, "approve", "--stage", "ux_spec", "--revision", "1")
    T.G(d, "add", "-A"); T.G(d, "commit", "-qm", "ux spec approved")
    ok(d, "begin", "--stage", "design_direction")
    ok(d, "explore-skip", "--phase", "visual", "--note", "시각 탐색 없이 진행(테스트 시뮬레이션)")
    up = root / f"{name}-upload"
    up.mkdir()
    (up / "banner.png").write_bytes(BANNER_V1())
    ok(d, "explore-asset", "add", "--file", up / "banner.png", "--kind", "image", "--role", "decorative", "--source", "self_made", "--license", "own",
       "--refs", "SCR-001")
    ok(d, "explore-asset", "confirm", "--id", "AST-001", "--license", "own", "--note", "직접 만든 배너(테스트 시뮬레이션)")
    DDT.write_07(d, 1, vd1_rel="SCR-001, CMP-001, UXD-001, AST-001")
    ok(d, "done", "--path", DDT.DD); ok(d, "submit", "--stage", "design_direction"); ok(d, "approve", "--stage", "design_direction", "--revision", "1")
    T.G(d, "add", "-A"); T.G(d, "commit", "-qm", "design direction approved")
    if not with_preview:
        return d, False
    ok(d, "begin", "--stage", "preview"); ok(d, "preview-scaffold")
    T.fill_preview(d, 1)
    man = d / "design-preview/preview.manifest.json"
    m = json.loads(man.read_text())
    m["design_direction_revision"] = 1
    for sid in m["screens"]:
        m["screens"][sid]["vd"] = ["VD-001"]
    man.write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n")
    (d / BANNER).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(d / "design-profile/assets/AST-001.png", d / BANNER)
    (d / "design-preview/src/screens/SCR-001.tsx").write_text(SCR1_TSX)
    (d / "design-preview/src/screens/SCR-001.css").write_text(SCR1_CSS)
    T.write_06(d, 1)
    ok(d, "done", "--path", "docs/design/06-preview-review.md")
    if shutil.which("pnpm") is None:
        return d, False
    code, out = pd(d, "preview-verify")
    if code != 0:
        print("NOTE preview-verify 실패(환경):", json.dumps(out, ensure_ascii=False)[:600])
        return d, False
    T.G(d, "add", "-A"); T.G(d, "commit", "-qm", "preview")
    ok(d, "submit", "--stage", "preview"); ok(d, "approve", "--stage", "preview", "--revision", "1")
    (d / "tools/pd-measure").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(CDP, d / "tools/pd-measure/pd-measure-cdp.mjs")
    ok(d, "explore-config", "--measure-cmd", MEASURE_CMD, "--confirm", "--note", "브라우저 측정 명령 확인(테스트 시뮬레이션)")
    T.G(d, "add", "-A"); T.G(d, "commit", "-qm", "preview approved + measure cmd")
    return d, True
