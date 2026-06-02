import json
import queue
import re
import subprocess
import sys
import threading
from datetime import date, datetime
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

if getattr(sys, "frozen", False):
    CURRENT_DIR = Path(sys.executable).resolve().parent
else:
    CURRENT_DIR = Path(__file__).resolve().parent
if (CURRENT_DIR / "script").is_dir():
    ROOT = CURRENT_DIR
elif (CURRENT_DIR.parent / "script").is_dir():
    ROOT = CURRENT_DIR.parent
else:
    ROOT = CURRENT_DIR

SCRIPT = ROOT / "src" / "make_report.py"
ENGINE_EXE = ROOT / "src" / "make_report.exe"

GUI_SETTINGS_PATH = ROOT / "gui_settings.json"
SETTINGS_TAG = "er_fastip_gui_v1"

CE_PRESET_BOTHWIN_TFE = "bothwin_tfe"
CE_PRESET_ADMIN_TFE = "admin_tfe"
CE_PRESET_BOTHWIN_DOTX12 = "bothwin_dotx12"
CE_PRESET_CUSTOM_AAA = "custom_aaa"

CE_PRESETS: dict[str, tuple[str, str, str]] = {
    CE_PRESET_BOTHWIN_TFE: ("bothwin/Tfe", "bothwin", "Tfe28@w%"),
    CE_PRESET_ADMIN_TFE: ("admin/Tfe", "admin", "Tfe28@w%"),
    CE_PRESET_BOTHWIN_DOTX12: ("bothwin/.x12", "bothwin", ".x12Tfe192Ti.2024"),
}

PRODUCT_ER = "er"
PRODUCT_USG = "usg"

# DESIGN.md color tokens
TOKENS = {
    "primary": "#f54e00",
    "primary_active": "#d04200",
    "ink": "#26251e",
    "body": "#5a5852",
    "muted": "#807d72",
    "hairline": "#e6e5e0",
    "hairline_strong": "#cfcdc4",
    "canvas": "#f7f7f4",
    "canvas_soft": "#fafaf7",
    "surface": "#ffffff",
    "ok": "#1f8a65",
    "error": "#cf2d56",
}


def validate_gui_ce_interval_i(value: str) -> None:
    s = value.strip()
    if not re.fullmatch(r"\d+(?:\.\d+)?", s):
        raise ValueError("CE ping -i 须为数字或小数（例如 0.01）")


def validate_gui_ce_interval_m(value: str) -> None:
    s = value.strip()
    if not re.fullmatch(r"\d+", s):
        raise ValueError("CE ping -m 须为非负整数（例如 1）")


def sanitize(value: str, default: str) -> str:
    v = re.sub(r"[^A-Za-z0-9_-]", "_", value.strip())
    return v or default


def load_gui_settings() -> dict:
    if not GUI_SETTINGS_PATH.is_file():
        return {}
    try:
        data = json.loads(GUI_SETTINGS_PATH.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return {}
    if data.get("settings_tag") != SETTINGS_TAG:
        return {}
    return data


def save_gui_settings(data: dict) -> None:
    payload = {"settings_tag": SETTINGS_TAG, **data}
    GUI_SETTINGS_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("FASTIP 自动测试报告")
        self.geometry("1100x800")
        self.minsize(1000, 700)
        self.configure(bg=TOKENS["canvas"])

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.current_proc: subprocess.Popen | None = None
        self.stop_requested = False
        self._password_mode_var = tk.StringVar(value=CE_PRESET_BOTHWIN_TFE)
        self._aaa_user_var = tk.StringVar()
        self._aaa_password_var = tk.StringVar()

        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        self._setup_theme(style)
        self._build_ui()
        self._apply_ce_password_mode(silent=True)
        self._load_saved_ce_settings()
        self._sync_product_interval_ui()

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------

    def _setup_theme(self, style: ttk.Style) -> None:
        style.configure("Canvas.TFrame", background=TOKENS["canvas"])
        style.configure(
            "Card.TFrame",
            background=TOKENS["surface"],
            borderwidth=1,
            relief="solid",
        )
        style.configure(
            "CardSoft.TFrame",
            background=TOKENS["canvas_soft"],
            borderwidth=1,
            relief="solid",
        )
        style.configure(
            "LogCard.TFrame",
            background=TOKENS["canvas_soft"],
            borderwidth=1,
            relief="solid",
        )
        style.configure(
            "Header.TLabel",
            background=TOKENS["canvas"],
            foreground=TOKENS["ink"],
            font=("Microsoft YaHei UI", 22, "normal"),
        )
        style.configure(
            "SubHeader.TLabel",
            background=TOKENS["canvas"],
            foreground=TOKENS["muted"],
            font=("Microsoft YaHei UI", 11),
        )
        style.configure(
            "CardTitle.TLabel",
            background=TOKENS["surface"],
            foreground=TOKENS["ink"],
            font=("Microsoft YaHei UI", 12, "bold"),
        )
        style.configure(
            "CardSoftTitle.TLabel",
            background=TOKENS["canvas_soft"],
            foreground=TOKENS["ink"],
            font=("Microsoft YaHei UI", 11, "bold"),
        )
        style.configure(
            "Field.TLabel",
            background=TOKENS["surface"],
            foreground=TOKENS["body"],
            font=("Microsoft YaHei UI", 10),
        )
        style.configure(
            "FieldSoft.TLabel",
            background=TOKENS["canvas_soft"],
            foreground=TOKENS["body"],
            font=("Microsoft YaHei UI", 10),
        )
        style.configure(
            "Field.TEntry",
            fieldbackground=TOKENS["surface"],
            foreground=TOKENS["ink"],
            bordercolor=TOKENS["hairline_strong"],
            lightcolor=TOKENS["hairline_strong"],
            darkcolor=TOKENS["hairline_strong"],
            padding=8,
        )
        style.configure(
            "Surface.TRadiobutton",
            background=TOKENS["surface"],
            foreground=TOKENS["ink"],
            font=("Microsoft YaHei UI", 10),
        )
        style.configure(
            "Canvas.TRadiobutton",
            background=TOKENS["canvas"],
            foreground=TOKENS["ink"],
            font=("Microsoft YaHei UI", 10),
        )
        style.configure(
            "Soft.TRadiobutton",
            background=TOKENS["canvas_soft"],
            foreground=TOKENS["ink"],
            font=("Microsoft YaHei UI", 10),
        )
        style.configure(
            "Status.TLabel",
            background=TOKENS["canvas"],
            foreground=TOKENS["muted"],
            font=("Microsoft YaHei UI", 10),
        )
        style.configure(
            "Warn.TLabel",
            background=TOKENS["canvas"],
            foreground=TOKENS["error"],
            font=("Microsoft YaHei UI", 12, "bold"),
        )
        style.configure(
            "Primary.TButton",
            background=TOKENS["primary"],
            foreground="#ffffff",
            font=("Microsoft YaHei UI", 10, "bold"),
            borderwidth=0,
            padding=(20, 10),
        )
        style.map(
            "Primary.TButton",
            background=[("active", TOKENS["primary_active"])],
            foreground=[("active", "#ffffff")],
        )
        style.configure(
            "Secondary.TButton",
            background=TOKENS["surface"],
            foreground=TOKENS["ink"],
            bordercolor=TOKENS["hairline_strong"],
            borderwidth=1,
            padding=(14, 9),
        )

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=0)   # header
        self.grid_rowconfigure(1, weight=0)   # product bar
        self.grid_rowconfigure(2, weight=1)   # main form + log (expands)
        self.grid_rowconfigure(3, weight=0)   # actions

        self.vars = {
            "customer": tk.StringVar(),
            "line_id": tk.StringVar(),
            "bandwidth": tk.StringVar(),
            "engineer": tk.StringVar(),
            "test_date": tk.StringVar(value=date.today().isoformat()),
            "ce_host": tk.StringVar(),
            "ce_port": tk.StringVar(value="2707"),
            "ce_user": tk.StringVar(value="bothwin"),
            "ce_password": tk.StringVar(value="Tfe28@w%"),
            "main_ip": tk.StringVar(),
            "backup_ip": tk.StringVar(),
            "local_site": tk.StringVar(value="www.baidu.com"),
            "accel_site": tk.StringVar(value="www.google.com"),
            "ce_ping_interval_i": tk.StringVar(value="0.01"),
            "ce_ping_interval_m": tk.StringVar(value="1"),
        }

        self._build_header()
        self._build_product_bar()
        self._build_form_area()
        self._build_actions()

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------

    def _build_header(self) -> None:
        bar = ttk.Frame(self, style="Canvas.TFrame")
        bar.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 0))
        bar.grid_columnconfigure(0, weight=1)

        ttk.Label(bar, text="FASTIP 自动测试报告", style="Header.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            bar,
            text="⚠ 请补充带宽测试和主备切换截图",
            style="Warn.TLabel",
        ).grid(row=0, column=1, sticky="e", padx=(12, 0))

        ttk.Label(
            bar,
            text="执行过程和结果实时显示在下方日志区",
            style="SubHeader.TLabel",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 0))

    # ------------------------------------------------------------------
    # Product / interval bar
    # ------------------------------------------------------------------

    def _build_product_bar(self) -> None:
        bar = ttk.Frame(self, style="Canvas.TFrame")
        bar.grid(row=1, column=0, sticky="ew", padx=16, pady=(10, 8))

        self.product_var = tk.StringVar(value=PRODUCT_ER)

        ttk.Label(bar, text="产品：", style="Status.TLabel").pack(side="left")
        ttk.Radiobutton(
            bar,
            text="ER FASTIP",
            value=PRODUCT_ER,
            variable=self.product_var,
            command=self._sync_product_interval_ui,
            style="Canvas.TRadiobutton",
        ).pack(side="left", padx=(4, 12))
        ttk.Radiobutton(
            bar,
            text="USG FASTIP",
            value=PRODUCT_USG,
            variable=self.product_var,
            command=self._sync_product_interval_ui,
            style="Canvas.TRadiobutton",
        ).pack(side="left", padx=(0, 20))

        ttk.Label(bar, text="CE ping -i（ER）：", style="Status.TLabel").pack(
            side="left", padx=(0, 4)
        )
        self._ent_ce_i = ttk.Entry(
            bar, width=8, textvariable=self.vars["ce_ping_interval_i"], style="Field.TEntry"
        )
        self._ent_ce_i.pack(side="left")
        ttk.Label(bar, text="CE ping -m（USG）：", style="Status.TLabel").pack(
            side="left", padx=(14, 4)
        )
        self._ent_ce_m = ttk.Entry(
            bar, width=6, textvariable=self.vars["ce_ping_interval_m"], style="Field.TEntry"
        )
        self._ent_ce_m.pack(side="left")

    # ------------------------------------------------------------------
    # Form — two-column card layout
    # ------------------------------------------------------------------

    def _build_form_area(self) -> None:
        form = ttk.Frame(self, style="Canvas.TFrame")
        form.grid(row=2, column=0, sticky="nsew", padx=12, pady=2)
        form.grid_columnconfigure(0, weight=1, uniform="col")
        form.grid_columnconfigure(1, weight=1, uniform="col")
        form.grid_rowconfigure(0, weight=1)

        # — Left column: Customer + CE info + Password preset —
        left = ttk.Frame(form, style="Canvas.TFrame")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(0, weight=0)
        left.grid_rowconfigure(1, weight=0)
        left.grid_rowconfigure(2, weight=1)

        self._build_customer_card(left)
        self._build_ce_card(left)
        self._build_password_card(left)

        # — Right column: IP/Site info (top) + Log (bottom) —
        right = ttk.Frame(form, style="Canvas.TFrame")
        right.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(0, weight=0)
        right.grid_rowconfigure(1, weight=1)

        self._build_network_card(right)
        self._build_log_area(right)

    # ------------------------------------------------------------------
    # Card: 客户与测试信息
    # ------------------------------------------------------------------

    def _build_customer_card(self, parent: ttk.Frame) -> None:
        card = ttk.Frame(parent, style="Card.TFrame", padding=2)
        card.grid(row=0, column=0, sticky="ew", pady=(0, 4))

        ttk.Label(card, text="客户与测试信息", style="CardTitle.TLabel").pack(
            anchor="w", padx=14, pady=(12, 10)
        )

        fields = [
            ("客户名称", "customer"),
            ("CID", "line_id"),
            ("带宽", "bandwidth"),
            ("测试工程师", "engineer"),
            ("测试日期", "test_date"),
        ]
        self._render_field_rows(card, fields, "Field.TLabel", "surface")

    # ------------------------------------------------------------------
    # Card: CE 密码预设
    # ------------------------------------------------------------------

    def _build_password_card(self, parent: ttk.Frame) -> None:
        card = ttk.Frame(parent, style="CardSoft.TFrame", padding=2)
        card.grid(row=2, column=0, sticky="nsew", pady=(4, 0))
        card.grid_rowconfigure(1, weight=1)
        card.grid_columnconfigure(0, weight=1)

        ttk.Label(card, text="CE 密码预设（可选保存）", style="CardSoftTitle.TLabel").grid(
            row=0, column=0, sticky="w", padx=14, pady=(12, 8)
        )

        inner = ttk.Frame(card, style="Canvas.TFrame")
        inner.grid(row=1, column=0, sticky="new", padx=14, pady=(0, 4))

        preset_order = [
            CE_PRESET_BOTHWIN_TFE,
            CE_PRESET_ADMIN_TFE,
            CE_PRESET_BOTHWIN_DOTX12,
        ]
        ttk.Radiobutton(
            inner,
            text=CE_PRESETS[preset_order[0]][0],
            value=preset_order[0],
            variable=self._password_mode_var,
            command=self._on_ce_password_mode_change,
            style="Soft.TRadiobutton",
        ).grid(row=0, column=0, sticky="w", padx=2, pady=1)
        ttk.Radiobutton(
            inner,
            text=CE_PRESETS[preset_order[1]][0],
            value=preset_order[1],
            variable=self._password_mode_var,
            command=self._on_ce_password_mode_change,
            style="Soft.TRadiobutton",
        ).grid(row=0, column=1, sticky="w", padx=2, pady=1)
        ttk.Radiobutton(
            inner,
            text=CE_PRESETS[preset_order[2]][0],
            value=preset_order[2],
            variable=self._password_mode_var,
            command=self._on_ce_password_mode_change,
            style="Soft.TRadiobutton",
        ).grid(row=1, column=0, columnspan=2, sticky="w", padx=2, pady=1)

        ttk.Radiobutton(
            inner,
            text="aaa（自定义：在下方填写用户名和密码后点保存）",
            value=CE_PRESET_CUSTOM_AAA,
            variable=self._password_mode_var,
            command=self._on_ce_password_mode_change,
            style="Soft.TRadiobutton",
        ).grid(row=2, column=0, columnspan=2, sticky="w", padx=2, pady=(6, 0))

        ttk.Label(inner, text="aaa 用户名：", style="FieldSoft.TLabel").grid(
            row=3, column=0, sticky="w", padx=2, pady=(8, 0)
        )
        ttk.Entry(
            inner, textvariable=self._aaa_user_var, width=28, style="Field.TEntry"
        ).grid(row=3, column=1, sticky="we", padx=2, pady=(8, 0))

        ttk.Label(inner, text="aaa 密码：", style="FieldSoft.TLabel").grid(
            row=4, column=0, sticky="w", padx=2, pady=(6, 0)
        )
        ttk.Entry(
            inner, textvariable=self._aaa_password_var, width=28, show="*", style="Field.TEntry"
        ).grid(row=4, column=1, sticky="we", padx=2, pady=(6, 0))

        ttk.Button(
            inner, text="保存密码", command=self._save_ce_password_settings, style="Secondary.TButton"
        ).grid(row=5, column=0, sticky="w", padx=2, pady=(8, 4))
        inner.grid_columnconfigure(1, weight=1)

    # ------------------------------------------------------------------
    # Card: CE 连接信息
    # ------------------------------------------------------------------

    def _build_ce_card(self, parent: ttk.Frame) -> None:
        card = ttk.Frame(parent, style="Card.TFrame", padding=2)
        card.grid(row=1, column=0, sticky="ew", pady=(4, 4))

        ttk.Label(card, text="CE 连接信息", style="CardTitle.TLabel").pack(
            anchor="w", padx=14, pady=(12, 10)
        )

        fields = [
            ("CE SSH IP", "ce_host"),
            ("CE端口", "ce_port"),
            ("CE用户名", "ce_user"),
            ("CE密码", "ce_password"),
        ]
        self._render_field_rows(card, fields, "Field.TLabel", "surface", password_index=3)

    # ------------------------------------------------------------------
    # Card: IP / 站点信息
    # ------------------------------------------------------------------

    def _build_network_card(self, parent: ttk.Frame) -> None:
        card = ttk.Frame(parent, style="Card.TFrame", padding=2)
        card.grid(row=0, column=0, sticky="ew", pady=(0, 4))

        ttk.Label(card, text="IP / 站点信息", style="CardTitle.TLabel").pack(
            anchor="w", padx=14, pady=(12, 10)
        )

        fields = [
            ("主线对端IP", "main_ip"),
            ("备线IP", "backup_ip"),
            ("本地站点", "local_site"),
            ("加速站点", "accel_site"),
        ]
        self._render_field_rows(card, fields, "Field.TLabel", "surface")

    # ------------------------------------------------------------------
    # Field rows helper
    # ------------------------------------------------------------------

    def _render_field_rows(
        self,
        parent: ttk.Frame,
        fields: list[tuple[str, str]],
        label_style: str,
        bg: str,
        password_index: int | None = None,
    ) -> None:
        inner = ttk.Frame(parent, style="Canvas.TFrame")
        inner.pack(fill="x", padx=14, pady=(0, 12))
        inner.grid_columnconfigure(1, weight=1)

        for i, (label, key) in enumerate(fields):
            is_pw = password_index is not None and i == password_index
            show_char = "*" if is_pw else ""
            ttk.Label(inner, text=label, width=12, style=label_style).grid(
                row=i, column=0, sticky="e", padx=(0, 8), pady=4
            )
            ttk.Entry(
                inner, textvariable=self.vars[key], width=30, show=show_char, style="Field.TEntry"
            ).grid(row=i, column=1, sticky="we", pady=4)

    # ------------------------------------------------------------------
    # Actions bar
    # ------------------------------------------------------------------

    def _build_actions(self) -> None:
        bar = ttk.Frame(self, style="Canvas.TFrame")
        bar.grid(row=3, column=0, sticky="ew", padx=16, pady=(6, 2))
        bar.grid_columnconfigure(0, weight=1)

        btn_frame = ttk.Frame(bar, style="Canvas.TFrame")
        btn_frame.pack(side="left")

        self.run_btn = ttk.Button(
            btn_frame, text="开始生成报告", command=self.run_report, style="Primary.TButton"
        )
        self.run_btn.pack(side="left")
        self.stop_btn = ttk.Button(
            btn_frame,
            text="中断",
            command=self.stop_report,
            state="disabled",
            style="Secondary.TButton",
        )
        self.stop_btn.pack(side="left", padx=8)
        self.clear_btn = ttk.Button(
            btn_frame, text="清空日志", command=self.clear_log, style="Secondary.TButton"
        )
        self.clear_btn.pack(side="left")

        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(bar, textvariable=self.status_var, style="Status.TLabel").pack(
            side="right"
        )

    # ------------------------------------------------------------------
    # Log area — light theme, under right column
    # ------------------------------------------------------------------

    def _build_log_area(self, parent: ttk.Frame) -> None:
        card = ttk.Frame(parent, style="LogCard.TFrame", padding=2)
        card.grid(row=1, column=0, sticky="nsew", pady=(4, 0))
        card.grid_rowconfigure(1, weight=1)
        card.grid_columnconfigure(0, weight=1)

        ttk.Label(
            card, text="  执行日志", style="CardSoftTitle.TLabel"
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=14, pady=(10, 6))

        self.output = tk.Text(
            card,
            wrap="word",
            font=("JetBrains Mono", 10),
            bg=TOKENS["surface"],
            fg=TOKENS["ink"],
            insertbackground=TOKENS["ink"],
            relief="flat",
            padx=10,
            pady=6,
            borderwidth=1,
            highlightthickness=0,
            highlightbackground=TOKENS["hairline"],
            highlightcolor=TOKENS["hairline"],
        )
        self.output.grid(row=1, column=0, sticky="nsew", padx=(14, 0), pady=(0, 10))

        scroll = ttk.Scrollbar(card, orient="vertical", command=self.output.yview)
        scroll.grid(row=1, column=1, sticky="ns", padx=(0, 14), pady=(0, 10))
        self.output.configure(yscrollcommand=scroll.set)

        self.output.tag_config("ts", foreground=TOKENS["muted"])
        self.output.tag_config("ok", foreground=TOKENS["ok"])
        self.output.tag_config("warn", foreground="#b8860b")
        self.output.tag_config("err", foreground=TOKENS["error"])
        self.output.tag_config("cmd", foreground="#2563eb")

    # ------------------------------------------------------------------
    # Product / interval sync
    # ------------------------------------------------------------------

    def _sync_product_interval_ui(self) -> None:
        if self.product_var.get() == PRODUCT_ER:
            self._ent_ce_i.configure(state="normal")
            self._ent_ce_m.configure(state="disabled")
        else:
            self._ent_ce_i.configure(state="disabled")
            self._ent_ce_m.configure(state="normal")

    # ------------------------------------------------------------------
    # Password mode
    # ------------------------------------------------------------------

    def _on_ce_password_mode_change(self) -> None:
        self._apply_ce_password_mode(silent=False)

    def _apply_ce_password_mode(self, *, silent: bool) -> None:
        mode = self._password_mode_var.get()
        if mode in CE_PRESETS:
            _hint, user, pwd = CE_PRESETS[mode]
            self.vars["ce_user"].set(user)
            self.vars["ce_password"].set(pwd)
        elif mode == CE_PRESET_CUSTOM_AAA:
            custom_user = self._aaa_user_var.get().strip()
            custom_pwd = self._aaa_password_var.get().strip()
            if custom_user:
                self.vars["ce_user"].set(custom_user)
            if custom_pwd:
                self.vars["ce_password"].set(custom_pwd)
        else:
            self._password_mode_var.set(CE_PRESET_BOTHWIN_TFE)
            self._apply_ce_password_mode(silent=True)

    def _load_saved_ce_settings(self) -> None:
        data = load_gui_settings()
        mode = data.get("ce_password_mode")
        if mode not in (*CE_PRESETS.keys(), CE_PRESET_CUSTOM_AAA):
            return
        self._password_mode_var.set(mode)
        if mode == CE_PRESET_CUSTOM_AAA:
            pwd = data.get("ce_password_custom", "")
            user = data.get("ce_user_custom", "")
            if isinstance(user, str):
                self._aaa_user_var.set(user)
                if user.strip():
                    self.vars["ce_user"].set(user.strip())
            if isinstance(pwd, str):
                self._aaa_password_var.set(pwd)
                self.vars["ce_password"].set(pwd)
        else:
            self._apply_ce_password_mode(silent=True)

    def _save_ce_password_settings(self) -> None:
        mode = self._password_mode_var.get()
        if mode in CE_PRESETS:
            _hint, user, pwd = CE_PRESETS[mode]
            save_gui_settings(
                {
                    "ce_password_mode": mode,
                    "ce_user_custom": "",
                    "ce_password_custom": "",
                }
            )
            self.vars["ce_user"].set(user)
            self.vars["ce_password"].set(pwd)
            messagebox.showinfo("已保存", f"已保存预设：{CE_PRESETS[mode][0]}")
            return
        if mode == CE_PRESET_CUSTOM_AAA:
            user = (
                self._aaa_user_var.get().strip()
                or self.vars["ce_user"].get().strip()
            )
            pwd = (
                self._aaa_password_var.get().strip()
                or self.vars["ce_password"].get().strip()
            )
            if not user:
                messagebox.showerror("错误", "自定义模式下 aaa 用户名 不能为空")
                return
            if not pwd:
                messagebox.showerror("错误", "自定义模式下 CE密码 不能为空")
                return
            self._aaa_user_var.set(user)
            self._aaa_password_var.set(pwd)
            self.vars["ce_user"].set(user)
            self.vars["ce_password"].set(pwd)
            save_gui_settings(
                {
                    "ce_password_mode": CE_PRESET_CUSTOM_AAA,
                    "ce_user_custom": user,
                    "ce_password_custom": pwd,
                }
            )
            messagebox.showinfo("已保存", "已保存自定义 aaa 用户名与密码")
            return

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def _ts(self) -> str:
        return datetime.now().strftime("%H:%M:%S")

    def append(self, text: str) -> None:
        ts = self._ts()
        tag = None
        if text.startswith("[OK]") or text.startswith("[skip]"):
            tag = "ok"
        elif text.startswith("[WARN]"):
            tag = "warn"
        elif text.startswith("[ERROR]"):
            tag = "err"
        elif text.startswith(">>>") or "执行:" in text:
            tag = "cmd"

        self.output.insert("end", f"[{ts}] ", "ts")
        if tag:
            self.output.insert("end", text + "\n", tag)
        else:
            self.output.insert("end", text + "\n")
        self.output.see("end")
        self.update_idletasks()

    def clear_log(self) -> None:
        self.output.delete("1.0", "end")

    # ------------------------------------------------------------------
    # Run control
    # ------------------------------------------------------------------

    def set_running(self, running: bool) -> None:
        state = "disabled" if running else "normal"
        self.run_btn.configure(state=state)
        self.stop_btn.configure(state="normal" if running else "disabled")
        self.clear_btn.configure(state=state)
        self.status_var.set("运行中..." if running else "就绪")

    def stop_report(self) -> None:
        if self.current_proc and self.current_proc.poll() is None:
            self.stop_requested = True
            self.append("[WARN] 收到中断请求，正在终止任务...")
            try:
                self.current_proc.terminate()
                try:
                    self.current_proc.wait(timeout=2)
                except Exception:
                    self.current_proc.kill()
                if sys.platform.startswith("win"):
                    subprocess.run(
                        ["taskkill", "/PID", str(self.current_proc.pid), "/T", "/F"],
                        capture_output=True,
                        text=True, encoding="utf-8",
                    )
            except Exception:
                pass

    def run_report(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showwarning("提示", "任务正在执行中")
            return

        try:
            line_id = self.vars["line_id"].get().strip()
            ce_host = self.vars["ce_host"].get().strip()
            ce_user = self.vars["ce_user"].get().strip()
            ce_pwd = self.vars["ce_password"].get()
            main_ip = self.vars["main_ip"].get().strip()
            backup_ip = self.vars["backup_ip"].get().strip()
            if not (
                line_id and ce_host and ce_user and ce_pwd and main_ip and backup_ip
            ):
                raise ValueError(
                    "CID、CE主机、CE用户名、CE密码、主线对端IP、备线IP为必填"
                )

            date_value = self.vars["test_date"].get().strip()
            date_key = re.sub(r"[^0-9]", "", date_value)
            if not date_key:
                raise ValueError("测试日期不能为空")

            product_type = self.product_var.get().strip().lower()
            if product_type not in (PRODUCT_ER, PRODUCT_USG):
                raise ValueError("产品请选择 ER FASTIP 或 USG FASTIP")
            i_raw = self.vars["ce_ping_interval_i"].get().strip() or "0.01"
            m_raw = self.vars["ce_ping_interval_m"].get().strip() or "1"
            if product_type == PRODUCT_ER:
                validate_gui_ce_interval_i(i_raw)
            else:
                validate_gui_ce_interval_m(m_raw)

            run_dir = ROOT / "log" / f"{date_key}_{sanitize(line_id, 'NO_CID')}"
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "screenshots").mkdir(exist_ok=True)
            (run_dir / "raw").mkdir(exist_ok=True)

            cfg = {
                "customer": self.vars["customer"].get().strip(),
                "line_id": line_id,
                "bandwidth": self.vars["bandwidth"].get().strip(),
                "engineer": self.vars["engineer"].get().strip(),
                "test_date": date_value,
                "ce_host": ce_host,
                "ce_port": int(self.vars["ce_port"].get().strip() or "2707"),
                "ce_user": ce_user,
                "main_ip": main_ip,
                "backup_ip": backup_ip,
                "local_site": self.vars["local_site"].get().strip() or "www.baidu.com",
                "accel_site": self.vars["accel_site"].get().strip()
                or "www.google.com",
                "product_type": product_type,
                "ce_ping_interval_i": i_raw,
                "ce_ping_interval_m": m_raw,
            }
            (run_dir / "config.json").write_text(
                json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            (run_dir / "state.json").write_text("{}", encoding="utf-8")

            if getattr(sys, "frozen", False) and ENGINE_EXE.is_file():
                cmd = [
                    str(ENGINE_EXE),
                    "--resume",
                    str(run_dir),
                    "--ce-password",
                    ce_pwd,
                    "--no-manual-pause",
                ]
            else:
                cmd = [
                    sys.executable,
                    str(SCRIPT),
                    "--resume",
                    str(run_dir),
                    "--ce-password",
                    ce_pwd,
                    "--no-manual-pause",
                ]

            self.clear_log()
            self.append("开始执行：")
            self.append(" ".join(cmd[:-2]) + " --no-manual-pause")
            self.stop_requested = False
            self.set_running(True)

            self.worker = threading.Thread(
                target=self._run_worker, args=(cmd, run_dir, cfg), daemon=True
            )
            self.worker.start()
            self.after(100, self._poll_logs)
        except Exception as exc:
            messagebox.showerror("错误", str(exc))

    def _run_worker(self, cmd: list[str], run_dir: Path, cfg: dict) -> None:
        try:
            creationflags = 0
            if sys.platform.startswith("win"):
                creationflags = subprocess.CREATE_NO_WINDOW

            proc = subprocess.Popen(
                cmd,
                cwd=str(ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=creationflags,
            )
            self.current_proc = proc
            assert proc.stdout is not None
            for line_b in iter(proc.stdout.readline, b""):
                line = line_b.decode("utf-8", errors="replace")
                self.log_queue.put(line.rstrip("\r\n"))
            code = proc.wait()
            self.current_proc = None
            if code != 0:
                if self.stop_requested:
                    self.log_queue.put("[WARN] 任务已被中断")
                    self.log_queue.put("__DONE_ERROR__")
                    return
                self.log_queue.put(f"[ERROR] 执行失败，退出码 {code}")
                self.log_queue.put("__DONE_ERROR__")
                return

            report = (
                run_dir
                / f"FASTIP-测试报告_{cfg['customer'] or '未命名'}_{cfg['test_date']}.docx"
            )
            self.log_queue.put(f"[OK] 报告已生成: {report}")
            self.log_queue.put("__DONE_OK__")
        except Exception as exc:
            self.log_queue.put(f"[ERROR] {exc}")
            self.log_queue.put("__DONE_ERROR__")
        finally:
            self.current_proc = None

    def _poll_logs(self) -> None:
        done = None
        while True:
            try:
                item = self.log_queue.get_nowait()
            except queue.Empty:
                break
            if item == "__DONE_OK__":
                done = "ok"
            elif item == "__DONE_ERROR__":
                done = "err"
            else:
                self.append(item)

        if done:
            self.set_running(False)
            if done == "ok":
                messagebox.showinfo("完成", "报告已生成，详情见日志最后一行路径")
            else:
                messagebox.showerror("失败", "执行失败，请查看日志")
            return

        if self.worker and self.worker.is_alive():
            self.after(120, self._poll_logs)
        else:
            self.set_running(False)


if __name__ == "__main__":
    App().mainloop()
