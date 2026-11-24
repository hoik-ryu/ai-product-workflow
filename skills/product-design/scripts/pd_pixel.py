"""/product-design 변경 요청(CR) Type B: 이미지 자산 전후 픽셀 비교(표준 라이브러리, 읽기 전용).

지원: PNG 8비트, 색 형식 0(회색)·2(RGB)·4(회색+알파)·6(RGBA), 인터레이스 없음. 그 밖(팔레트·16비트·인터레이스·JPEG·WebP·SVG)은
`analyzable: false`로 돌려줍니다. 판정할 수 없으면 Type B로 확정하지 않습니다(상위 유형, reference/change-request.md §4).

판정(`verdict`)
- `identical`: 픽셀이 모두 같음
- `edge_only`: 바뀐 픽셀이 모두 가장자리 띠(edge band) 안에 있음 — 마스크·테두리 보정 후보
- `interior`: 가장자리 띠 밖(내부) 픽셀이 바뀜 — 구도·내용 변경 가능성(Type B 불가)
- `dimensions_changed`: 가로·세로가 다름(비율·구도 변경, Type B 불가)
"""
from __future__ import annotations

import struct
import zlib

PNG_SIG = b"\x89PNG\r\n\x1a\n"
CHANNELS = {0: 1, 2: 3, 4: 2, 6: 4}


class Unsupported(Exception):
    pass


def decode_png(raw: bytes) -> tuple[int, int, list[tuple[int, int, int, int]]]:
    """(가로, 세로, RGBA 픽셀 목록). 지원하지 않는 형식이면 Unsupported."""
    if not raw.startswith(PNG_SIG):
        raise Unsupported("PNG가 아닙니다")
    pos, ihdr, idat = 8, None, []
    while pos + 8 <= len(raw):
        ln, typ = struct.unpack(">I4s", raw[pos:pos + 8])
        data = raw[pos + 8:pos + 8 + ln]
        if len(data) != ln:
            raise Unsupported("잘린 PNG")
        if typ == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", data)
        elif typ == b"IDAT":
            idat.append(data)
        elif typ == b"IEND":
            break
        pos += 12 + ln
    if not ihdr:
        raise Unsupported("IHDR 없음")
    w, h, depth, ctype, _comp, _filt, interlace = ihdr
    if depth != 8 or ctype not in CHANNELS or interlace != 0:
        raise Unsupported(f"지원하지 않는 PNG 형식(비트 {depth}, 색 형식 {ctype}, 인터레이스 {interlace})")
    if w * h > 4_000_000:
        raise Unsupported("픽셀 수가 너무 많습니다(400만 초과)")
    try:
        data = zlib.decompress(b"".join(idat))
    except zlib.error as e:
        raise Unsupported(f"압축 해제 실패: {e}") from e
    ch = CHANNELS[ctype]
    stride = w * ch
    if len(data) < h * (stride + 1):
        raise Unsupported("픽셀 데이터가 부족합니다")
    prev = bytearray(stride)
    px: list[tuple[int, int, int, int]] = []
    for y in range(h):
        f = data[y * (stride + 1)]
        line = bytearray(data[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for i in range(stride):
            a = line[i - ch] if i >= ch else 0
            b = prev[i]
            c = prev[i - ch] if i >= ch else 0
            if f == 1:
                line[i] = (line[i] + a) & 255
            elif f == 2:
                line[i] = (line[i] + b) & 255
            elif f == 3:
                line[i] = (line[i] + ((a + b) >> 1)) & 255
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
            elif f != 0:
                raise Unsupported(f"알 수 없는 필터 {f}")
        for x in range(w):
            v = line[x * ch:(x + 1) * ch]
            if ctype == 0:
                px.append((v[0], v[0], v[0], 255))
            elif ctype == 2:
                px.append((v[0], v[1], v[2], 255))
            elif ctype == 4:
                px.append((v[0], v[0], v[0], v[1]))
            else:
                px.append((v[0], v[1], v[2], v[3]))
        prev = line
    return w, h, px


def edge_band(w: int, h: int) -> int:
    """가장자리 띠 두께(px): 짧은 변의 1%와 2px 중 큰 값. 엔진 고정값입니다(프로젝트 정책 아님)."""
    return max(2, round(min(w, h) * 0.01))


def compare(old: bytes, new: bytes) -> dict:
    """전후 이미지 비교 결과. 판정할 수 없으면 analyzable False와 이유."""
    try:
        w0, h0, p0 = decode_png(old)
        w1, h1, p1 = decode_png(new)
    except Unsupported as e:
        return {"analyzable": False, "reason": str(e), "verdict": None}
    out = {"analyzable": True, "before": {"width": w0, "height": h0}, "after": {"width": w1, "height": h1}}
    if (w0, h0) != (w1, h1):
        return out | {"verdict": "dimensions_changed", "aspect_same": w0 * h1 == w1 * h0}
    band = edge_band(w0, h0)
    changed = interior = 0
    bbox = None
    rgb_max = alpha_max = 0
    rgb_changed = alpha_changed = 0
    for i, (a, b) in enumerate(zip(p0, p1)):
        if a == b:
            continue
        x, y = i % w0, i // w0
        changed += 1
        dr = max(abs(a[k] - b[k]) for k in range(3))
        da = abs(a[3] - b[3])
        rgb_max, alpha_max = max(rgb_max, dr), max(alpha_max, da)
        rgb_changed += dr > 0
        alpha_changed += da > 0
        if band <= x < w0 - band and band <= y < h0 - band:
            interior += 1
        bbox = (min(bbox[0], x), min(bbox[1], y), max(bbox[2], x), max(bbox[3], y)) if bbox else (x, y, x, y)
    total = w0 * h0
    verdict = "identical" if changed == 0 else ("interior" if interior else "edge_only")
    return out | {"verdict": verdict, "edge_band_px": band, "pixels_total": total, "pixels_changed": changed,
                  "changed_ratio": round(changed / total, 6), "interior_changed": interior,
                  "bbox": list(bbox) if bbox else None, "rgb_changed": rgb_changed, "alpha_changed": alpha_changed,
                  "rgb_max_delta": rgb_max, "alpha_max_delta": alpha_max, "aspect_same": True}
