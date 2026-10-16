"""One place that decides what text the system will store. Anything that reaches the database as a string goes through here first, so a bad character is a
clear 400/422 to the caller, never a crash: a NUL character cannot be sent to the database, and a lone surrogate cannot be encoded as UTF-8."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, model_validator

NUL = chr(0)


def check_text(value: Any, where: str = "arguments") -> None:
    """Raise ValueError for text that cannot be stored, however deeply it is nested in dicts and lists."""
    if isinstance(value, str):
        if NUL in value:
            raise ValueError(f"{where} cannot contain a NUL (zero) character")
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError(f"{where} contains characters that are not valid text") from None
    elif isinstance(value, dict):
        for k, v in value.items():
            check_text(k, where)
            check_text(v, where)
    elif isinstance(value, (list, tuple)):
        for v in value:
            check_text(v, where)


class Clean(BaseModel):
    """Base for every request body: all its text is checked once it has parsed."""

    @model_validator(mode="after")
    def _no_bad_text(self):
        check_text(self.model_dump(), "the request")
        return self
