"""抖音 aweme detail 接口数据模型"""

from msgspec import Struct, field
from msgspec.json import Decoder


class UrlList(Struct):
    url_list: list[str]


class Addr(Struct):
    uri: str

    @property
    def url(self) -> str:
        return f"https://aweme.snssdk.com/aweme/v1/play/?video_id={self.uri}&ratio=1080p&line=0"


class Author(Struct):
    nickname: str
    avatar_thumb: UrlList

    @property
    def avatar_url(self) -> str:
        return self.avatar_thumb.url_list[-1]


class Video(Struct):
    play_addr: Addr
    cover: UrlList
    duration: int
    cover_original_scale: UrlList | None = None

    @property
    def url(self) -> str:
        return self.play_addr.url

    @property
    def duration_seconds(self) -> float:
        return self.duration / 1000

    @property
    def cover_url(self) -> str:
        if self.cover_original_scale:
            return self.cover_original_scale.url_list[-1]
        return self.cover.url_list[-1]


class Image(Struct):
    url_list: list[str] = field(default_factory=list)
    clip_type: int | None = None
    video: Video | None = None


class ShareInfo(Struct):
    share_desc: str = ""
    share_desc_info: str = ""

    @property
    def text(self) -> str:
        return self.share_desc_info.replace(f"#{self.share_desc}#", "", 1)


class Aweme(Struct):
    aweme_id: str
    author: Author
    create_time: int
    desc: str = ""
    share_url: str = ""
    share_info: ShareInfo = field(default_factory=ShareInfo)
    images: list[Image] | None = None
    video: Video | None = None


class Response(Struct):
    aweme_detail: Aweme


decoder = Decoder(Response)
