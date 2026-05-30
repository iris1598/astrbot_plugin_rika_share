from dataclasses import dataclass
from msgspec import Struct
from .common import Upper


class Stats(Struct):
    view: int
    danmaku: int
    reply: int
    favorite: int
    coin: int
    share: int
    like: int


class Page(Struct):
    cid: int
    part: str
    ctime: int
    duration: int
    first_frame: str | None = None


@dataclass(frozen=True, slots=True)
class PageInfo:
    index: int
    title: str
    duration: int
    timestamp: int
    cid: int | None = None
    cover: str | None = None


class VideoInfo(Struct):
    bvid: str
    title: str
    desc: str
    duration: int
    owner: Upper
    stat: Stats
    pubdate: int
    ctime: int
    pic: str | None = None
    pages: list[Page] | None = None

    @property
    def title_with_part(self) -> str:
        if self.pages and len(self.pages) > 1:
            return f"{self.title} - {self.pages[0].part}"
        return self.title

    @property
    def formatted_stats_info(self) -> str:
        stats_mapping = [
            ("\U0001f44d", self.stat.like),
            ("\U0001fa99", self.stat.coin),
            ("\u2b50", self.stat.favorite),
            ("\u21a9\ufe0f", self.stat.share),
            ("\U0001f4ac", self.stat.reply),
            ("\U0001f440", self.stat.view),
            ("\U0001f4ad", self.stat.danmaku),
        ]
        result_parts = []
        for display_name, value in stats_mapping:
            formatted_value = f"{value / 10000:.1f}万" if value > 10000 else str(value)
            result_parts.append(f"{display_name} {formatted_value}")
        return " ".join(result_parts)

    def extract_info_with_page(self, page_num: int = 1) -> PageInfo:
        page_idx = page_num - 1
        title = self.title
        duration = self.duration
        cover = self.pic
        timestamp = self.pubdate
        cid = None
        if self.pages and len(self.pages) > 1:
            page_idx = page_idx % len(self.pages)
            page = self.pages[page_idx]
            title += f" | 分集 - {page.part}"
            duration = page.duration
            cover = page.first_frame
            timestamp = page.ctime
            cid = page.cid
        elif self.pages:
            cid = self.pages[0].cid
        return PageInfo(index=page_idx, title=title, duration=duration, timestamp=timestamp, cover=cover, cid=cid)


class ModelResult(Struct):
    summary: str


class AIConclusion(Struct):
    model_result: ModelResult | None = None

    @property
    def summary(self) -> str:
        if self.model_result and self.model_result.summary:
            return f"AI总结: {self.model_result.summary}"
        return "该视频暂不支持AI总结"
