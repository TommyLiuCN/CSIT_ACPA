"""
core_logic_v3.py — CSIT_ACPA V3 自动输入引擎

V3 相对 V2 的关键改进:
  1. [关键修复] 输入移至独立工作线程
     v2 中 F8 热键回调在 keyboard 钩子线程内同步执行 perform_typing,
     整个输入期间钩子线程被阻塞, F9 中止事件根本无法被处理 → 中止功能实际失效。
     v3 中 start_typing() 启动 daemon 工作线程执行输入, 热键回调立即返回,
     F9 的 abort_typing() 随时可生效。
  2. 可中止睡眠: 段间等待也检查中止信号, F9 响应 ≤ 0.1s
  3. 结果枚举 TypingResult: 成功 / 空剪贴板 / 重复触发 / 中止 / 失败
  4. 长段分块输入: 超长 ASCII/中文段按 CHUNK_SIZE 分块, 块间可中止
  5. 剪贴板只备份/恢复一次(可关闭), 不再每段读写
  6. Tab 显式映射 Key.tab
  7. 日志回调 on_log + 完成回调 on_done, 供 GUI 实时展示
  8. 可选开始倒计时 delay, 倒计时中也可 F9 取消
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from enum import Enum

import keyboard
import pyperclip
from pynput.keyboard import Controller, Key

kb_controller = Controller()

# ── 结果枚举 ──────────────────────────────────────────────


class TypingResult(Enum):
    """输入结果, 供 GUI 区分展示。"""

    SUCCESS = "输入完成"
    EMPTY_CLIPBOARD = "剪贴板是空的"
    BUSY = "正在输入中, 已忽略本次触发"
    ABORTED = "输入被中止"
    ERROR = "输入失败(部分字符未能输入)"


# ── 可调配置 ──────────────────────────────────────────────

DEFAULT_SPEED = 0.05          # 每段/每块输入后的间隔(秒)
CHUNK_SIZE = 200              # 长段分块大小(字符), 块间可检查中止
PASTE_SETTLE_DELAY = 0.02     # 剪贴板写入后等待(秒)
PASTE_AFTER_DELAY = 0.05      # 模拟 Ctrl+V 后等待(秒)
RESTORE_CLIPBOARD = True      # 输入结束后是否恢复剪贴板原内容
ABORT_POLL_INTERVAL = 0.1     # 可中止睡眠的轮询间隔(秒)

# ── 并发控制 ──────────────────────────────────────────────

_typing_lock = threading.Lock()
_abort_event = threading.Event()


def abort_typing() -> None:
    """请求中止正在进行的输入(含倒计时阶段)。"""
    _abort_event.set()


# ── 字符分段 ──────────────────────────────────────────────


def _is_ascii_safe(char: str) -> bool:
    """判断字符是否可用 pynput.type() 安全输入(ASCII 可打印字符)。"""
    return char.isascii() and char.isprintable()


def _segment_content(content: str, chunk_size: int = CHUNK_SIZE) -> list[tuple[str, str]]:
    """
    将文本分段并分块。

    返回: [(type, text), ...], type ∈ {'ascii', 'non-ascii', 'newline', 'tab'}
    超过 chunk_size 的 ascii / non-ascii 段会被拆成多个块, 以便在块间检查中止信号。
    """
    segments: list[tuple[str, str]] = []
    current: list[str] = []
    current_type: str | None = None

    def flush() -> None:
        nonlocal current, current_type
        if current:
            segments.append((current_type or "ascii", "".join(current)))
            current = []
        current_type = None

    for char in content:
        if char == "\n":
            flush()
            segments.append(("newline", "\n"))
        elif char == "\t":
            flush()
            segments.append(("tab", "\t"))
        else:
            char_type = "ascii" if _is_ascii_safe(char) else "non-ascii"
            if current_type != char_type:
                flush()
                current_type = char_type
            current.append(char)
    flush()

    # 长段分块
    chunked: list[tuple[str, str]] = []
    for seg_type, text in segments:
        if seg_type in ("ascii", "non-ascii") and len(text) > chunk_size:
            chunked.extend(
                (seg_type, text[i : i + chunk_size])
                for i in range(0, len(text), chunk_size)
            )
        else:
            chunked.append((seg_type, text))
    return chunked


# ── 剪贴板操作 ────────────────────────────────────────────


def _copy_to_clipboard(text: str) -> None:
    pyperclip.copy(text)
    time.sleep(PASTE_SETTLE_DELAY)


def _paste_clipboard() -> None:
    kb_controller.press(Key.ctrl_l)
    kb_controller.press("v")
    kb_controller.release("v")
    kb_controller.release(Key.ctrl_l)
    time.sleep(PASTE_AFTER_DELAY)


def _restore_clipboard(text: str) -> None:
    time.sleep(PASTE_SETTLE_DELAY)
    pyperclip.copy(text)


# ── 可中止睡眠 ────────────────────────────────────────────


def _sleep_interruptible(seconds: float) -> bool:
    """可中止的睡眠; 被中止返回 False, 正常走完返回 True。"""
    end = time.monotonic() + max(0.0, seconds)
    while True:
        remaining = end - time.monotonic()
        if remaining <= 0:
            return True
        if _abort_event.wait(min(ABORT_POLL_INTERVAL, remaining)):
            return False


# ── 核心输入流程 ──────────────────────────────────────────


def _perform_typing_locked(
    speed: float,
    *,
    on_log: Callable[[str], None] | None,
    restore_clipboard: bool,
) -> TypingResult:
    """输入主体; 调用前必须已持有 _typing_lock。"""

    def log(msg: str) -> None:
        if on_log is not None:
            on_log(msg)

    _abort_event.clear()
    aborted = False
    error = False
    original_clipboard: str | None = None

    try:
        content = pyperclip.paste()
        if not content:
            log("剪贴板是空的")
            return TypingResult.EMPTY_CLIPBOARD

        # 统一换行符
        content = content.replace("\r\n", "\n").replace("\r", "\n")
        segments = _segment_content(content)

        if restore_clipboard:
            original_clipboard = content

        log(f"开始输入: {len(content)} 字符, {len(segments)} 段")

        for seg_type, seg_text in segments:
            if _abort_event.is_set():
                log("已收到中止信号, 停止输入")
                aborted = True
                break

            try:
                if seg_type == "newline":
                    kb_controller.press(Key.enter)
                    kb_controller.release(Key.enter)
                elif seg_type == "tab":
                    kb_controller.press(Key.tab)
                    kb_controller.release(Key.tab)
                elif seg_type == "ascii":
                    kb_controller.type(seg_text)
                else:  # non-ascii
                    _copy_to_clipboard(seg_text)
                    _paste_clipboard()
                if not _sleep_interruptible(speed):
                    log("已收到中止信号, 停止输入")
                    aborted = True
                    break
            except Exception as e:
                log(f"段 {seg_type!r} 输入失败: {e}")
                error = True
                # 不 break — 能输多少输多少

        if not aborted and not error:
            log("输入完成")
    finally:
        if restore_clipboard and original_clipboard is not None:
            try:
                _restore_clipboard(original_clipboard)
            except Exception as e:
                log(f"恢复剪贴板失败: {e}")

    if aborted:
        return TypingResult.ABORTED
    if error:
        return TypingResult.ERROR
    return TypingResult.SUCCESS


# ── 公共 API ──────────────────────────────────────────────


def perform_typing(
    speed: float = DEFAULT_SPEED,
    *,
    on_log: Callable[[str], None] | None = None,
    restore_clipboard: bool = RESTORE_CLIPBOARD,
) -> TypingResult:
    """
    同步执行输入(阻塞调用线程, 供脚本/命令行使用)。

    若已有输入在进行, 返回 TypingResult.BUSY。
    """
    if not _typing_lock.acquire(blocking=False):
        return TypingResult.BUSY
    try:
        return _perform_typing_locked(
            speed, on_log=on_log, restore_clipboard=restore_clipboard
        )
    finally:
        _typing_lock.release()


def start_typing(
    speed: float = DEFAULT_SPEED,
    *,
    delay: float = 0.0,
    on_log: Callable[[str], None] | None = None,
    on_done: Callable[[TypingResult], None] | None = None,
    restore_clipboard: bool = RESTORE_CLIPBOARD,
) -> bool:
    """
    在后台工作线程中执行输入; 热键回调应调用本函数并立即返回。

    返回 True 表示已启动; 若已有输入在进行则返回 False(并通过 on_log/on_done
    异步报告 BUSY)。
    on_log 在任意线程被调用, on_done 在工作线程结束时被调用。
    delay: 开始前的倒计时秒数, 倒计时中按 F9 可取消。
    """
    def worker() -> None:
        if not _typing_lock.acquire(blocking=False):
            if on_log is not None:
                on_log("正在输入中, 请勿重复触发")
            if on_done is not None:
                on_done(TypingResult.BUSY)
            return

        try:
            # 清除历史中止信号(如上次 F9 残留), 再进入倒计时/输入
            _abort_event.clear()

            cancelled = False
            if delay > 0:
                for remaining in range(int(delay), 0, -1):
                    if _abort_event.is_set():
                        cancelled = True
                        break
                    if on_log is not None:
                        on_log(f"⏳ {remaining} 秒后开始 (F9 取消)...")
                    if not _sleep_interruptible(1.0):
                        cancelled = True
                        break

            if cancelled:
                if on_log is not None:
                    on_log("倒计时已取消")
                if on_done is not None:
                    on_done(TypingResult.ABORTED)
                return

            result = _perform_typing_locked(
                speed, on_log=on_log, restore_clipboard=restore_clipboard
            )
        finally:
            _typing_lock.release()

        if on_done is not None:
            on_done(result)

    threading.Thread(target=worker, name="typing-worker", daemon=True).start()
    return True


# ── 热键绑定 ──────────────────────────────────────────────


def bind_hotkey(callback_func: Callable[[], None]) -> None:
    """绑定全局热键 F8(回调在 keyboard 钩子线程中执行, 必须轻量、快速返回)。"""
    keyboard.add_hotkey("f8", callback_func)


def bind_abort_hotkey(callback_func: Callable[[], None]) -> None:
    """绑定中止热键 F9(同上, 必须轻量、快速返回)。"""
    keyboard.add_hotkey("f9", callback_func)


def unhook_all() -> None:
    """移除全部热键与键盘钩子(GUI 关闭时调用)。"""
    keyboard.unhook_all()


# ── 独立测试入口 ──────────────────────────────────────────

if __name__ == "__main__":
    print("core_logic_v3 模块加载成功")

    samples = [
        "abc中\n文\tefg",
        "a" * 500,
        "中" * 500,
        "ab\n\ncd\t中",
        "",
    ]
    for sample in samples:
        segs = _segment_content(sample, chunk_size=200)
        print(f"  输入 {len(sample)} 字符 → {len(segs)} 段/块")
        for seg_type, text in segs:
            print(f"    {seg_type!r}: {text!r}")

    assert _segment_content("") == []
    assert _segment_content("ab") == [("ascii", "ab")]
    assert _segment_content("中") == [("non-ascii", "中")]
    assert _segment_content("a\nb") == [("ascii", "a"), ("newline", "\n"), ("ascii", "b")]
    assert _segment_content("a\tb") == [("ascii", "a"), ("tab", "\t"), ("ascii", "b")]
    assert _segment_content("a" * 500, chunk_size=200) == [("ascii", "a" * 200)] * 2 + [
        ("ascii", "a" * 100)
    ]
    print("全部断言通过 [OK]")
