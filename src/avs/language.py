"""标注网页有中文和英文两版，网页的每个请求都在 `X-Language` 头里带上当前的语言，
服务端回的提示（出错原因、导出时没导出的原因）跟着换。命令行一律用中文。"""

from __future__ import annotations

from contextvars import ContextVar

LANGUAGE: ContextVar[str] = ContextVar("language", default="zh")
"""这个请求要的语言，`zh` 或 `en`。不在请求里（命令行、测试直接调用）时是中文。"""


def say(zh: str, en: str) -> str:
    """按当前请求的语言挑一句。"""
    return en if LANGUAGE.get() == "en" else zh


class Words:
    """两种语言都记着、到显示时才挑的一句话。给不在请求里生成、却要在请求里显示的提示用，
    比如启动时记下的「这一集没载入」。"""

    def __init__(self, zh: str, en: str) -> None:
        self.zh, self.en = zh, en

    def __str__(self) -> str:
        return say(self.zh, self.en)
