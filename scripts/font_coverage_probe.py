# -*- coding: utf-8 -*-
"""探测 Windows 系统字体对颜文字字符的覆盖情况"""
import sys
from pathlib import Path
from fontTools.ttLib import TTFont

SAMPLE = "៸៸᳐⦁⩊⦁៸៸᳐ ੭ﾞ ᯠ_ ̫ _ᯄ /ᐠ .⸝⸝ ᵔ ᴗ ˬˬˊ˗ (๑˃ᴗ˂)ﻭ ♡ ⌯'ㅅ'⌯"
CODEPOINTS = sorted({ord(c) for c in SAMPLE})
print("涉及码点:")
for cp in CODEPOINTS:
    print(f"  U+{cp:05X} {chr(cp)!r}")

FONTS_DIR = Path("C:/Windows/Fonts")
candidates = [
    "msyh.ttc", "msyhbd.ttc", "simhei.ttf", "simsun.ttc", "Deng.ttf",
    "seguisym.ttf",   # Segoe UI Symbol
    "seguihis.ttf",   # Segoe UI Historic
    "segoeui.ttf",    # Segoe UI
    "ebrima.ttf",     # Ebrima (含加拿大原住民音节/提非纳等)
    "gadugi.ttf",     # Gadugi
    "Nirmala.ttf",    # Nirmala UI (印度系文字)
    "leelawui.ttf",   # Leelawadee UI
    "seguisb.ttf",    # Segoe UI Semibold
    "taile.ttf",      # MS Gothic?
    "meiryo.ttc",
    "msgothic.ttc",
    "YuGothM.ttc",
    "malgun.ttf",
    "arial.ttf",
    "tahoma.ttf",
    "cour.ttf",
    "segoeuib.ttf",
]

print("\n覆盖情况 (x=覆盖, .=缺失):")
header = "      " + "".join(chr(cp) for cp in CODEPOINTS)
print(header)
results = {}
for name in candidates:
    p = FONTS_DIR / name
    if not p.exists():
        continue
    covered = set()
    try:
        tt = TTFont(str(p), fontNumber=0, lazy=True)
        for table in tt["cmap"].tables:
            if table.isUnicode():
                covered.update(table.cmap.keys())
        tt.close()
    except Exception as e:
        print(f"{name}: 读取失败 {e}")
        continue
    row = "".join("x" if cp in covered else "." for cp in CODEPOINTS)
    results[name] = row
    print(f"{name:16s} {row}")

# 汇总：每个码点有哪些字体覆盖
print("\n逐字符可用字体:")
for cp in CODEPOINTS:
    covering = [n for n, row in results.items() if row[CODEPOINTS.index(cp)] == "x"]
    print(f"  U+{cp:05X} {chr(cp)!r}: {', '.join(covering) or '无'}")
