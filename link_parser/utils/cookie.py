"""Cookie 解析工具。"""


def ck2dict(cookies_str: str) -> dict[str, str]:
    """将 cookies 字符串转换为字典"""
    res = {}
    for cookie in cookies_str.split(";"):
        name, value = cookie.strip().split("=", 1)
        res[name] = value
    return res
