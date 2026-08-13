"""
main_gui_v3.py — CSIT_ACPA V3 自动输入 GUI

V3 相对 V2 的改进:
  1. [关键修复] F9 中止实时生效 — 输入在 core_logic_v3 的工作线程中执行,
     热键回调只投递消息并立即返回, 不再阻塞 keyboard 钩子线程
  2. tkinter 线程安全 — 热键/工作线程通过 queue 向主线程投递消息,
     主线程 after 轮询更新 UI, 不再从后台线程直接调用 tkinter
  3. 状态复位令牌 — 修复 v2 中"2 秒复位"回调在下次输入进行中误改状态的竞态
  4. 结果细分 — 完成 / 空剪贴板 / 重复触发 / 中止 / 失败 分别显示
  5. 实时日志面板 — 显示输入进度与运行日志
  6. 可选开始倒计时(3 秒, 可 F9 取消), 防止误触 F8 把内容打进 GUI 自己
  7. 可选: 输入结束后恢复剪贴板
  8. 关闭窗口时 abort_typing() + unhook_all() 清理热键
"""

from __future__ import annotations

import queue
import tkinter as tk
from typing import Any

import customtkinter as ctk

from core_logic_v3 import (
    DEFAULT_SPEED,
    TypingResult,
    abort_typing,
    bind_abort_hotkey,
    bind_hotkey,
    start_typing,
    unhook_all,
)

COUNTDOWN_SECONDS = 3  # 开始前倒计时秒数(勾选后生效)

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
        self.title("CSIT_ACPA V3.0")
        self.geometry("420x540")
        self.attributes("-topmost", True)

        # 状态变量(仅在主线程读写; 钩子线程只读 speed/选项这些普通属性)
        self.current_speed: float = DEFAULT_SPEED
        self._msg_queue: "queue.Queue[tuple[str, Any]]" = queue.Queue()
        self._generation: int = 0  # 状态复位令牌: 递增即作废旧复位回调

        # 选项镜像(主线程更新, 钩子线程安全读取)
        self._countdown_enabled = True
        self._restore_enabled = True

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

        # 选项行
        options_row = ctk.CTkFrame(self, fg_color="transparent")
        options_row.pack(pady=4)
        self.countdown_var = tk.BooleanVar(value=True)
        self.restore_var = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            options_row,
            text=f"开始前倒计时 {COUNTDOWN_SECONDS} 秒",
            variable=self.countdown_var,
            command=self._sync_options,
        ).pack(side="left", padx=8)
        ctk.CTkCheckBox(
            options_row,
            text="结束后恢复剪贴板",
            variable=self.restore_var,
            command=self._sync_options,
        ).pack(side="left", padx=8)

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

    # ── 选项同步(主线程) ────────────────────────────────────

    def _sync_options(self) -> None:
        self._countdown_enabled = bool(self.countdown_var.get())
        self._restore_enabled = bool(self.restore_var.get())

    # ── 热键回调(在 keyboard 钩子线程中执行, 必须轻量) ───────

    def _on_hotkey_f8(self) -> None:
        """F8: 只投递消息 + 启动工作线程, 立即返回。"""
        self._msg_queue.put(("start", None))
        start_typing(
            speed=self.current_speed,
            delay=COUNTDOWN_SECONDS if self._countdown_enabled else 0.0,
            restore_clipboard=self._restore_enabled,
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
        self.state_label.configure(text="⏳ 准备中...", text_color="orange")

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
