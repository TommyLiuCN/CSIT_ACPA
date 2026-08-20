"""
main_gui_v5beta.py — CSIT_ACPA V5 Beta 自动输入 GUI

沿用 V4 Beta 的现代深色设计风格, 并引入 V5 的界面改进:
  1. [界面] 输出信息显示窗口不再太小 — 默认 720x600, 日志面板随窗口自由伸缩, 字体 13
  2. [美化] 应用图标 — 加载 app_icon.ico(打包时 --icon 嵌入 exe, 不再显示 Python 图标)
  3. [交互] 自由调整窗口大小 — resizable(True, True) + minsize, 控件自适应
  4. [交互] "总在最上层"开关 — 默认开启, 可随时关闭

引擎与 V4 Beta 相同: core_logic_v4(SendInput Unicode 逐字符注入)。
热键回调经 after(0, ...) 转主线程; 日志/完成回调同样经 after 转发, 状态复位由
on_done 统一处理(无竞态)。
"""

from __future__ import annotations

import os
import sys
import tkinter as tk

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


def _resource_path(name: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


_ICON_PATH = _resource_path("app_icon.ico")


class ModernCSITACPAGUI:
    def __init__(self) -> None:
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.window = ctk.CTk()
        self.window.title("CSIT_ACPA V5 Beta - by 楼sing")
        self.window.geometry("720x600")
        self.window.minsize(560, 480)
        self.window.resizable(True, True)

        self._topmost_var = tk.BooleanVar(value=True)
        if os.path.exists(_ICON_PATH):
            try:
                self.window.iconbitmap(default=_ICON_PATH)
            except tk.TclError:
                pass

        self.current_speed: float = DEFAULT_SPEED
        self._build_ui()
        self.window.attributes("-topmost", self._topmost_var.get())
        self._bind_hotkeys_safe()

    # ── UI 构建 ──────────────────────────────────────────────

    def _build_ui(self) -> None:
        # 状态显示
        status_frame = ctk.CTkFrame(self.window, fg_color="transparent")
        status_frame.pack(pady=(24, 10))

        self.status_label = ctk.CTkLabel(
            status_frame,
            text="⏸️ READY",
            font=ctk.CTkFont(size=36, weight="bold"),
            text_color="#4ADE80",
        )
        self.status_label.pack()

        self.sub_status = ctk.CTkLabel(
            status_frame,
            text="Press F8 to start typing",
            font=ctk.CTkFont(size=14),
            text_color="gray",
        )
        self.sub_status.pack(pady=(5, 0))

        # 速度滑块
        speed_frame = ctk.CTkFrame(self.window, fg_color="#2B2B2B", corner_radius=12)
        speed_frame.pack(pady=(0, 16), padx=40, fill="x")

        ctk.CTkLabel(speed_frame, text="Typing Speed", font=ctk.CTkFont(size=14)).pack(
            anchor="w", padx=15, pady=(12, 0)
        )

        slider_row = ctk.CTkFrame(speed_frame, fg_color="transparent")
        slider_row.pack(fill="x", padx=15, pady=(8, 12))

        self.speed_slider = ctk.CTkSlider(
            slider_row,
            from_=0.01,  # type: ignore
            to=0.3,  # type: ignore
            number_of_steps=29,
            command=self._update_speed_label,
        )
        self.speed_slider.set(DEFAULT_SPEED)
        self.speed_slider.pack(side="left", fill="x", expand=True)

        self.speed_value = ctk.CTkLabel(
            slider_row, text=f"{DEFAULT_SPEED:.2f}s", width=50
        )
        self.speed_value.pack(side="right", padx=(10, 0))

        # 热键提示
        hotkey_frame = ctk.CTkFrame(self.window, fg_color="#1E1E1E", corner_radius=10)
        hotkey_frame.pack(pady=(0, 12), padx=40, fill="x")

        for key, label, color in [
            ("F8", "Start / Resume Typing", "#60A5FA"),
            ("F9", "Stop Immediately", "#F87171"),
        ]:
            row = ctk.CTkFrame(hotkey_frame, fg_color="transparent")
            row.pack(
                fill="x",
                padx=15,
                pady=(10 if key == "F8" else 4, 4 if key == "F8" else 10),
            )
            ctk.CTkLabel(
                row,
                text=key,
                font=ctk.CTkFont(size=16, weight="bold"),
                text_color=color,
            ).pack(side="left")
            ctk.CTkLabel(row, text=label, font=ctk.CTkFont(size=13)).pack(
                side="left", padx=(12, 0)
            )

        # 选项栏: 置顶开关 + 清空日志
        options_frame = ctk.CTkFrame(self.window, fg_color="transparent")
        options_frame.pack(fill="x", padx=40, pady=(0, 8))

        self.topmost_switch = ctk.CTkSwitch(
            options_frame,
            text="Always On Top",
            font=ctk.CTkFont(size=13),
            variable=self._topmost_var,
            command=self._toggle_topmost,
        )
        self.topmost_switch.pack(side="left")

        ctk.CTkButton(
            options_frame, text="Clear Log", width=80, command=self._clear_log
        ).pack(side="right")

        # 日志面板(可随窗口自由伸缩)
        log_frame = ctk.CTkFrame(self.window, fg_color="#1A1A1A", corner_radius=8)
        log_frame.pack(pady=(0, 16), padx=40, fill="both", expand=True)

        self.log_textbox = ctk.CTkTextbox(
            log_frame,
            font=ctk.CTkFont(family="Consolas", size=13),
            fg_color="transparent",
        )
        self.log_textbox.pack(fill="both", expand=True, padx=8, pady=8)
        self.log_textbox.configure(state="disabled")

    # ── 置顶开关 ─────────────────────────────────────────────

    def _toggle_topmost(self) -> None:
        self.window.attributes("-topmost", self._topmost_var.get())

    # ── 速度更新 ─────────────────────────────────────────────

    def _update_speed_label(self, value: float) -> None:
        self.current_speed = round(value, 2)
        self.speed_value.configure(text=f"{self.current_speed:.2f}s")

    # ── 线程安全热键绑定 ────────────────────────────────────

    def _bind_hotkeys_safe(self) -> None:
        # keyboard 钩子回调 → after(0, ...) → 主线程执行
        bind_hotkey(lambda: self.window.after(0, self._on_start))  # type: ignore
        bind_abort_hotkey(lambda: self.window.after(0, self._on_stop))  # type: ignore

    # ── F8 触发 ──────────────────────────────────────────────

    def _on_start(self) -> None:
        def on_log(msg: str) -> None:
            self.window.after(0, lambda m=msg: self._append_log(m))

        def on_done(result: TypingResult) -> None:
            self.window.after(0, lambda r=result: self._handle_done(r))

        started = start_typing(
            speed=self.current_speed,
            on_log=on_log,
            on_done=on_done,
        )

        if started:
            self.status_label.configure(text="⌨️ TYPING...", text_color="#60A5FA")
            self.sub_status.configure(text="Press F9 to stop")
        # 若返回 False，BUSY 会通过 on_log/on_done 异步报告，无需此处处理

    # ── F9 中止 ──────────────────────────────────────────────

    def _on_stop(self) -> None:
        abort_typing()
        self._append_log("[STOPPED] User interrupted")
        # 状态复位由 on_done(ABORTED) 统一处理，避免竞态

    # ── 输入完成回调（主线程） ───────────────────────────────

    def _handle_done(self, result: TypingResult) -> None:
        status_map = {
            TypingResult.SUCCESS: ("✅ DONE", "#4ADE80", "Press F8 to start typing"),
            TypingResult.EMPTY_CLIPBOARD: (
                "⚠️ EMPTY",
                "#FBBF24",
                "Copy content first, then press F8",
            ),
            TypingResult.BUSY: (
                "⏳ BUSY",
                "#FBBF24",
                "Wait for current task to finish",
            ),
            TypingResult.ABORTED: ("⏸️ ABORTED", "#F87171", "Press F8 to restart"),
            TypingResult.ERROR: ("❌ ERROR", "#F87171", "Check log for details"),
        }
        text, color, sub = status_map.get(
            result, ("⏸️ READY", "#4ADE80", "Press F8 to start typing")
        )
        self.status_label.configure(text=text, text_color=color)
        self.sub_status.configure(text=sub)

    # ── 日志追加（线程安全） ─────────────────────────────────

    def _append_log(self, message: str) -> None:
        self.log_textbox.configure(state="normal")
        self.log_textbox.insert("end", message + "\n")
        self.log_textbox.see("end")
        self.log_textbox.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log_textbox.configure(state="normal")
        self.log_textbox.delete("1.0", "end")
        self.log_textbox.configure(state="disabled")

    # ── 生命周期 ─────────────────────────────────────────────

    def run(self) -> None:
        self.window.protocol("WM_DELETE_WINDOW", self._on_close)
        self.window.mainloop()

    def _on_close(self) -> None:
        abort_typing()
        unhook_all()
        self.window.destroy()


if __name__ == "__main__":
    app = ModernCSITACPAGUI()
    app.run()
