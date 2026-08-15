# CSIT_ACPA — 剪贴板自动打字工具

一个 Windows 剪贴板自动打字工具：按下 **F8**，把剪贴板内容逐字符"打"进当前光标所在的输入框。常用于对付禁止粘贴（`onpaste preventDefault`）的网页，以及需要在浏览器中输入中文的场景。

## 核心特性

- **F8 瞬发输入** — 按下立即开始，无延迟
- **F9 实时中止** — 输入过程中随时打断，响应粒度 ≤ 0.1s
- **中英文混输** — 逐字符注入 Unicode，中文不再依赖剪贴板粘贴
- **不受输入法影响** — V4 引擎绕过键盘布局与 IME，微软拼音/搜狗下也能正常输入
- **可调速度** — 每字符间隔 0.01~0.3s，GUI 滑块调节
- **实时日志面板** — 显示输入进度与运行日志
- **结果细分** — 完成 / 空剪贴板 / 重复触发 / 中止 / 失败 分别显示不同状态

## 快速开始

```bash
pip install -r requirements.txt
python main_gui_v4beta.py   # 现代深色主题界面（推荐）
# 或 python main_gui_v4.py  # 精简界面
```

### 使用步骤

1. 复制要输入的内容（`Ctrl+C`，浏览器里复制不受限制）
2. 把光标点进目标输入框（网页、编辑器等）
3. 按 `F8` 开始逐字输入
4. 随时按 `F9` 中止

## 版本演进

| 版本 | 文件 | 输入方式 | 说明 |
|------|------|----------|------|
| **V4**（推荐） | `core_logic_v4.py` | `SendInput` + `KEYEVENTF_UNICODE` 逐字符注入 | 绕过 IME 与禁止粘贴，中英文直接进输入框，不碰剪贴板 |
| **V4 beta GUI** | `main_gui_v4beta.py` | —（复用 V4 引擎） | 现代深色主题界面：大号状态显示、速度滑块、热键提示、日志面板 |
| **V4 GUI** | `main_gui_v4.py` | —（复用 V4 引擎） | 精简界面，其余功能与 V3 GUI 一致 |
| **V3** | `core_logic_v3.py` / `main_gui_v3.py` | ASCII 用 `pynput.type()` + 中文用剪贴板粘贴 | 工作线程修复 F9 中止失效；但中文输入法下 ASCII 会被 IME 吞掉，且网页可拦截粘贴 |
| **V2** | `core_logic_v2.py` / `main_gui_v2.py` | 同上 | 批量分段粘贴、并发锁；F9 中止实际失效（钩子线程被阻塞） |
| **V1** | `core_logic.py` / `main_gui.py` | 逐字符（ASCII `type()`，非 ASCII 逐字粘贴） | 原始版 |

## 原理

V4 用 Windows 的 `SendInput` + `KEYEVENTF_UNICODE` 标志直接注入 Unicode 字符本身：

- **不经过键盘布局**（`VkKeyScan` 虚拟键码）— 中文字符无需映射，天然支持
- **不经过 IME** — 中文输入法的合成窗口只处理扫描码/布局键，Unicode 注入事件直接生成 `WM_CHAR` 进输入框
- **不碰剪贴板** — 天然免疫网页的 `onpaste preventDefault` 拦截
- **浏览器视角真实** — 注入事件 `isTrusted=true`，页面 JS 无法与人工输入区分

这正是本工具能对付"禁止粘贴"页面的根本原因：它不依赖粘贴，而是模拟真实键盘逐字输入。

## 已知限制

- 仅支持 **Windows**（依赖 `user32.SendInput`）
- 输入速度受"每字符间隔"限制（默认 0.05s/字符），长文本耗时较长
- 全局热键依赖 `keyboard`/`pynput`，个别环境可能需要管理员权限

## 依赖

`requirements.txt`：`customtkinter`、`pyautogui`、`pyperclip`、`pynput`、`keyboard`

> 注：V4 引擎实际只用 `keyboard`（热键）和 `pyperclip`（读取剪贴板），`pynput`/`pyautogui` 为旧版本保留。

## 项目结构

```
core_logic_v4.py        # V4 引擎：SendInput Unicode 逐字符注入
main_gui_v4beta.py      # V4 beta GUI：现代深色主题（推荐入口）
main_gui_v4.py          # V4 GUI：精简界面
core_logic_v3.py        # V3 引擎：工作线程 + 剪贴板粘贴兜底
main_gui_v3.py
core_logic_v2.py        # V2 引擎：批量分段粘贴 + 并发锁
main_gui_v2.py
core_logic.py           # V1 原始引擎
main_gui.py
learning.py             # Python 练习代码（与项目无关）
CHANGELOG.md            # 版本记录
```