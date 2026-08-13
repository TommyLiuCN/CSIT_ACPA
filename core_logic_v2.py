"""
core_logic_v2.py — 改进版自动输入引擎

改进项:
  1. 并发锁: 防止 F8 快速连按导致多个打字任务冲突
  2. 正确返回值: 部分失败返回 False
  3. 批量粘贴: 连续非 ASCII 字符整段粘贴，避免 O(n²) 剪贴板读写
  4. if __name__ 保护
  5. 完整类型注解
  6. 默认速度与 GUI 一致 (0.05s)
  7. 中止机制: 通过 abort_typing() 可随时打断
"""

import threading
import time
from collections.abc import Callable

import keyboard
import pyperclip
from pynput.keyboard import Controller, Key

kb_controller = Controller()

# ── 并发控制 ──────────────────────────────────────────────
_typing_lock = threading.Lock()
_abort_event = threading.Event()


def abort_typing() -> None:
    """请求中止正在进行的输入。"""
    _abort_event.set()


# ── 核心功能 ──────────────────────────────────────────────

def _is_ascii_safe(char: str) -> bool:
    """判断字符是否可以用 pynput.type() 安全输入（ASCII 可打印字符）"""
    return char.isascii() and char.isprintable()


def _segment_content(content: str) -> list[tuple[str, str]]:
    """
    将文本按 ASCII / 非 ASCII / 换行 分段。

    返回: [(type, text), ...]
      type ∈ {'ascii', 'non-ascii', 'newline'}
    """
    segments: list[tuple[str, str]] = []
    current: list[str] = []
    current_type: str | None = None

    for char in content:
        if char == "\n":
            # 刷出当前段
            if current:
                segments.append((current_type or "ascii", "".join(current)))  # type: ignore[arg-type]
                current = []
            segments.append(("newline", "\n"))
            current_type = None
        else:
            is_ascii = _is_ascii_safe(char)
            char_type = "ascii" if is_ascii else "non-ascii"
            if current_type != char_type:
                if current:
                    segments.append((current_type or "ascii", "".join(current)))  # type: ignore[arg-type]
                    current = []
                current_type = char_type
            current.append(char)

    if current:
        segments.append((current_type or "ascii", "".join(current)))  # type: ignore[arg-type]

    return segments


def _clipboard_paste_text(text: str) -> None:
    """通过剪贴板粘贴方式输入一段文本（用于非 ASCII 字符块）。"""
    original = pyperclip.paste()
    try:
        pyperclip.copy(text)
        time.sleep(0.02)
        kb_controller.press(Key.ctrl_l)
        kb_controller.press("v")
        kb_controller.release("v")
        kb_controller.release(Key.ctrl_l)
        time.sleep(0.05)
    finally:
        time.sleep(0.02)
        pyperclip.copy(original)


def perform_typing(speed: float = 0.05) -> bool:
    """
    从剪贴板读取内容并模拟键盘输入。

    参数:
        speed: 每段输入后的间隔秒数

    返回:
        True  — 全部成功
        False — 剪贴板为空 或 部分字符输入失败 或 被中止
    """
    # ── 并发防护 ──
    if not _typing_lock.acquire(blocking=False):
        print("正在输入中，请勿重复触发")
        return False

    _abort_event.clear()
    overall_success = True

    try:
        content = pyperclip.paste()
        if not content:
            print("剪贴板是空的！")
            return False

        # 统一换行符
        content = content.replace("\r\n", "\n").replace("\r", "\n")
        segments = _segment_content(content)

        for seg_type, seg_text in segments:
            # ── 检查中止信号 ──
            if _abort_event.is_set():
                print("输入已中止")
                overall_success = False
                break

            try:
                if seg_type == "newline":
                    kb_controller.press(Key.enter)
                    kb_controller.release(Key.enter)
                elif seg_type == "ascii":
                    kb_controller.type(seg_text)
                else:  # non-ascii
                    _clipboard_paste_text(seg_text)
                time.sleep(speed)
            except Exception as e:
                print(f"段 {seg_type!r} 输入失败: {e}")
                overall_success = False
                # 不 break — 能输多少输多少
    finally:
        _typing_lock.release()

    return overall_success


def bind_hotkey(callback_func: Callable[[], None]) -> None:
    """绑定全局热键 F8"""
    keyboard.add_hotkey("f8", callback_func)


def bind_abort_hotkey(callback_func: Callable[[], None]) -> None:
    """绑定中止热键 F9"""
    keyboard.add_hotkey("f9", callback_func)


# ── 独立测试入口 ──────────────────────────────────────────

if __name__ == "__main__":
    print("core_logic_v2 模块加载成功")
    print("类型提示、并发锁、批量粘贴、中止支持均已启用")
