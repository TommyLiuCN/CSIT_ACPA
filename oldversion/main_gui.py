import customtkinter as ctk

from core_logic import bind_hotkey, perform_typing  # type: ignore


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("CSIT_ACPA_V1.2")
        self.geometry("300x250")
        self.attributes("-topmost", True)

        # 状态变量
        self.current_speed = 0.05

        # UI 组件
        self.label = ctk.CTkLabel(
            self, text="按下 F8 自动输入", font=("Arial", 16, "bold")
        )
        self.label.pack(pady=20)

        self.slider = ctk.CTkSlider(self, from_=0.01, to=0.3, command=self.update_speed)  # type: ignore[arg-type]
        self.slider.set(self.current_speed)
        self.slider.pack(pady=10)

        self.status = ctk.CTkLabel(
            self, text=f"当前间隔: {self.current_speed}s", text_color="gray"
        )
        self.status.pack()

        # 启动热键监听（放在后台线程以免卡死界面）
        bind_hotkey(self.on_hotkey_pressed)

    def update_speed(self, val):
        self.current_speed = round(val, 2)
        self.status.configure(text=f"当前间隔: {self.current_speed}s")

    def on_hotkey_pressed(self):
        # 收到热键信号后的操作
        success = perform_typing(self.current_speed)
        if not success:
            print("剪贴板空空如也...")


if __name__ == "__main__":
    app = App()
    app.mainloop()
    # app.mainloop()
