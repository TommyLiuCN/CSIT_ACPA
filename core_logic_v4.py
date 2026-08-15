"""
core_logic_v4.py — CSIT_ACPA V4 自动输入引擎

V4 相对 V3 的关键改进:
  1. [核心] SendInput + KEYEVENTF_UNICODE 逐字符注入
     v3 对 ASCII 用 pynput.type()(走键盘布局映射), 非 ASCII 用剪贴板粘贴兜底。
       - 中文输入法(微软拼音/搜狗)激活时, 布局映射的字母键事件被 IME 合成窗口
         吞掉, ASCII 部分直接失效;
       - 网页 onpaste preventDefault() 会拦截剪贴板粘贴, 恰恰无法用于
         "禁止粘贴" 的页面(本工具的初衷场景)。
     v4 改用 SendInput + KEYEVENTF_UNICODE 直接注入 Unicode 字符:
       - 不经过键盘布局与 IME: 中英文都直接生成 WM_CHAR 进入输入框;
       - 不碰剪贴板: 天然免疫网页禁止粘贴;
       - 对浏览器而言事件真实(isTrusted=True), 页面 JS 无法与人工输入区分。
  2. 剪贴板只读不写: 无备份/恢复开销, 移除恢复选项。
  3. 保留 V3 工程化成果: 工作线程 / F9 中止 / 可中止睡眠 / 结果枚举 /
     线程安全 GUI 消息队列 / 长段可分块逐字符检查中止。

已知限制:
  - 仅支持 Windows (ctypes 调 user32.SendInput)。
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import threading
import time
from collections.abc import Callable
from enum import Enum

import keyboard
import pyperclip

# ── Win32 常量 ─────────────────────────────────────────────

INPUT_KEYBOARD = 1
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_KEYUP = 0x0002
VK_RETURN = 0x0D
VK_TAB = 0x09


class MOUSEINPUT(ctypes.Structure):
    _fields_ = (
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    )


class KEYBDINPUT(ctypes.Structure):
    _fields_ = (
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    )


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = (
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    )


class _INPUTUNION(ctypes.Union):
    _fields_ = (("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT))


class INPUT(ctypes.Structure):
    _anonymous_ = ("_input",)
    _fields_ = (("type", wintypes.DWORD), ("_input", _INPUTUNION))


def _send_input(inputs: "tuple[INPUT, INPUT]") -> int:
    """发送一组键盘输入, 返回 SendInput 实际发送数量。"""
    array = (INPUT * len(inputs))(*inputs)
    return ctypes.windll.user32.SendInput(
        len(inputs), ctypes.byref(array), ctypes.sizeof(INPUT)
    )


def _input_event(wscan: int, wvk: int, keyup: bool) -> INPUT:
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ki.wVk = wvk
    inp.ki.wScan = wscan
    inp.ki.dwFlags = (KEYEVENTF_UNICODE if wscan and not wvk else 0) | (
        KEYEVENTF_KEYUP if keyup else 0
    )
    inp.ki.time = 0
    inp.ki.dwExtraInfo = None
    return inp


def _type_unicode(char: str) -> None:
    """通过 SendInput 注入单个 Unicode 字符(绕过布局与 IME)。"""
    code = ord(char)
    _send_input(
        (
            _input_event(code, 0, False),
            _input_event(code, 0, True),
        )
    )


def _press_vk(vk: int) -> None:
    """按下并抬起一个虚拟键(回车/Tab 等)。"""
    _send_input(
        (
            _input_event(0, vk, False),
            _input_event(0, vk, True),
        )
    )


# ── 结果枚举 ──────────────────────────────────────────────


class TypingResult(Enum):
    """输入结果, 供 GUI 区分展示。"""

    SUCCESS = "输入完成"
    EMPTY_CLIPBOARD = "剪贴板是空的"
    BUSY = "正在输入中, 已忽略本次触发"
    ABORTED = "输入被中止"
    ERROR = "输入失败(部分字符未能输入)"


# ── 可调配置 ──────────────────────────────────────────────

DEFAULT_SPEED = 0.05          # 每字符输入后的间隔(秒)
ABORT_POLL_INTERVAL = 0.1     # 可中止睡眠的轮询间隔(秒)

# ── 并发控制 ──────────────────────────────────────────────

_typing_lock = threading.Lock()
_abort_event = threading.Event()


def abort_typing() -> None:
    """请求中止正在进行的输入。"""
    _abort_event.set()


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
) -> TypingResult:
    """输入主体; 调用前必须已持有 _typing_lock。"""

    def log(msg: str) -> None:
        if on_log is not None:
            on_log(msg)

    aborted = False
    error = False

    try:
        content = pyperclip.paste()
        if not content:
            log("剪贴板是空的")
            return TypingResult.EMPTY_CLIPBOARD

        # 统一换行符
        content = content.replace("\r\n", "\n").replace("\r", "\n")

        log(f"开始输入: {len(content)} 字符")

        for char in content:
            if _abort_event.is_set():
                log("已收到中止信号, 停止输入")
                aborted = True
                break

            try:
                if char == "\n":
                    _press_vk(VK_RETURN)
                elif char == "\t":
                    _press_vk(VK_TAB)
                else:
                    _type_unicode(char)
                if not _sleep_interruptible(speed):
                    log("已收到中止信号, 停止输入")
                    aborted = True
                    break
            except Exception as e:
                log(f"字符 {char!r} 输入失败: {e}")
                error = True
                # 不 break — 能输多少输多少

        if not aborted and not error:
            log("输入完成")
    finally:
        pass

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
) -> TypingResult:
    """
    同步执行输入(阻塞调用线程, 供脚本/命令行使用)。

    若已有输入在进行, 返回 TypingResult.BUSY。
    """
    if not _typing_lock.acquire(blocking=False):
        return TypingResult.BUSY
    try:
        return _perform_typing_locked(speed, on_log=on_log)
    finally:
        _typing_lock.release()


def start_typing(
    speed: float = DEFAULT_SPEED,
    *,
    on_log: Callable[[str], None] | None = None,
    on_done: Callable[[TypingResult], None] | None = None,
) -> bool:
    """
    在后台工作线程中执行输入; 热键回调应调用本函数并立即返回。

    返回 True 表示已启动; 若已有输入在进行则返回 False(并通过 on_log/on_done
    异步报告 BUSY)。
    on_log 在任意线程被调用, on_done 在工作线程结束时被调用。
    """
    def worker() -> None:
        if not _typing_lock.acquire(blocking=False):
            if on_log is not None:
                on_log("正在输入中, 请勿重复触发")
            if on_done is not None:
                on_done(TypingResult.BUSY)
            return

        try:
            # 清除历史中止信号(如上次 F9 残留)
            _abort_event.clear()
            result = _perform_typing_locked(speed, on_log=on_log)
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
    print("core_logic_v4 模块加载成功 (Windows SendInput 引擎)")

    # 结构体大小自检: 32 位 28 字节, 64 位 40 字节
    expected = {28, 40}
    size = ctypes.sizeof(INPUT)
    print(f"  INPUT 结构体大小: {size} 字节")
    assert size in expected, f"INPUT 结构体大小异常: {size}"

    # 不实际发送按键, 仅验证事件构造
    e = _input_event(ord("中"), 0, False)
    assert e.type == INPUT_KEYBOARD and e.ki.wScan == ord("中")
    assert e.ki.dwFlags & KEYEVENTF_UNICODE
    print("  事件构造自检通过 [OK]")