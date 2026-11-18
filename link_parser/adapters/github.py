"""GitHub 解析器"""

import re
from typing import ClassVar

from httpx import AsyncClient

from ..constants import COMMON_TIMEOUT
from ..exceptions import ParseException
from ..models import ParseResult, Platform
from ..models.platforms.github import repo_decoder
from .base import BaseParser, handle
from .registry import AdapterSpec, register_adapter

#: 仓库接口限流提示（匿名 60 次/小时/IP）
RATE_LIMIT_HINT = "GitHub API 请求受限（匿名额度 60 次/小时/IP），请稍后再试"


def _fmt_num(n: int) -> str:
    return f"{n / 10000:.1f}万" if n >= 10000 else str(n)


class GitHubParser(BaseParser):
    platform: ClassVar[Platform] = Platform(name="github", display_name="GitHub")

    def __init__(self, downloader):
        super().__init__(downloader)
        self.headers["accept"] = "application/vnd.github+json"

    @handle(
        "github.com",
        r"(?<!gist\.)github\.com/(?P<owner>[A-Za-z0-9-]+)/(?P<repo>[A-Za-z0-9_.\-]+)",
    )
    async def _parse(self, searched: re.Match[str]) -> ParseResult:
        owner = searched.group("owner")
        # 允许句尾紧跟英文句号的情况（如「仓库地址：github.com/o/r.」）
        repo = searched.group("repo").rstrip(".")

        api_url = f"https://api.github.com/repos/{owner}/{repo}"
        async with AsyncClient(headers=self.headers, timeout=COMMON_TIMEOUT, verify=False) as client:
            response = await client.get(api_url)
            if response.status_code == 404:
                raise ParseException("GitHub 仓库不存在或已转为私有")
            if response.status_code in (403, 429):
                raise ParseException(RATE_LIMIT_HINT)
            response.raise_for_status()
        repo_info = repo_decoder.decode(response.content)

        stats_map = {
            "🌟": repo_info.stargazers_count,
            "🍴": repo_info.forks_count,
            "🐛": repo_info.open_issues_count,
            "👁": repo_info.subscribers_count,
        }
        stats_line = " ".join(f"{k} {_fmt_num(v)}" for k, v in stats_map.items() if v > 0)

        # 元信息行：语言 / License / Topics / 最近更新，缺失的段自动跳过
        meta_parts = []
        if repo_info.language:
            meta_parts.append(f"🧑‍💻 {repo_info.language}")
        if license_label := repo_info.license_label:
            meta_parts.append(f"📜 {license_label}")
        if repo_info.topics:
            meta_parts.append(f"🏷 {'、'.join(repo_info.topics[:5])}")
        if pushed_ts := repo_info.pushed_timestamp:
            from datetime import datetime

            meta_parts.append(f"🕒 {datetime.fromtimestamp(pushed_ts):%Y-%m-%d} 更新")
        repo_line = " · ".join(meta_parts)

        author = self.create_author(repo_info.owner.login, repo_info.owner.avatar_url)
        return self.result(
            title=repo_info.full_name,
            text=repo_info.description,
            url=repo_info.html_url,
            timestamp=repo_info.pushed_timestamp,
            author=author,
            extra={
                "content_type": "仓库",
                "stats_line": stats_line,
                "repo_line": repo_line,
            },
        )


ADAPTER = register_adapter(
    AdapterSpec(
        name="github",
        url_pattern=re.compile(r"(?<!gist\.)github\.com"),
        parser_cls=GitHubParser,
        description="仓库信息（Star / Fork / Issues / 语言 / License / Topics）",
        priority=100,
    )
)
