"""
main_gui_v5.py — CSIT_ACPA V5 自动输入 GUI

V5 相对 V4 的改进:
  1. [界面] 输出信息显示窗口不再太小
     - 默认窗口 680x560, 日志面板随窗口自由伸缩(weight 布局), 字体加大
  2. [美化] 应用图标
     - 运行窗口加载 app_icon.ico(配合 build_exe_v5.bat 打包, exe 不再显示 Python 图标)
  3. [交互] 允许自由调整窗口大小(resizable + minsize, 控件随窗口自适应)
  4. [交互] 增加"总在最上层"开关(默认开启, 可随时关闭)

保留 V4 全部能力: SendInput 引擎 / F8 瞬发 / F9 中止 / 实时日志 / 线程安全消息队列 /
状态复位令牌 / 关闭窗口清理热键。
"""

from __future__ import annotations

import os
import queue
import sys
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

# 应用图标(与打包脚本共用; 打包后从 PyInstaller 临时目录取)
def _resource_path(name: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


_ICON_PATH = _resource_path("app_icon.ico")


class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("CSIT_ACPA V5.0")
        self.geometry("680x560")
        self.minsize(480, 420)  # 允许自由调整大小, 但不至于缩成无法使用
        self.resizable(True, True)

        # 状态变量(仅在主线程读写; 钩子线程只读 speed)
        self.current_speed: float = DEFAULT_SPEED
        self._topmost_var = tk.BooleanVar(value=True)
        self._msg_queue: "queue.Queue[tuple[str, Any]]" = queue.Queue()
        self._generation: int = 0  # 状态复位令牌: 递增即作废旧复位回调

        # 窗口图标(exe 内已由 PyInstaller 嵌入; 源码运行时也从本地 ico 加载)
        if os.path.exists(_ICON_PATH):
            try:
                self.iconbitmap(default=_ICON_PATH)
            except tk.TclError:
                pass

        self._build_ui()
        self.attributes("-topmost", self._topmost_var.get())

        # 全局热键(回调在钩子线程中执行, 必须轻量)
        bind_hotkey(self._on_hotkey_f8)
        bind_abort_hotkey(self._on_hotkey_f9)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # 主线程轮询消息队列, 替代从后台线程直接调用 tkinter
        self.after(50, self._poll_queue)

    # ── UI 构建 ────────────────────────────────────────────

    def _build_ui(self) -> None:
        # 主区域允许纵向扩展, 日志面板独占剩余空间
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)

        self.label = ctk.CTkLabel(
            self, text="按下 F8 自动输入", font=("Arial", 18, "bold")
        )
        self.label.grid(row=0, column=0, padx=12, pady=(16, 8), sticky="ew")

        speed_row = ctk.CTkFrame(self, fg_color="transparent")
        speed_row.grid(row=1, column=0, padx=16, sticky="ew")
        speed_row.grid_columnconfigure(0, weight=1)

        self.slider = ctk.CTkSlider(
            speed_row, from_=0.01, to=0.3, command=self._update_speed
        )
        self.slider.set(self.current_speed)
        self.slider.grid(row=0, column=0, sticky="ew")

        self.speed_label = ctk.CTkLabel(
            speed_row, text=f"{self.current_speed:.2f}s", width=64
        )
        self.speed_label.grid(row=0, column=1, padx=(10, 0))

        self.status = ctk.CTkLabel(self, text="就绪", text_color="green")
        self.status.grid(row=2, column=0, padx=12, pady=8, sticky="ew")

        # 选项栏: 置顶开关 + 清空日志
        opts = ctk.CTkFrame(self, fg_color="transparent")
        opts.grid(row=3, column=0, padx=16, pady=(0, 6), sticky="ew")
        opts.grid_columnconfigure(0, weight=1)

        self.topmost_switch = ctk.CTkSwitch(
            opts,
            text="总在最上层",
            variable=self._topmost_var,
            command=self._toggle_topmost,
        )
        self.topmost_switch.grid(row=0, column=0, sticky="w")

        ctk.CTkButton(
            opts, text="清空日志", width=90, command=self._clear_log
        ).grid(row=0, column=1, sticky="e")

        # 日志面板
        log_frame = ctk.CTkFrame(self, fg_color="transparent")
        log_frame.grid(row=4, column=0, padx=16, pady=(0, 6), sticky="nsew")
        log_frame.grid_columnconfigure(0, weight=1)
        log_frame.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            log_frame, text="运行日志", text_color="gray", font=("Arial", 11)
        ).grid(row=0, column=0, sticky="w")

        self.log_box = ctk.CTkTextbox(
            log_frame, height=220, font=("Consolas", 12)
        )
        self.log_box.grid(row=1, column=0, sticky="nsew", pady=(2, 0))
        self.log_box.configure(state="disabled")

        # 底部快捷键提示
        ctk.CTkLabel(
            self,
            text="F8 开始  |  F9 中止",
            text_color="gray",
            font=("Arial", 11),
        ).grid(row=5, column=0, padx=12, pady=(0, 10))

    # ── 选项 ───────────────────────────────────────────────

    def _toggle_topmost(self) -> None:
        self.attributes("-topmost", self._topmost_var.get())

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
                    self.status.configure(text=text, text_color=color)
                elif kind == "log":
                    self._append_log(payload)
                elif kind == "done":
                    self._on_typing_done(payload)
        except queue.Empty:
            pass
        self.after(50, self._poll_queue)

    def _on_typing_start(self) -> None:
        self._generation += 1  # 作废未执行的旧复位回调
        self.status.configure(text="⏳ 输入中...", text_color="orange")

    def _on_typing_done(self, result: TypingResult) -> None:
        self._generation += 1
        gen = self._generation
        text, color = _RESULT_LABELS.get(result, ("ℹ️ 完成", "green"))
        self.status.configure(text=text, text_color=color)
        # 2 秒后复位; 仅当期间没有新的开始/完成时才生效
        self.after(2000, lambda g=gen: self._reset_status(g))

    def _reset_status(self, gen: int) -> None:
        if gen == self._generation:
            self.status.configure(text="就绪", text_color="green")

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
        self.speed_label.configure(text=f"{self.current_speed:.2f}s")

    def _on_close(self) -> None:
        """关闭窗口: 中止输入并清理全局热键。"""
        abort_typing()
        unhook_all()
        self.destroy()


if __name__ == "__main__":
    app = App()
    app.mainloop()
