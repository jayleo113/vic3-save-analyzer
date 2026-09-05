# -*- coding: utf-8 -*-
"""Small terminal UI helpers used by the launcher."""

from __future__ import annotations

import os
from pathlib import Path


def clear() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def ask(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:
        return ""


def pause() -> None:
    try:
        input("\n按回车返回")
    except EOFError:
        return


def rule(width: int = 56) -> str:
    return "-" * width


def title(text: str, subtitle: str | None = None) -> None:
    print(text)
    if subtitle:
        print(subtitle)
    print(rule())


def menu(title_text: str, items: list[tuple[str, str]], subtitle: str | None = None, footer: str | None = None) -> str:
    clear()
    title(title_text, subtitle)
    print()
    for key, label in items:
        print(f"{key}. {label}")
    if footer:
        print()
        print(footer)
    return ask("\n选择：").strip()


def section(text: str) -> None:
    print()
    print(text)
    print(rule(32))


def done(lines: list[tuple[str, object]]) -> None:
    print("\n完成")
    for label, value in lines:
        print(f"{label}：{value}")


def failed(message: object) -> None:
    print(f"\n失败：{message}")


def open_folder(path: Path) -> None:
    if os.name != "nt":
        return
    try:
        os.startfile(path)
    except OSError:
        pass
