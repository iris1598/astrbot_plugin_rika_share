"""字体探测与符号回退链。

中文主字体决定卡片文字的可用性；主字体缺字形时（颜文字、生僻符号等）
按预设链回退到系统符号字体，必要时再通过 fontconfig 动态查找。
"""

from __future__ import annotations

import sys
from pathlib import Path

from astrbot.api import logger

try:
    from fontTools.ttLib import TTFont
except ImportError:  # pragma: no cover - 缺失时退化为单字体渲染
    TTFont = None


_FONT_CANDIDATES: dict[str, tuple[tuple[str, str], ...]] = {
    "win32": (
        ("msyh.ttc", "msyhbd.ttc"),        # 微软雅黑
        ("simhei.ttf", "msyhbd.ttc"),      # 黑体
        ("Deng.ttf", "Dengb.ttf"),         # 等线
        ("simsun.ttc", "simsun.ttc"),      # 宋体
        ("NotoSansSC-VF.ttf", "NotoSansSC-VF.ttf"),
    ),
    "darwin": (
        ("PingFang.ttc", "PingFang.ttc"),  # 苹方
        ("Hiragino Sans GB.ttc", "Hiragino Sans GB.ttc"),
        ("STHeiti Medium.ttc", "STHeiti Medium.ttc"),
    ),
    "linux": (
        ("NotoSansCJK-Regular.ttc", "NotoSansCJK-Bold.ttc"),
        ("SourceHanSansSC-Regular.otf", "SourceHanSansSC-Bold.otf"),
        ("wqy-zenhei.ttc", "wqy-zenhei.ttc"),
        ("wqy-microhei.ttc", "wqy-microhei.ttc"),
        ("DroidSansFallbackFull.ttf", "DroidSansFallbackFull.ttf"),
        ("arpluminghk-regular.ttf", "arpluminghk-regular.ttf"),
    ),
}

FONT_DIRS = [
    "C:/Windows/Fonts",
    "/System/Library/Fonts",
    "/System/Library/Fonts/Supplemental",
    "/usr/share/fonts/opentype/noto",
    "/usr/share/fonts/opentype/noto-cjk",
    "/usr/share/fonts/truetype/noto",
    "/usr/share/fonts/truetype/noto-cjk",
    "/usr/share/fonts/noto-cjk",
    "/usr/share/fonts/truetype/wqy",
    "/usr/share/fonts/truetype/droid",
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts/truetype/arphic",
    "/usr/share/fonts/opentype/source-han-sans",
    "/usr/local/share/fonts",
]

# 符号/生僻文字回退字体链（按优先级排列）。
# 颜文字常用字符分布在数学算符、修饰字母、上标、东南亚文字、
# 加拿大原住民音节等生僻 Unicode 区，中文字体普遍缺字形，
# 需要回退到这些覆盖面更广的字体才能正常渲染。
SYMBOL_FONT_CANDIDATES: dict[str, tuple[str, ...]] = {
    "win32": (
        "segoeui.ttf",              # Segoe UI：上标/修饰字母/附标/古尔穆奇 ੭ 等
        "seguisym.ttf",             # Segoe UI Symbol：⌯ ♡ ⦁ ⩊ ⸝ 等杂项符号
        "leelawui.ttf",             # Leelawadee UI：高棉文 ៸ 等
        "gadugi.ttf",               # Gadugi：加拿大原住民音节 ᐠ
        "malgun.ttf",               # Malgun Gothic：谚文兼容字母 ㅅ
        "SansSerifCollection.ttf",  # 巽他文 ᯄ ᯠ / 吠陀记号 ᳐
        "Nirmala.ttc",              # Nirmala UI：吠陀记号 ᳐
        "ebrima.ttf",               # Ebrima：提非纳/瓦伊等
        "DroidSansFallbackFull.ttf",
    ),
    "darwin": (
        "Apple Symbols.ttf",
        "Arial Unicode.ttf",
        "Geneva.ttf",
        "Helvetica.ttc",
    ),
    "linux": (
        "NotoSansSymbols2-Regular.ttf",             # ⌯ ⸝ 等符号扩展
        "NotoSansMath-Regular.ttf",                 # ⦁ ⩊ 数学算符
        "NotoSansSymbols-Regular.ttf",              # ♡ 等杂项符号
        "NotoSans-Regular.ttf",                     # ˗ ˬ ˊ ᴗ ᵔ ̫ 修饰字母/上标
        "NotoSansGurmukhi-Regular.ttf",             # ੭ 古木基文
        "NotoSansKhmer-Regular.ttf",                # 比较高棉文
        "NotoSansSundanese-Regular.ttf",            # ᯄ ᯠ 巽他文
        "NotoSansCanadianAboriginal-Regular.ttf",   # ᐠ 加拿大原住民音节
        "NotoSansDevanagari-Regular.ttf",           # ᳐ 吠陀记号
        "NotoSansCham-Regular.ttf",                 # 占文等东南亚文字
        "DejaVuSans.ttf",
        "DroidSansFallbackFull.ttf",
        "wqy-zenhei.ttc",
        "Symbola.ttf",
    ),
}

# 字体文件 -> Unicode 码点集合 缓存（进程级共享）
_CMAP_CACHE: dict[str, frozenset[int]] = {}


def font_cmap(path: str) -> frozenset[int]:
    """读取字体 cmap 返回其覆盖的码点集合；读取失败返回空集合。"""
    cached = _CMAP_CACHE.get(path)
    if cached is not None:
        return cached
    codepoints: set[int] = set()
    if TTFont is not None:
        try:
            font = TTFont(path, fontNumber=0, lazy=True)
            try:
                for table in font["cmap"].tables:
                    if table.isUnicode():
                        codepoints.update(table.cmap.keys())
            finally:
                font.close()
        except Exception:
            pass
    result = frozenset(codepoints)
    _CMAP_CACHE[path] = result
    return result


# 渲染字体均无法覆盖的码点（只记录一次日志）
UNCOVERED_WARNED: set[int] = set()

# fontconfig 查询结果缓存：码点 -> 字体文件路径（可能为 None）
_FC_CACHE: dict[int, str | None] = {}


def fontconfig_lookup(cp: int) -> str | None:
    """通过 fontconfig 查找覆盖指定码点的系统字体（Linux/macOS 兜底）。

    fc-list 支持 :charset=XXX 匹配，能直接给出覆盖该码点的字体文件，
    用于应对预设回退链之外的字形。每个码点只查询一次，结果缓存。
    """
    if cp in _FC_CACHE:
        return _FC_CACHE[cp]
    path: str | None = None
    if sys.platform != "win32":
        try:
            import shutil
            import subprocess

            if shutil.which("fc-list"):
                out = subprocess.run(
                    ["fc-list", f":charset={cp:X}", "file"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                ).stdout
                for line in out.splitlines():
                    # 形如 /usr/share/fonts/.../NotoSansSundanese-Regular.ttf:
                    cand = line.strip().rstrip(":").strip()
                    if cand and Path(cand).is_file():
                        path = cand
                        break
        except Exception:
            path = None
    _FC_CACHE[cp] = path
    if path:
        logger.debug(f"fontconfig 为 U+{cp:04X} 找到回退字体: {path}")
    return path


def discover_fonts(custom_path: str | None = None) -> tuple[str | None, str | None]:
    """查找可用的中文字体，返回 (常规字体, 粗体字体) 路径。"""
    if custom_path:
        p = Path(custom_path).expanduser()
        if p.is_dir():
            for ext in ("*.ttf", "*.ttc", "*.otf"):
                found = sorted(p.glob(ext))
                if found:
                    return str(found[0]), str(found[-1] if len(found) > 1 else found[0])
        elif p.is_file():
            return str(p), str(p)
        logger.warning(f"渲染字体路径无效，将自动探测系统字体: {custom_path}")

    platform = sys.platform
    candidates = _FONT_CANDIDATES.get(platform, _FONT_CANDIDATES["linux"])
    dirs = [Path(d) for d in FONT_DIRS]

    for regular_name, bold_name in candidates:
        for d in dirs:
            reg = d / regular_name
            bol = d / bold_name
            if reg.exists():
                if bol.exists():
                    return str(reg), str(bol)
                return str(reg), None

    # 兜底：任意目录下存在的中文字体
    for d in dirs:
        if not d.is_dir():
            continue
        for p in sorted(d.iterdir()):
            if p.suffix.lower() in {".ttf", ".ttc", ".otf"}:
                return str(p), None
    return None, None
