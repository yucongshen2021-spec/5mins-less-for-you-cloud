#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tkinter 替代 stub —— 让业务模块在无 Tk/DISPLAY/Xvfb 环境下加载运行。

业务模块（er_fastip_2in1_v8 等）是原生 tkinter GUI 程序，顶层有
``root = tk.Tk()`` + ``build_net_panel()`` 创建控件并返回闭包。
app.py 用 exec() 加载这些模块，本 stub 替代真实 tkinter，使：

- ``tk.Tk()`` / ``tk.Frame()`` / ``tk.Entry()`` 等返回 mock 对象
- mock 控件的 ``.get()`` 返回 ``insert()`` 记录的值（或被 ``delete()`` 清空）
- ``StringVar`` / ``BooleanVar`` 的 ``.get()`` 返回 ``set()`` 的值
- 所有布局/状态方法（pack/grid/config/bind/...）均为 no-op
- ``__getattr__`` 兜底：任何未显式定义的方法调用都不报错

这样 builder 闭包（hk_get_raw/hk_get_net 等）能正常调用 .get() 取值，
``_apply_network_to_widgets`` 清空控件后闭包 fallback 到 globals DEFAULT_*，
与真实 tkinter 下的 web 模式行为一致。
"""

# ── 常量（业务模块用 tk.END / tk.NORMAL / tk.DISABLED / tk.TclError）────────
END = "end"
NORMAL = "normal"
DISABLED = "disabled"
LEFT = "left"
RIGHT = "right"
BOTH = "both"
X = "x"
Y = "y"
TOP = "top"
BOTTOM = "bottom"
N = "n"
S = "s"
E = "e"
W = "w"
TRUE = 1
FALSE = 0


class TclError(Exception):
    """模拟 tkinter.TclError。"""


class _MockWidget:
    """所有控件基类。布局/状态方法全 no-op，__getattr__ 兜底。"""

    def __init__(self, *args, **kwargs):
        pass

    # 布局
    def pack(self, *a, **kw): pass
    def grid(self, *a, **kw): pass
    def grid_remove(self, *a, **kw): pass
    def grid_forget(self, *a, **kw): pass
    def place(self, *a, **kw): pass
    def place_forget(self, *a, **kw): pass
    def pack_forget(self, *a, **kw): pass

    # 配置
    def config(self, *a, **kw): pass
    def configure(self, *a, **kw): pass
    def cget(self, *a, **kw): return ""
    def __getitem__(self, key): return ""
    def __setitem__(self, key, val): pass

    # 事件
    def bind(self, *a, **kw): pass
    def unbind(self, *a, **kw): pass
    def event_generate(self, *a, **kw): pass

    # 子控件
    def winfo_children(self): return []
    def winfo_exists(self): return 1
    def winfo_screenwidth(self): return 1920
    def winfo_screenheight(self): return 1080
    def winfo_width(self): return 1024
    def winfo_height(self): return 768
    def winfo_parent(self): return ""
    def nametowidget(self, name): return _MockWidget()

    # 定时器/事件循环
    def after(self, *a, **kw): return 0
    def after_cancel(self, *a): pass
    def after_idle(self, *a, **kw): return 0
    def update(self): pass
    def update_idletasks(self): pass
    def mainloop(self): pass
    def quit(self): pass
    def destroy(self): pass

    # 窗口管理
    def withdraw(self): pass
    def deiconify(self): pass
    def title(self, *a): pass
    def geometry(self, *a): pass
    def minsize(self, *a, **kw): pass
    def maxsize(self, *a, **kw): pass
    def resizable(self, *a): pass
    def iconbitmap(self, *a): pass
    def overrideredirect(self, *a): pass
    def lift(self, *a): pass
    def lower(self, *a): pass
    def focus_set(self): pass
    def focus(self): pass
    def see(self, *a): pass
    def yview(self, *a, **kw): pass
    def xview(self, *a, **kw): pass
    def yview_moveto(self, *a): pass
    def xview_moveto(self, *a): pass

    # Notebook / PanedWindow
    def add(self, *a, **kw): pass
    def remove(self, *a): pass
    def select(self, *a): pass
    def tab(self, *a, **kw): return {}
    def tabs(self): return []
    def sashpos(self, *a): return 0
    def pane(self, *a, **kw): return {}
    def insert(self, *a, **kw): pass

    # 标签/按钮
    def invoke(self): pass

    def __getattr__(self, name):
        """兜底：任何未显式定义的方法调用都返回 no-op。"""
        def _noop(*a, **kw): pass
        return _noop


class _MockEntry(_MockWidget):
    """Entry 控件。web 模式下 .get() 总返回空，强制闭包 fallback 到 globals DEFAULT_*。

    原理：业务模块的 small_entry 初始化时 e.insert(0, GK("DEFAULT_*"))，
    闭包 _pv(entry, placeholder) 比较 get()==placeholder。如果 get() 返回空，
    _pv 返回空（空 != placeholder），builder 用 GK("DEFAULT_*") 取值。
    _inject_network_to_module 改了 globals，GK 立刻读到新值 → 无串号。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def insert(self, index, text): pass  # no-op: 不记录值
    def delete(self, *args): pass
    def get(self): return ""  # 总返回空，强制 globals fallback

    def icursor(self, *a): pass
    def index(self, *a): return 0
    def selection_clear(self): pass
    def selection_range(self, *a): pass


class _MockText(_MockWidget):
    """Text 控件。web 模式下 .get() 总返回空，强制 globals fallback。

    inner_nets 等字段从 DEFAULT_INNER_NETS globals 取值。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def insert(self, index, text): pass  # no-op
    def delete(self, *args): pass
    def get(self, *args): return ""  # 总返回空

    def see(self, *a): pass
    def mark_set(self, *a): pass
    def tag_add(self, *a): pass
    def tag_config(self, *a, **kw): pass
    def tag_configure(self, *a, **kw): pass
    def tag_remove(self, *a): pass


class _MockVar:
    """StringVar / BooleanVar / IntVar / DoubleVar。记录 set 的值，get 返回。"""

    def __init__(self, *args, **kwargs):
        self._value = kwargs.get("value", "")

    def get(self):
        return self._value

    def set(self, value):
        self._value = value

    def trace_add(self, *a, **kw): pass
    def trace_remove(self, *a): pass
    def trace(self, *a, **kw): pass


class _MockCombobox(_MockWidget):
    """ttk.Combobox。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._value = ""

    def get(self):
        return self._value

    def set(self, value):
        self._value = value

    def __getitem__(self, key):
        return []

    def __setitem__(self, key, val):
        pass


class _MockTk(_MockWidget):
    """tk.Tk() 根窗口 mock。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tk = _MockTcl()

    def call(self, *a, **kw): return ""


class _MockTcl:
    """模拟 Tcl 解释器对象（root.tk）。"""

    def call(self, *a, **kw): return ""
    def eval(self, *a): return ""
    def createcommand(self, *a): pass
    def deletecommand(self, *a): pass


# ── ttk 命名空间 ────────────────────────────────────────────────────────────
class _Ttk:
    """ttk 命名空间。所有控件类返回 mock 对象。"""

    Notebook = _MockWidget
    Style = _MockWidget
    PanedWindow = _MockWidget
    Scrollbar = _MockWidget
    Combobox = _MockCombobox
    Entry = _MockEntry
    Label = _MockWidget
    Frame = _MockWidget
    Button = _MockWidget
    Checkbutton = _MockWidget
    Radiobutton = _MockWidget
    Separator = _MockWidget
    LabelFrame = _MockWidget
    Treeview = _MockWidget
    Progressbar = _MockWidget
    Notebook = _MockWidget

    @staticmethod
    def theme_use(name): pass


# ── 模块级控件工厂（用类而非函数，使 isinstance 可用）─────────────────────
class Tk(_MockTk):
    """tk.Tk() — 业务模块用 tk.Tk() 创建根窗口。"""
    pass


class Frame(_MockWidget):
    pass


class Label(_MockWidget):
    pass


class Entry(_MockEntry):
    pass


class Text(_MockText):
    pass


class Button(_MockWidget):
    pass


class Radiobutton(_MockWidget):
    pass


class Checkbutton(_MockWidget):
    pass


class Menu(_MockWidget):
    pass


class Canvas(_MockWidget):
    pass


class StringVar(_MockVar):
    """tk.StringVar — isinstance(widget, tk.StringVar) 需要类而非函数。"""
    pass


class BooleanVar(_MockVar):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not args and "value" not in kwargs:
            self._value = False


class IntVar(_MockVar):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not args and "value" not in kwargs:
            self._value = 0


class DoubleVar(_MockVar):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not args and "value" not in kwargs:
            self._value = 0.0


class PhotoImage(_MockWidget):
    pass


class Spinbox(_MockEntry):
    pass


class Listbox(_MockWidget):
    pass


class Scale(_MockWidget):
    pass


class LabelFrame(_MockWidget):
    pass


class PanedWindow(_MockWidget):
    pass


class Scrollbar(_MockWidget):
    pass


# ── messagebox / filedialog / simpledialog ──────────────────────────────────
class messagebox:
    @staticmethod
    def showwarning(*a, **kw): pass
    @staticmethod
    def showinfo(*a, **kw): pass
    @staticmethod
    def showerror(*a, **kw): pass
    @staticmethod
    def askyesno(*a, **kw): return False
    @staticmethod
    def askokcancel(*a, **kw): return True
    @staticmethod
    def askquestion(*a, **kw): return "no"
    @staticmethod
    def askretrycancel(*a, **kw): return False


class filedialog:
    @staticmethod
    def asksaveasfilename(*a, **kw): return ""
    @staticmethod
    def askopenfilename(*a, **kw): return ""
    @staticmethod
    def askdirectory(*a, **kw): return ""


class simpledialog:
    @staticmethod
    def askstring(*a, **kw): return ""
    @staticmethod
    def askinteger(*a, **kw): return None
    @staticmethod
    def askfloat(*a, **kw): return None


# ttk 实例（业务模块用 ``from tkinter import ttk``）
ttk = _Ttk
