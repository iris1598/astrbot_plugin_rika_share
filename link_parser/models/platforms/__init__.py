"""各平台接口返回结构模型（统一为「一个平台一个子包」）。

约定：

- 一个平台一个子包，子包内按「接口 / 资源」拆分模块，例如
  ``video_info.py``（视频信息）、``aweme.py``（抖音作品）、``init_state.py``（快手页面状态）、
  ``status.py``（微博正文）、``note.py``（小红书笔记媒体）；
- 子包 ``__init__.py`` 显式导出对外接口（响应数据结构 + ``decoder``），
  适配器统一写 ``from ..models.platforms.<平台> import ...``，不直接依赖子包内部的模块名，
  这样调整内部拆分不会影响适配器；
- 一个平台内多个模块都定义 ``decoder`` 时，导出时按语义加前缀
  （如 ``article_decoder`` / ``status_decoder`` / ``explore_decoder``）。
"""

__all__: list[str] = []
