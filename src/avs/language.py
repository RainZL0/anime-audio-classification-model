"""The labeling page has Chinese and English versions. Every request from the page carries the
current language in the `X-Language` header, and the messages the server sends back (error reasons,
reasons a clip was not exported) follow it."""

from contextvars import ContextVar

LANGUAGE: ContextVar[str] = ContextVar("language", default="en")
"""The language this request wants, `zh` or `en`. Outside a request (the command line, tests calling
directly) it is English."""


def say(zh: str, en: str) -> str:
    """Pick one sentence by the current request's language."""
    return en if LANGUAGE.get() == "en" else zh


class Words:
    """A sentence kept in both languages and picked only when shown. For messages made outside a
    request but shown inside one, such as "this episode was not loaded" noted at startup."""

    def __init__(self, zh: str, en: str) -> None:
        self.zh, self.en = zh, en

    def __str__(self) -> str:
        return say(self.zh, self.en)
