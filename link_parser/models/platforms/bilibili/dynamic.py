from typing import Any
from msgspec import Struct, convert


class AuthorInfo(Struct):
    name: str
    face: str
    mid: int
    pub_time: str
    pub_ts: int | str


class VideoArchive(Struct):
    aid: str
    bvid: str
    title: str
    desc: str
    cover: str
    duration_text: str = ""

    @property
    def duration_seconds(self) -> float:
        if not self.duration_text:
            return 0.0
        parts = self.duration_text.split(":")
        try:
            if len(parts) == 2:
                return int(parts[0]) * 60 + int(parts[1])
            elif len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        except ValueError:
            pass
        return 0.0


class OpusImage(Struct):
    url: str


class OpusSummary(Struct):
    text: str


class OpusContent(Struct):
    jump_url: str
    pics: list[OpusImage]
    summary: OpusSummary
    title: str | None = None


class DynamicMajor(Struct):
    type: str | None = None
    archive: VideoArchive | None = None
    opus: OpusContent | None = None
    desc: OpusSummary | None = None

    @property
    def title(self) -> str | None:
        if self.type == "MAJOR_TYPE_ARCHIVE" and self.archive:
            return self.archive.title
        if self.type == "MAJOR_TYPE_OPUS" and self.opus:
            return self.opus.title
        return None

    @property
    def text(self) -> str | None:
        if self.type == "MAJOR_TYPE_ARCHIVE" and self.archive:
            return self.archive.desc
        elif self.type == "MAJOR_TYPE_OPUS" and self.opus:
            return self.opus.summary.text
        elif self.desc:
            return self.desc.text
        return None

    @property
    def image_urls(self) -> list[str]:
        if self.type == "MAJOR_TYPE_OPUS" and self.opus:
            return [pic.url for pic in self.opus.pics]
        elif self.type == "MAJOR_TYPE_ARCHIVE" and self.archive and self.archive.cover:
            return [self.archive.cover]
        return []

    @property
    def cover_url(self) -> str | None:
        if self.type == "MAJOR_TYPE_ARCHIVE" and self.archive:
            return self.archive.cover
        return None

    @property
    def duration(self) -> float:
        if self.type == "MAJOR_TYPE_ARCHIVE" and self.archive:
            return self.archive.duration_seconds
        return 0.0


class DynamicModule(Struct):
    module_author: AuthorInfo
    module_dynamic: dict[str, Any] | None = None
    module_stat: dict[str, Any] | None = None
    _cached_major: DynamicMajor | None = None

    @property
    def author_name(self) -> str:
        return self.module_author.name

    @property
    def author_face(self) -> str:
        return self.module_author.face

    @property
    def pub_ts(self) -> int:
        ts = self.module_author.pub_ts
        if isinstance(ts, str):
            return int(ts)
        return ts

    @property
    def _major_info(self) -> dict[str, Any] | None:
        if self.module_dynamic:
            if major := self.module_dynamic.get("major"):
                return major
            return self.module_dynamic
        return None

    @property
    def major(self) -> DynamicMajor | None:
        if self._cached_major is None:
            major_info = self._major_info
            if major_info:
                self._cached_major = convert(major_info, DynamicMajor)
        return self._cached_major

    @property
    def desc_text(self) -> str | None:
        if self.module_dynamic:
            desc = self.module_dynamic.get("desc")
            if desc and isinstance(desc, dict):
                return desc.get("text")
        return None


class DynamicInfo(Struct):
    id_str: str
    type: str
    visible: bool
    modules: DynamicModule
    basic: dict[str, Any] | None = None
    orig: "DynamicInfo | None" = None

    @property
    def name(self) -> str:
        return self.modules.author_name

    @property
    def avatar(self) -> str:
        return self.modules.author_face

    @property
    def timestamp(self) -> int:
        return self.modules.pub_ts

    @property
    def title(self) -> str | None:
        if major := self.modules.major:
            return major.title

    @property
    def text(self) -> str | None:
        if desc_text := self.modules.desc_text:
            return desc_text
        if major := self.modules.major:
            return major.text

    @property
    def image_urls(self) -> list[str]:
        if major := self.modules.major:
            return major.image_urls
        return []

    def is_video(self) -> bool:
        major = self.modules.major
        return major is not None and major.archive is not None


class DynamicWrapper(Struct):
    item: DynamicInfo
