# -*- coding: utf-8 -*-
"""Terminal progress rendering."""

from __future__ import annotations

import re
import shutil
import threading
import time
import sys
import unicodedata


class ProgressPrinter:
    def __init__(self, total_hint_seconds: int = 180, steps: list[tuple[int, str]] | None = None, title: str = "处理中") -> None:
        self.started = time.time()
        self.total_hint_seconds = total_hint_seconds
        self.title = title
        self.percent = 0
        self.label = "准备"
        self.steps = steps or [(100, "完成")]
        self.last_text = ""
        self.line_len = 0
        self.has_line = False
        self.done = False
        self.lock = threading.Lock()

    def start(self) -> None:
        self.done = False

    def stop(self) -> None:
        with self.lock:
            self.done = True
        if self.has_line:
            print()
            self.has_line = False

    @staticmethod
    def clock(seconds: float) -> str:
        seconds = max(0, int(seconds))
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    _clock = clock

    @staticmethod
    def _short_label(label: str) -> str:
        scan = re.search(r"扫描(人口|战斗)条目\s+([\d,]+)/([\d,]+)", label)
        if scan:
            kind, done_raw, total_raw = scan.groups()
            done = int(done_raw.replace(",", ""))
            total = int(total_raw.replace(",", ""))
            left = max(total - done, 0)
            if kind == "人口":
                kind = "人口组"
            return f"{kind} {done_raw}/{total_raw}，剩 {left:,}"
        if "仍在处理" in label:
            return label.replace("，仍在处理", "")
        if len(label) > 32:
            return label[:31] + "..."
        return label

    @staticmethod
    def _fit_line(text: str, previous_len: int) -> tuple[str, str]:
        width = max(shutil.get_terminal_size((96, 20)).columns - 1, 1)
        fitted = ''
        cells = 0
        for char in text:
            size = 0 if unicodedata.combining(char) else 2 if unicodedata.east_asian_width(char) in 'WF' else 1
            if cells + size > width:
                break
            fitted += char
            cells += size
        text = fitted
        padding = " " * max(0, min(previous_len, width) - cells)
        return text, padding

    def _step(self, percent: int) -> tuple[int, str]:
        for index, (upper, name) in enumerate(self.steps, 1):
            if percent <= upper:
                return index, name
        return len(self.steps), self.steps[-1][1]

    def __call__(self, percent: int, label: str, force: bool = False, remember: bool = True) -> None:
        percent = max(0, min(100, int(percent)))
        with self.lock:
            self.percent = max(self.percent, percent)
            if remember:
                self.label = label
            percent = self.percent
            step_index, step_name = self._step(percent)
            detail = self._short_label(label)
            current = "完成" if percent >= 100 else detail or step_name
            text = f"{self.title} · {current}"
            if not force and text == self.last_text:
                return
            self.last_text = text
            if not sys.stdout.isatty():
                return
            text, padding = self._fit_line(text, self.line_len)
            print("\r" + text + padding, end="", flush=True)
            self.line_len = sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in text)
            self.has_line = True
