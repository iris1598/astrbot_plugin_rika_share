from typing import Any
from dataclasses import dataclass
from msgspec import Struct


class Author(Struct):
    name: str
    face: str
    mid: int
    pub_time: str
    pub_ts: int


class Image(Struct):
    url: str


class Pic(Struct):
    pics: list[Image]
    style: int


class Text(Struct):
    nodes: list[dict[str, Any]]


class Paragraph(Struct):
    para_type: int
    text: Text | None = None
    pic: Pic | None = None


class Content(Struct):
    paragraphs: list[Paragraph]


class Stat(Struct):
    like: dict[str, Any] | None = None
    comment: dict[str, Any] | None = None
    forward: dict[str, Any] | None = None
    favorite: dict[str, Any] | None = None
    coin: dict[str, Any] | None = None


class Module(Struct):
    module_type: str
    module_author: Author | None = None
    module_content: Content | None = None


class Basic(Struct):
    title: str


class Info(Struct):
    id_str: str
    type: int
    modules: list[Module]
    basic: Basic | None = None


@dataclass(slots=True)
class ImageNode:
    url: str
    alt: str | None = None


class OpusItem(Struct):
    item: Info

    @property
    def title(self) -> str | None:
        return self.item.basic.title if self.item.basic else None

    @property
    def name_avatar(self) -> tuple[str, str]:
        author_module = next(module.module_author for module in self.item.modules if module.module_author)
        return author_module.name, author_module.face

    @property
    def timestamp(self) -> int | None:
        for module in self.item.modules:
            if module.module_type == "MODULE_TYPE_AUTHOR" and module.module_author:
                return module.module_author.pub_ts
        return None

    def extract_nodes(self):
        for module in self.item.modules:
            if module.module_type == "MODULE_TYPE_CONTENT" and module.module_content:
                iterator = iter(module.module_content.paragraphs)
                for paragraph in iterator:
                    if paragraph.text and paragraph.text.nodes:
                        cur_text = "".join(
                            text for text, _ in self._extract_texts_from_nodes(paragraph.text.nodes)
                        ).strip()
                        if cur_text:
                            yield cur_text
                    if paragraph.pic and paragraph.pic.pics:
                        for pic in paragraph.pic.pics:
                            image_node = ImageNode(url=pic.url)
                            next_text = ""
                            if (next_par := next(iterator, None)) and next_par.text and next_par.text.nodes:
                                for text, color in self._extract_texts_from_nodes(next_par.text.nodes):
                                    if color == "#999999":
                                        image_node.alt = text
                                    else:
                                        next_text += text
                            yield image_node
                            next_text = next_text.strip()
                            if next_text:
                                yield next_text

    def _extract_texts_from_nodes(self, nodes: list[dict[str, Any]]) -> list[tuple[str, str | None]]:
        texts: list[tuple[str, str | None]] = []
        for node in nodes:
            if node.get("type") in ("TEXT_NODE_TYPE_WORD", "TEXT_NODE_TYPE_RICH") and node.get("word"):
                text = node["word"]["words"]
                color = node["word"]["color"]
                texts.append((text, color))
        return texts
