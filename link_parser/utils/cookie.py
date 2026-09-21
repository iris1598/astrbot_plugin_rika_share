"""Cookie 解析工具。"""


def ck2dict(cookies_str: str) -> dict[str, str]:
    """将 cookies 字符串转换为字典。

    容忍畸形片段：没有 ``=`` 的段（用户从浏览器复制时常见的脏数据、或粘贴了
    整段 HTTP 头）会被跳过，而不是抛 ValueError 打断调用方——B站凭证解析曾因此
    直接失败。空名或空值同样跳过。
    """
    res: dict[str, str] = {}
    for cookie in (cookies_str or "").split(";"):
        segment = cookie.strip()
        if "=" not in segment:
            continue
        name, value = segment.split("=", 1)
        name, value = name.strip(), value.strip()
        if name and value:
            res[name] = value
    return res
