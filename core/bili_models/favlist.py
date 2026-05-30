from msgspec import Struct
from .common import Upper


class FavItem(Struct):
    title: str
    cover: str
    intro: str
    link: str

    @property
    def url(self) -> str:
        return self.link.replace("bilibili://video/", "https://bilibili.com/video/av")

    @property
    def desc(self) -> str:
        return f"标题: {self.title}\n简介: {self.intro}\n链接: {self.url}"

    @property
    def avid(self) -> int:
        return int(self.link.split("/")[-1])


class FavInfo(Struct):
    title: str
    cover: str
    upper: Upper
    ctime: int
    mtime: int
    media_count: int
    intro: str


class FavData(Struct):
    info: FavInfo
    medias: list[FavItem]

    @property
    def title(self) -> str:
        return f"收藏夹 - {self.info.title}"

    @property
    def cover(self) -> str:
        return self.info.cover

    @property
    def desc(self) -> str:
        return self.info.intro

    @property
    def timestamp(self) -> int:
        return self.info.ctime
