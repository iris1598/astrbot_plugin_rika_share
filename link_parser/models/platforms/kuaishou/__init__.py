"""快手接口返回结构模型。

- ``init_state``：分享页 ``window.INIT_STATE`` 内嵌的作品数据（视频 / 图集）
"""

from .init_state import Atlas, CdnUrl, ExtParams, Photo, TusjohData
from .init_state import decoder as init_state_decoder

__all__ = [
    "Atlas",
    "CdnUrl",
    "ExtParams",
    "Photo",
    "TusjohData",
    "init_state_decoder",
]
