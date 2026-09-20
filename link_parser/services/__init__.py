"""有状态服务层（每个服务一个模块，按功能命名）。

- :mod:`~link_parser.services.downloader`         异步流式媒体下载
- :mod:`~link_parser.services.card_render`        解析结果卡片渲染（Pillow，多模块子系统）
- :mod:`~link_parser.services.web_screenshot`     Cloudflare Browser Rendering 网页截图
- :mod:`~link_parser.services.live_photo`         实况照片（主图 + 短视频）单文件合成
- :mod:`~link_parser.services.bilibili_account`   B站扫码登录 / Cookie 监控与自动应用

多模块子系统才使用子包（如 ``card_render``），单模块服务保持单文件。

本模块刻意不做二次导出：各服务依赖差异较大，按需直接 import 子模块即可，
以避免无关依赖（Pillow / aiohttp 等）在导入期被一并加载。
"""

__all__: list[str] = []
