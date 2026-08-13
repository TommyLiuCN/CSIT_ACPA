"""
main_gui_v2.py — 改进版自动输入 GUI

改进项:
  1. 并发锁       ← 由 core_logic_v2 提供
  2. 正确返回值    ← 由 core_logic_v2 提供
  3. 批量粘贴      ← 由 core_logic_v2 提供
  4. 清理死代码
  5. 类型注解      ← 由 core_logic_v2 提供
  6. 默认速度一致
  7. 视觉反馈 + 中止热键 (F9)
"""

import customtkinter as ctk

from core_logic_v2 import abort_typing, bind_abort_hotkey, bind_hotkey, perform_typing


class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("CSIT_ACPA_V1.2 (改进版)")
        self.geometry("300x280")
        self.attributes("-topmost", True)

        # 状态变量
        self.current_speed: float = 0.05

        # ── UI 组件 ──

        self.label = ctk.CTkLabel(
            self, text="按下 F8 自动输入", font=("Arial", 16, "bold")
        )
        self.label.pack(pady=20)

        self.slider = ctk.CTkSlider(
            self,
            from_=0.01,  # type: ignore[arg-type]
            to=0.3,  # type: ignore[arg-type]
            command=self.update_speed,  # type: ignore[arg-type]
        )
        self.slider.set(self.current_speed)
        self.slider.pack(pady=10)

        self.status = ctk.CTkLabel(
            self, text=f"当前间隔: {self.current_speed}s", text_color="gray"
        )
        self.status.pack()

        # 改进 7: 状态提示行
        self.state_label = ctk.CTkLabel(self, text="就绪", text_color="green")
        self.state_label.pack(pady=5)

        # 改进 7: 快捷键提示
        self.hint_label = ctk.CTkLabel(
            self, text="F8 开始  |  F9 中止", text_color="gray", font=("Arial", 11)
        )
        self.hint_label.pack(pady=5)

        # ── 热键绑定 ──
        bind_hotkey(self.on_hotkey_pressed)
        bind_abort_hotkey(self.on_abort_pressed)

    # ── 回调 ──

    def update_speed(self, val: float) -> None:
        self.current_speed = round(val, 2)
        self.status.configure(text=f"当前间隔: {self.current_speed}s")

    def on_hotkey_pressed(self) -> None:
        """F8: 开始输入（在后台线程中执行）。"""
        # 改进 7: 通过 after(0, ...) 安全地在主线程更新 GUI
        self.after(0, self._show_typing_status)

        success = perform_typing(self.current_speed)

        if success:
            self.after(
                0,
                lambda: self.state_label.configure(
                    text="✅ 输入完成", text_color="green"
                ),
            )
        else:
            self.after(
                0,
                lambda: self.state_label.configure(
                    text="❌ 输入中止或失败", text_color="red"
                ),
            )

        # 2 秒后恢复就绪状态
        self.after(
            2000, lambda: self.state_label.configure(text="就绪", text_color="green")
        )

    def on_abort_pressed(self) -> None:
        """F9: 中止正在进行的输入。"""
        abort_typing()
        self.after(
            0,
            lambda: self.state_label.configure(
                text="⏹ 正在中止...", text_color="orange"
            ),
        )

    def _show_typing_status(self) -> None:
        self.state_label.configure(text="⏳ 输入中...", text_color="orange")


if __name__ == "__main__":
    app = App()
    app.mainloop()
