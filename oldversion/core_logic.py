import time

import keyboard
import pyperclip
from pynput.keyboard import Controller, Key

# 初始化键盘控制器
kb_controller = Controller()


def _is_ascii_safe(char):
    """判断字符是否可以用 pynput.type() 安全输入（ASCII 可打印字符）"""
    return char.isascii() and char.isprintable()


def _clipboard_paste_char(char):
    """通过剪贴板粘贴方式输入单个字符（适用于中文、中文标点等非ASCII字符）"""
    # 保存原始剪贴板内容
    original = pyperclip.paste()
    try:
        pyperclip.copy(char)
        time.sleep(0.02)
        # 模拟 Ctrl+V
        kb_controller.press(Key.ctrl_l)
        kb_controller.press("v")
        kb_controller.release("v")
        kb_controller.release(Key.ctrl_l)
        time.sleep(0.05)
    finally:
        # 恢复原始剪贴板内容
        time.sleep(0.02)
        pyperclip.copy(original)


def perform_typing(speed=0.1):
    """从剪贴板读取并模拟输入（混合模式：ASCII用type，非ASCII用粘贴）"""
    content = pyperclip.paste()
    if not content:
        print("剪贴板是空的！")
        return False

    # 统一换行符：Windows 剪贴板中 \r\n 会导致逐字符输入时多出换行
    content = content.replace("\r\n", "\n").replace("\r", "\n")

    for char in content:
        try:
            if char == "\n":
                # 换行符用回车键
                kb_controller.press(Key.enter)
                kb_controller.release(Key.enter)
            elif _is_ascii_safe(char):
                # ASCII 可打印字符直接用 type 输入
                kb_controller.type(char)
            else:
                # 中文、中文标点等非ASCII字符通过剪贴板粘贴
                _clipboard_paste_char(char)
            time.sleep(speed)
        except Exception as e:
            print(f"字符 {char} 输入失败: {e}")

    return True


def bind_hotkey(callback_func):
    """绑定全局热键 F8"""
    keyboard.add_hotkey("f8", callback_func)
