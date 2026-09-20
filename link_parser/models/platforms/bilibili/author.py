from msgspec import Struct


class Upper(Struct):
    mid: int
    name: str
    face: str
