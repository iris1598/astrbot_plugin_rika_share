"""QQ 官方机器人的分享卡片（纯文本形态）识别与字段提取。

官方机器人拿不到分享卡片的 JSON 结构：QQ 开放平台把卡片转成**纯文本**下发，
适配器原样放进 ``message_str``，已知的两种形态::

    [卡片消息] 小程序
    摘要: [QQ小程序][魔裁/绘画] "来吧,成为我的共犯吧" 【bilibilionly同人扶持计划】
    source: 哔哩哔哩
    source_logo: https://open.gtimg.cn/open/app_icon/...
    title: [魔裁/绘画] "来吧,成为我的共犯吧" 【bilibilionly同人扶持计划】
    preview: https://qq.ugcimg.cn/v1/...

    [卡片消息] 图文H5
    摘要: 【分享】当不同动漫角色得到波塔拉耳环进行融合时
    title: 当不同动漫角色得到波塔拉耳环进行融合时
    desc: 当不同动漫角色得到波塔拉耳环进行融合时
    jump_url: https://b23.tv/hcXlPa4
    tag: 哔哩哔哩

「小程序」卡片只有第三方图床（``open.gtimg.cn`` / ``qq.ugcimg.cn``）的 URL，
没有内容链接，只能取 ``title`` 作为关键词去对应平台搜索；「图文H5」卡片带
``jump_url``（真实内容链接），**优先走链接解析**，与平台 Handler 的行为一致
（见 ``main.miniapp_card_handler`` 的协调守卫与 B站的
``adapters/bilibili.py::BilibiliParser.search_video_by_title``）。

本模块只做文本识别与字段提取，不依赖 AstrBot，可独立测试。
"""

import re

__all__ = [
    "extract_card_link",
    "extract_card_title",
    "is_miniapp_card",
    "parse_miniapp_card",
]

#: 卡片首行，如「[卡片消息] 小程序」「[卡片消息] 图文H5」。也与
#: ``main.miniapp_card_handler`` 的 ``@filter.regex`` 触发正则共用
#: （``^`` 锚定开头，``RegexFilter`` 用 ``search`` 匹配）。
CARD_HEADER_PATTERN: re.Pattern[str] = re.compile(r"^\[卡片消息\]\s*(\S*)")

#: 感兴趣的字段行，如「title: …」。``:`` 只在键名后取一次，URL 里的 ``://`` 不受影响。
_FIELD_PATTERN: re.Pattern[str] = re.compile(
    r"^(摘要|source|source_logo|title|preview|desc|jump_url|tag)\s*[:：]\s*(.*)$"
)

#: 摘要行里的「[QQ小程序]」前缀（回退关键词时要剥掉）
_QQ_MINIAPP_PREFIX: re.Pattern[str] = re.compile(r"^\s*\[QQ小程序\]\s*")

#: 链接尾部可能粘连的标点（与 main.cloudflare_fallback_handler 的清理口径一致）
_LINK_TRAILING_PUNCT = ".,!?;:)'\"】」》）"


def is_miniapp_card(text: str | None) -> bool:
    """文本是否是分享卡片的纯文本形态（以「[卡片消息]」开头）。"""
    return bool(text) and text.lstrip().startswith("[卡片消息]")


def parse_miniapp_card(text: str | None) -> dict[str, str] | None:
    """解析分享卡片文本，返回字段字典；不是卡片文本时返回 ``None``。

    返回值固定带 ``kind``（首行「[卡片消息]」后的类型，如「小程序」「图文H5」），
    其余为卡片字段行（``摘要`` / ``source`` / ``source_logo`` / ``title`` /
    ``preview`` / ``desc`` / ``jump_url`` / ``tag``，卡片上有才存在）。
    """
    stripped = (text or "").strip()
    if not stripped.startswith("[卡片消息]"):
        return None
    lines = stripped.splitlines()
    header = CARD_HEADER_PATTERN.match(lines[0].strip())
    fields = {"kind": header.group(1) if header else ""}
    for line in lines[1:]:
        m = _FIELD_PATTERN.match(line.strip())
        if m:
            fields[m.group(1)] = m.group(2).strip()
    return fields


def extract_card_link(fields: dict[str, str]) -> str | None:
    """取卡片里的真实内容链接（``jump_url``），没有则 ``None``。

    「图文H5」卡片带 ``jump_url``，应优先按链接解析而不是按标题搜索。
    """
    link = (fields.get("jump_url") or "").strip()
    if not link.lower().startswith(("http://", "https://")):
        return None
    return link.rstrip(_LINK_TRAILING_PUNCT) or None


def extract_card_title(fields: dict[str, str]) -> str | None:
    """取卡片标题作为搜索关键词：``title`` 字段优先，回退摘要。

    摘要通常比 ``title`` 多一个「[QQ小程序]」之类的修饰前缀，回退时剥掉
    「[QQ小程序]」；「图文H5」卡片的「【分享】」等括号段交给搜索关键词
    变体（见 ``BilibiliParser._title_search_variants``）处理。
    """
    title = (fields.get("title") or "").strip()
    if title:
        return title
    abstract = (fields.get("摘要") or "").strip()
    return _QQ_MINIAPP_PREFIX.sub("", abstract).strip() or None
