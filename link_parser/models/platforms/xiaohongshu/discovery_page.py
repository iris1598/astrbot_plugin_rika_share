from msgspec import Struct
from msgspec.json import Decoder

from .note import Video

#: 小红书图床原图地址：fileId 就是 imageList[n].fileId
ORIGINAL_IMAGE_URL = "https://ci.xiaohongshu.com/{file_id}?imageView2/2/format/jpg"


class ImageInfo(Struct):
    url: str = ""


class Image(Struct):
    fileId: str = ""
    url: str = ""
    urlDefault: str | None = None
    urlSizeLarge: str | None = None
    infoList: list[ImageInfo] = []

    @property
    def candidate_urls(self) -> list[str]:
        urls: list[str] = []
        if self.fileId:
            urls.append(ORIGINAL_IMAGE_URL.format(file_id=self.fileId))
        for candidate in (self.url, self.urlSizeLarge, self.urlDefault):
            if candidate:
                urls.append(candidate)
        urls.extend(item.url for item in self.infoList if item.url)
        return list(dict.fromkeys(urls))

    @property
    def best_url(self) -> str | None:
        urls = self.candidate_urls
        return urls[0] if urls else None


class User(Struct):
    nickName: str = ""
    avatar: str | None = None


class NoteData(Struct):
    user: User
    noteId: str = ""
    type: str = "normal"
    title: str = ""
    desc: str = ""
    time: int = 0
    lastUpdateTime: int = 0
    imageList: list[Image] = []
    video: Video | None = None

    @property
    def image_urls(self) -> list[str]:
        return [url for item in self.imageList if (url := item.best_url)]

    @property
    def is_video(self) -> bool:
        return self.type == "video" and self.video is not None

    @property
    def url_and_duration(self) -> tuple[str | None, float]:
        assert self.video is not None
        return self.video.url_and_duration


class NormalNotePreloadData(Struct):
    title: str = ""
    desc: str = ""
    imagesList: list[Image] = []

    @property
    def image_urls(self) -> list[str]:
        return [
            url
            for item in self.imagesList
            if (url := item.urlSizeLarge or item.best_url)
        ]


class NoteDataWrapper(Struct):
    noteData: NoteData


class NoteDataContainer(Struct):
    data: NoteDataWrapper
    normalNotePreloadData: NormalNotePreloadData | None = None


class InitialState(Struct):
    noteData: NoteDataContainer


class LauncherPageData(Struct):
    noteData: NoteData


class SetupInitialState(Struct):
    """移动端页面 ``window.__SETUP_SERVER_STATE__``。

    桌面 UA 会被重定向到登录页；移动端匿名访问返回的 SSR 数据在这里。
    """

    LAUNCHER_SSR_STORE_PAGE_DATA: LauncherPageData | None = None


decoder = Decoder(InitialState)
setup_decoder = Decoder(SetupInitialState)
