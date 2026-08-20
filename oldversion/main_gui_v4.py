"""
main_gui_v4.py — CSIT_ACPA V4 自动输入 GUI

V4 相对 V3 的改进:
  1. [核心] 输入改用 SendInput + KEYEVENTF_UNICODE 逐字符注入
     - 中英文均直接进输入框, 不受中文输入法(IME)拦截
     - 不碰剪贴板, 天然免疫网页禁止粘贴
  2. 移除"结束后恢复剪贴板"选项 — 引擎不再写剪贴板, 无恢复需求
  3. 保留: 实时日志面板 / 结果细分 / 状态复位令牌 / 线程安全消息队列 /
     工作线程 / F8 瞬发 / F9 实时中止 / 关闭窗口清理热键
"""

from __future__ import annotations

import queue
import tkinter as tk
from typing import Any

import customtkinter as ctk

from core_logic_v4 import (
    DEFAULT_SPEED,
    TypingResult,
    abort_typing,
    bind_abort_hotkey,
    bind_hotkey,
    start_typing,
    unhook_all,
)

# 输入结果 → 状态栏文案/颜色
_RESULT_LABELS: dict[TypingResult, tuple[str, str]] = {
    TypingResult.SUCCESS: ("✅ 输入完成", "green"),
    TypingResult.EMPTY_CLIPBOARD: ("⚠️ 剪贴板是空的", "orange"),
    TypingResult.BUSY: ("⚠️ 已在输入中, 本次忽略", "orange"),
    TypingResult.ABORTED: ("⏹ 输入已中止", "orange"),
    TypingResult.ERROR: ("❌ 输入失败", "red"),
}


class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("CSIT_ACPA V4.0")
        self.geometry("420x540")
        self.attributes("-topmost", True)

        # 状态变量(仅在主线程读写; 钩子线程只读 speed)
        self.current_speed: float = DEFAULT_SPEED
        self._msg_queue: "queue.Queue[tuple[str, Any]]" = queue.Queue()
        self._generation: int = 0  # 状态复位令牌: 递增即作废旧复位回调

        self._build_ui()

        # 全局热键(回调在钩子线程中执行, 必须轻量)
        bind_hotkey(self._on_hotkey_f8)
        bind_abort_hotkey(self._on_hotkey_f9)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # 主线程轮询消息队列, 替代从后台线程直接调用 tkinter
        self.after(50, self._poll_queue)

    # ── UI 构建 ────────────────────────────────────────────

    def _build_ui(self) -> None:
        self.label = ctk.CTkLabel(
            self, text="按下 F8 自动输入", font=("Arial", 16, "bold")
        )
        self.label.pack(pady=(16, 8))

        self.slider = ctk.CTkSlider(
            self, from_=0.01, to=0.3, command=self._update_speed
        )
        self.slider.set(self.current_speed)
        self.slider.pack(pady=4)

        self.status = ctk.CTkLabel(
            self, text=f"当前间隔: {self.current_speed}s", text_color="gray"
        )
        self.status.pack()

        self.state_label = ctk.CTkLabel(self, text="就绪", text_color="green")
        self.state_label.pack(pady=6)

        # 日志面板
        self.log_box = ctk.CTkTextbox(self, height=170, font=("Consolas", 11))
        self.log_box.pack(padx=12, pady=(4, 6), fill="both", expand=True)
        self.log_box.configure(state="disabled")

        # 底部按钮 + 快捷键提示
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.pack(pady=(0, 10))
        ctk.CTkButton(bottom, text="清空日志", width=90, command=self._clear_log).pack(
            side="left", padx=6
        )
        ctk.CTkLabel(
            bottom,
            text="F8 开始  |  F9 中止",
            text_color="gray",
            font=("Arial", 11),
        ).pack(side="left", padx=6)

    # ── 热键回调(在 keyboard 钩子线程中执行, 必须轻量) ───────

    def _on_hotkey_f8(self) -> None:
        """F8: 只投递消息 + 启动工作线程, 立即返回(瞬发输入, 无延迟)。"""
        self._msg_queue.put(("start", None))
        start_typing(
            speed=self.current_speed,
            on_log=self._enqueue_log,
            on_done=self._enqueue_done,
        )

    def _on_hotkey_f9(self) -> None:
        """F9: 请求中止, 轻量。"""
        abort_typing()
        self._msg_queue.put(("status", ("⏹ 正在中止...", "orange")))

    # ── 后台线程 → 主线程 消息转发(只 put, 不碰 tkinter) ─────

    def _enqueue_log(self, msg: str) -> None:
        self._msg_queue.put(("log", msg))

    def _enqueue_done(self, result: TypingResult) -> None:
        self._msg_queue.put(("done", result))

    # ── 主线程消息处理 ──────────────────────────────────────

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self._msg_queue.get_nowait()
                if kind == "start":
                    self._on_typing_start()
                elif kind == "status":
                    text, color = payload
                    self.state_label.configure(text=text, text_color=color)
                elif kind == "log":
                    self._append_log(payload)
                elif kind == "done":
                    self._on_typing_done(payload)
        except queue.Empty:
            pass
        self.after(50, self._poll_queue)

    def _on_typing_start(self) -> None:
        self._generation += 1  # 作废未执行的旧复位回调
        self.state_label.configure(text="⏳ 输入中...", text_color="orange")

    def _on_typing_done(self, result: TypingResult) -> None:
        self._generation += 1
        gen = self._generation
        text, color = _RESULT_LABELS.get(result, ("ℹ️ 完成", "green"))
        self.state_label.configure(text=text, text_color=color)
        # 2 秒后复位; 仅当期间没有新的开始/完成时才生效
        self.after(2000, lambda g=gen: self._reset_status(g))

    def _reset_status(self, gen: int) -> None:
        if gen == self._generation:
            self.state_label.configure(text="就绪", text_color="green")

    # ── 日志 ────────────────────────────────────────────────

    def _append_log(self, msg: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    # ── 其他回调 ────────────────────────────────────────────

    def _update_speed(self, val: float) -> None:
        self.current_speed = round(val, 2)
        self.status.configure(text=f"当前间隔: {self.current_speed}s")

    def _on_close(self) -> None:
        """关闭窗口: 中止输入并清理全局热键。"""
        abort_typing()
        unhook_all()
        self.destroy()


if __name__ == "__main__":
    app = App()
    app.mainloop()