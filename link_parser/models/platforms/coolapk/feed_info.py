"""酷安 API ``/v6/feed/detail`` 返回结构（只取需要的字段）。"""

from msgspec import Struct
from msgspec.json import Decoder


class FeedInfo(Struct, kw_only=True):
    entityType: str | None = None
    username: str = ""
    userAvatar: str | None = None
    #: 发布时间（秒级时间戳）
    dateline: int | None = None
    #: 相对时间文案（昨天 / 3天前），网页回退路径用它兜底
    dateline_text: str | None = None
    #: 正文（HTML 片段：话题 <a> 链接 + 换行 + [表情] 文字）
    message: str | None = None
    picArr: list[str] = []
    pic: str | None = None
    likenum: int = 0
    replynum: int = 0
    favnum: int = 0
    forwardnum: int = 0
    viewnum: int = 0
    feedTypeName: str | None = None
    device_title: str | None = None


class FeedResponse(Struct, kw_only=True):
    """/v6/feed/detail 的响应信封，动态信息在 ``data`` 键下。"""

    data: FeedInfo | None = None


decoder: Decoder[FeedResponse] = Decoder(FeedResponse)
