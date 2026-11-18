"""GitHub 接口返回结构模型。

- ``repo_info``：`/repos/{owner}/{repo}` 接口返回的仓库信息
"""

from .repo_info import RepoInfo, RepoLicense, RepoOwner
from .repo_info import decoder as repo_decoder

__all__ = [
    "RepoInfo",
    "RepoLicense",
    "RepoOwner",
    "repo_decoder",
]
