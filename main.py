import sys
import os
import shutil
import sqlite3

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)
import datetime
import re
import webbrowser
import urllib.parse
import pandas as pd
from pathlib import Path
from contextlib import closing

APP_VERSION = "V91"
MAX_BACKUPS = 10

# matplotlib is intentionally not required: the dashboard uses native Tk Canvas charts.
import customtkinter as ctk
from tkinter import ttk, messagebox
from PIL import Image, ImageDraw, ImageFont
import arabic_reshaper
from bidi.algorithm import get_display

# Branding & Elegant Config
SHOP_NAME = "ترند سنتر الأردن"
LOCATION = "الزرقاء - جبل طارق"
PHONE = "0787779095"
CURRENCY = "د.أ"
DB_NAME = "trend_center_v57.db"  # Keep the existing database filename to preserve V57 data.

# Elegant Crimson Theme Colors
COLOR_CRIMSON = "#A52A2A"      # Main Crimson
COLOR_CRIMSON_DARK = "#800000" # Dark Crimson for Sidebar
COLOR_WHITE = "#FFFFFF"
COLOR_BG_LIGHT = "#F8F9FA"
COLOR_TEXT_DARK = "#212529"

# UI Constants - Using Arial Bold size 14 as requested
FONT_BOLD = ("Arial", 14, "bold")
FONT_NORMAL_BOLD = ("Arial", 14, "bold")
HEADER_FONT_WHITE = ("Arial", 22, "bold")

ctk.set_appearance_mode("Light")
ctk.set_default_color_theme("blue")

def fix_arabic(text, for_ui=True, is_title=False):
    if not text: return ""
    # Windows Title Bars handle Arabic correctly without reshaping/bidi
    if is_title: return str(text)
    if not any('\u0600' <= c <= '\u06FF' for c in str(text)):
        return text
    try:
        reshaped_text = arabic_reshaper.reshape(str(text))
        return get_display(reshaped_text)
    except:
        return text

def clean_float(text):
    try:
        match = re.search(r"[-+]?\d*\.\d+|\d+", str(text))
        return float(match.group()) if match else 0.0
    except: return 0.0

class Database:
    def __init__(self):
        self.db_path = Path(DB_NAME).resolve()
        self._backup_existing_database()
        self.conn = sqlite3.connect(str(self.db_path), timeout=15)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.cursor = self.conn.cursor()
        self.create_tables()

    def _backup_existing_database(self):
        """Create a safe startup copy before any schema migration or write."""
        if not self.db_path.exists() or self.db_path.stat().st_size == 0:
            return
        backup_dir = self.db_path.parent / "backups"
        backup_dir.mkdir(exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"{self.db_path.stem}_{stamp}.db"
        try:
            shutil.copy2(self.db_path, backup_path)
            backups = sorted(backup_dir.glob(f"{self.db_path.stem}_*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
            for old in backups[MAX_BACKUPS:]:
                try:
                    old.unlink()
                except OSError:
                    pass
        except OSError:
            # A backup must never prevent the POS from opening.
            pass

    def _ensure_column(self, table, column, definition):
        existing = {row[1] for row in self.cursor.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in existing:
            self.cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def create_tables(self):
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT, role TEXT)''')
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY, code TEXT UNIQUE, name TEXT, buy_price REAL, sell_price REAL, stock INTEGER, description TEXT, min_stock INTEGER DEFAULT 3)''')
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS customers (id INTEGER PRIMARY KEY, phone TEXT UNIQUE, name TEXT, points INTEGER DEFAULT 0)''')
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS customer_notes (phone TEXT PRIMARY KEY, note TEXT, updated_at TEXT)''')
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS sales (id INTEGER PRIMARY KEY, code TEXT, name TEXT, qty INTEGER, price REAL, total REAL, buy_cost REAL, date TEXT, time TEXT, user TEXT, customer_phone TEXT)''')
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS expenses (id INTEGER PRIMARY KEY, desc TEXT, amount REAL, date TEXT, time TEXT, user TEXT)''')
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS purchases (id INTEGER PRIMARY KEY, code TEXT, name TEXT, qty INTEGER, cost REAL, supplier TEXT, date TEXT, time TEXT, description TEXT)''')
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS maintenance (id INTEGER PRIMARY KEY, device_name TEXT, repair_desc TEXT, client_name TEXT, client_phone TEXT, revenue REAL, internal_cost REAL DEFAULT 0, date TEXT, time TEXT, user TEXT)''')
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS transfers (id INTEGER PRIMARY KEY, type TEXT, client_name TEXT, client_phone TEXT, amount REAL, commission REAL, reference TEXT, provider TEXT, date TEXT, time TEXT, user TEXT)''')
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS suppliers (id INTEGER PRIMARY KEY, name TEXT UNIQUE, phone TEXT, address TEXT, balance REAL DEFAULT 0, notes TEXT)''')
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS audit_logs (id INTEGER PRIMARY KEY, username TEXT, action TEXT, entity TEXT, details TEXT, date TEXT, time TEXT)''')
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')

        # Migrate databases created by V57 without discarding existing records.
        self._ensure_column("sales", "payment_method", "TEXT DEFAULT 'Cash'")
        self._ensure_column("maintenance", "payment_method", "TEXT DEFAULT 'Cash'")
        self._ensure_column("transfers", "payment_method", "TEXT DEFAULT 'Cash'")
        self._ensure_column("expenses", "user", "TEXT")
        self._ensure_column("purchases", "supplier", "TEXT")
        self._ensure_column("purchases", "description", "TEXT")
        self._ensure_column("purchases", "user", "TEXT")
        self._ensure_column("products", "min_stock", "INTEGER DEFAULT 3")

        self.cursor.execute("INSERT OR REPLACE INTO users (id, username, password, role) VALUES (1, 'admin', 'Mk@262711', 'admin')")
        self.cursor.execute("INSERT OR IGNORE INTO users (id, username, password, role) VALUES (2, 'user', '123', 'employee')")
        default_settings = [('shop_name', SHOP_NAME), ('phone', PHONE), ('location', LOCATION), ('currency', CURRENCY), ('reg_points', '20')]
        for k, v in default_settings:
            self.cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
        self.conn.commit()

    def log_action(self, username, action, entity="", details=""):
        now = datetime.datetime.now()
        self.cursor.execute("INSERT INTO audit_logs (username, action, entity, details, date, time) VALUES (?,?,?,?,?,?)", (username or "system", action, entity, details, now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S")))
        self.conn.commit()

class TrendCenterApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.db = Database()
        self.current_user = None
        self.current_role = None
        self.title(fix_arabic(SHOP_NAME, is_title=True))
        self.geometry("1350x950")
        try:
            self.state("zoomed")
        except Exception:
            pass
        try:
            icon_p = resource_path("icon.ico")
            if os.path.exists(icon_p):
                # Try multiple methods to set the icon for maximum compatibility
                self.iconbitmap(icon_p)
                self.after(500, lambda: self._set_icon_safe(icon_p))
        except Exception:
            pass

    def _set_icon_safe(self, path):
        try:
            self.iconbitmap(path)
            # Also set for taskbar grouping on Windows
            import ctypes
            myappid = 'trendcenter.pos.v91' 
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except:
            pass
        
        style = ttk.Style()
        style.theme_use("default")
        style.configure("Treeview", font=("Arial", 13, "bold"), rowheight=35, background=COLOR_WHITE)
        style.configure("Treeview.Heading", font=("Arial", 14, "bold"), background=COLOR_CRIMSON, foreground=COLOR_WHITE)
        style.map("Treeview", background=[('selected', COLOR_CRIMSON_DARK)])
        
        self.show_login()

    def clear_screen(self):
        for widget in self.winfo_children(): widget.destroy()

    def show_msg(self, title, message):
        # Fallback to native for better reliability if needed, but here we fix the custom one too
        msg_box = ctk.CTkToplevel(self)
        msg_box.title(fix_arabic(title, is_title=True))
        msg_box.geometry("450x300")
        msg_box.attributes("-topmost", True)
        msg_box.lift()
        msg_box.focus_force()
        msg_box.grab_set()
        # Disable the 'X' close button to force clicking 'OK'
        msg_box.protocol("WM_DELETE_WINDOW", lambda: None)
        
        frame = ctk.CTkFrame(msg_box, corner_radius=20, fg_color=COLOR_WHITE, border_color=COLOR_CRIMSON, border_width=2)
        frame.pack(expand=True, fill="both", padx=10, pady=10)
        ctk.CTkLabel(frame, text=fix_arabic(message, for_ui=True), font=FONT_BOLD, text_color=COLOR_TEXT_DARK, wraplength=400).pack(pady=40)
        ctk.CTkButton(frame, text=fix_arabic("موافق", for_ui=True), command=msg_box.destroy, font=FONT_BOLD, width=180, height=50, fg_color=COLOR_CRIMSON, hover_color=COLOR_CRIMSON_DARK).pack(pady=15)

    def log_action(self, action, entity="", details=""):
        try:
            self.db.log_action(self.current_user, action, entity, details)
        except sqlite3.Error:
            # Logging must not interrupt a sale or service transaction.
            pass

    def positive_number(self, value, field_name, allow_zero=False):
        try:
            number = float(str(value).strip().replace(",", "."))
        except (TypeError, ValueError):
            raise ValueError(f"{field_name} يجب أن يكون رقماً")
        if (number < 0) or (number == 0 and not allow_zero):
            raise ValueError(f"{field_name} يجب أن يكون أكبر من صفر")
        return number

    def positive_integer(self, value, field_name):
        number = self.positive_number(value, field_name)
        if int(number) != number:
            raise ValueError(f"{field_name} يجب أن يكون رقماً صحيحاً")
        return int(number)

    def date_filter(self, date_column, start, end):
        start, end = (start or "").strip(), (end or "").strip()
        if not start and not end:
            return "", []
        try:
            if start:
                datetime.datetime.strptime(start, "%Y-%m-%d")
            if end:
                datetime.datetime.strptime(end, "%Y-%m-%d")
            if start and end and start > end:
                raise ValueError("تاريخ البداية يجب أن يسبق تاريخ النهاية")
        except ValueError:
            raise ValueError("صيغة التاريخ الصحيحة هي YYYY-MM-DD")
        clauses, params = [], []
        if start:
            clauses.append(f"{date_column} >= ?"); params.append(start)
        if end:
            clauses.append(f"{date_column} <= ?"); params.append(end)
        return "WHERE " + " AND ".join(clauses), params

    def show_login(self):
        self.clear_screen()
        self.configure(fg_color="#4A0E0E") # Deep luxurious crimson background
        
        # Outer container for centering
        outer_frame = ctk.CTkFrame(self, fg_color="transparent")
        outer_frame.place(relx=0.5, rely=0.5, anchor="center")
        
        card = ctk.CTkFrame(outer_frame, width=480, height=540, corner_radius=24, fg_color=COLOR_WHITE, border_color="#E0E0E0", border_width=1)
        card.pack(padx=20, pady=20)
        card.pack_propagate(False)
        
        # Top banner inside card
        banner = ctk.CTkFrame(card, height=120, fg_color=COLOR_CRIMSON, corner_radius=20)
        banner.pack(fill="x", padx=10, pady=10)
        banner.pack_propagate(False)
        
        ctk.CTkLabel(banner, text=fix_arabic(SHOP_NAME, for_ui=True), font=("Arial", 26, "bold"), text_color=COLOR_WHITE).pack(expand=True)
        ctk.CTkLabel(card, text=fix_arabic("نظام إدارة المبيعات والمستودعات الاحترافي", for_ui=True), font=("Arial", 13, "bold"), text_color="#757575").pack(pady=(15, 25))
        
        self.u_entry = ctk.CTkEntry(card, placeholder_text=fix_arabic("اسم المستخدم", for_ui=True), width=360, height=50, font=FONT_NORMAL_BOLD, justify="right", corner_radius=12, border_color="#BDBDBD")
        self.u_entry.pack(pady=10)
        
        self.p_entry = ctk.CTkEntry(card, placeholder_text=fix_arabic("كلمة المرور", for_ui=True), show="*", width=360, height=50, font=FONT_NORMAL_BOLD, justify="right", corner_radius=12, border_color="#BDBDBD")
        self.p_entry.pack(pady=10)
        
        ctk.CTkButton(card, text=fix_arabic("تسجيل الدخول", for_ui=True), command=self.login, width=360, font=FONT_BOLD, height=50, corner_radius=12, fg_color=COLOR_CRIMSON, hover_color=COLOR_CRIMSON_DARK).pack(pady=25)

    def login(self):
        u = self.u_entry.get().strip().lower(); p = self.p_entry.get().strip()
        self.db.cursor.execute("SELECT username, role FROM users WHERE username=? AND password=?", (u, p))
        res = self.db.cursor.fetchone()
        if res:
            self.current_user, self.current_role = res
            self.log_action("تسجيل دخول", "users", f"المستخدم: {u}")
            self.show_dashboard()
        else:
            self.show_msg("خطأ", "بيانات الدخول غير صحيحة")

    def show_dashboard(self):
        self.clear_screen()
        self.configure(fg_color=COLOR_BG_LIGHT)
        
        # Sidebar container
        self.sidebar = ctk.CTkFrame(self, width=280, corner_radius=0, fg_color=COLOR_CRIMSON_DARK)
        self.sidebar.pack(side="right", fill="y")
        self.sidebar.pack_propagate(False)
        
        # Pinned top shop name
        self.db.cursor.execute("SELECT value FROM settings WHERE key='shop_name'")
        s_name = self.db.cursor.fetchone()[0]
        ctk.CTkLabel(self.sidebar, text=fix_arabic(s_name, for_ui=True), font=FONT_BOLD, text_color=COLOR_WHITE, wraplength=250).pack(pady=(30, 15))
        
        # Pinned bottom actions frame (Logout & Close)
        bottom_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        bottom_frame.pack(side="bottom", fill="x", pady=15, padx=15)
        
        if self.current_role == "employee":
            ctk.CTkButton(bottom_frame, text=fix_arabic("تغيير كلمة السر", for_ui=True), fg_color="#1565C0", hover_color="#0D47A1", command=self.change_own_password, font=FONT_BOLD, height=42, corner_radius=10).pack(fill="x", pady=5)
        ctk.CTkButton(bottom_frame, text=fix_arabic("تسجيل خروج", for_ui=True), fg_color="#f57c00", hover_color="#e64a19", command=self.show_login, font=FONT_BOLD, height=42, corner_radius=10).pack(fill="x", pady=5)
        if self.current_role == "admin":
            ctk.CTkButton(bottom_frame, text=fix_arabic("إغلاق البرنامج", for_ui=True), fg_color="#d32f2f", hover_color="#b71c1c", command=self.quit, font=FONT_BOLD, height=42, corner_radius=10).pack(fill="x", pady=5)
            
        # Scrollable middle frame for navigation buttons
        nav_scroll = ctk.CTkScrollableFrame(self.sidebar, fg_color="transparent", scrollbar_button_color=COLOR_CRIMSON)
        nav_scroll.pack(side="top", fill="both", expand=True, padx=5, pady=5)
        
        btns = [("نقطة البيع", self.ui_pos), ("قسم الصيانة", self.ui_maintenance), ("حوالات وفواتير", self.ui_transfers), ("نظام الولاء", self.ui_loyalty)]
        if self.current_role == "admin":
            btns += [("لوحة التحكم والتحليلات", self.ui_analytics), ("إدارة المخزون", self.ui_inventory), ("المشتريات", self.ui_purchases), ("الموردون والديون", self.ui_suppliers), ("إدارة العملاء", self.ui_customers), ("إدارة العمليات", self.ui_operations_management), ("التقارير المتقدمة", self.ui_advanced_reports), ("سجل الرقابة", self.ui_audit_logs), ("المصاريف", self.ui_expenses), ("التقارير والأرباح", self.ui_reports), ("إعدادات النظام", self.ui_settings)]
            
        for txt, cmd in btns:
            ctk.CTkButton(nav_scroll, text=fix_arabic(txt, for_ui=True), command=cmd, font=FONT_BOLD, height=40, corner_radius=10, fg_color="transparent", border_width=1, border_color=COLOR_WHITE, hover_color=COLOR_CRIMSON).pack(pady=4, padx=10, fill="x")
            
        # Global scrollable container for main view to fit all screen sizes (laptops, monitors, TVs)
        self.main_view_scroll = ctk.CTkScrollableFrame(self, corner_radius=20, fg_color=COLOR_WHITE, scrollbar_button_color=COLOR_CRIMSON)
        self.main_view_scroll.pack(side="left", fill="both", expand=True, padx=20, pady=20)
        self.main_view = self.main_view_scroll
        self.ui_pos()

    def change_own_password(self):
        if not self.current_user:
            return
        win = ctk.CTkToplevel(self)
        win.title(fix_arabic("تغيير كلمة السر", is_title=True))
        win.geometry("460x430")
        win.attributes("-topmost", True)
        win.grab_set()
        ctk.CTkLabel(win, text=fix_arabic("تغيير كلمة السر للمستخدم الحالي فقط", for_ui=True), font=FONT_BOLD, text_color=COLOR_CRIMSON).pack(pady=20)
        fields = {}
        for key, label in [("current", "كلمة السر الحالية"), ("new", "كلمة السر الجديدة"), ("confirm", "تأكيد كلمة السر الجديدة")]:
            ctk.CTkLabel(win, text=fix_arabic(label, for_ui=True), font=FONT_NORMAL_BOLD).pack(anchor="e", padx=30, pady=(8, 2))
            entry = ctk.CTkEntry(win, font=FONT_NORMAL_BOLD, justify="right", show="*", height=42)
            entry.pack(fill="x", padx=25)
            fields[key] = entry
        def save_password():
            current, new, confirm = (fields[k].get().strip() for k in ("current", "new", "confirm"))
            if not current or not new or not confirm:
                self.show_msg("تنبيه", "يرجى تعبئة جميع خانات كلمة السر")
                return
            if new != confirm:
                self.show_msg("خطأ", "تأكيد كلمة السر غير مطابق")
                return
            if len(new) < 3:
                self.show_msg("خطأ", "كلمة السر يجب أن تتكون من 3 رموز على الأقل")
                return
            try:
                row = self.db.cursor.execute("SELECT password FROM users WHERE username=?", (self.current_user,)).fetchone()
                if not row or row[0] != current:
                    self.show_msg("خطأ", "كلمة السر الحالية غير صحيحة")
                    return
                self.db.cursor.execute("UPDATE users SET password=? WHERE username=?", (new, self.current_user))
                self.db.conn.commit()
                self.log_action("تغيير كلمة السر", "users", f"المستخدم: {self.current_user}")
                win.destroy()
                self.show_msg("نجاح", "تم تغيير كلمة السر الخاصة بك فقط بنجاح")
            except sqlite3.Error as exc:
                self.db.conn.rollback()
                self.show_msg("تعذر تغيير كلمة السر", str(exc))
        ctk.CTkButton(win, text=fix_arabic("حفظ كلمة السر", for_ui=True), command=save_password, font=FONT_BOLD, fg_color=COLOR_CRIMSON, height=45).pack(fill="x", padx=25, pady=25)

    def create_header(self, text):
        header = ctk.CTkFrame(self.main_view, height=65, fg_color=COLOR_CRIMSON, corner_radius=16)
        header.pack(fill="x", padx=15, pady=(0, 15))
        header.pack_propagate(False)
        ctk.CTkLabel(header, text=fix_arabic(text, for_ui=True), font=("Arial", 22, "bold"), text_color=COLOR_WHITE).pack(expand=True)

    def lookup_customer_name(self, phone_entry, name_entry):
        phone = str(phone_entry.get()).strip()
        phone_entry.configure(border_color="#BDBDBD", border_width=1)
        
        if not phone or len(phone) < 3:
            self._last_alert_phone = None
            return

        # Smart Phone Normalization: Check both with and without leading zero
        p_alt = phone[1:] if phone.startswith('0') else '0' + phone
        
        self.db.cursor.execute("SELECT name FROM customers WHERE phone=? OR phone=?", (phone, p_alt))
        res = self.db.cursor.fetchone()
        if res:
            name_entry.delete(0, 'end')
            name_entry.insert(0, res[0])
            
            # Check for note using the same smart normalization
            self.db.cursor.execute("SELECT note FROM customer_notes WHERE phone=? OR phone=?", (phone, p_alt))
            note_res = self.db.cursor.fetchone()
            if note_res and note_res[0]:
                phone_entry.configure(border_color="#FF0000", border_width=2)
                # Trigger alert immediately for the matched phone
                self.check_customer_note(phone)
        else:
            self._last_alert_phone = None

    def check_customer_note(self, phone):
        ph = str(phone).strip()
        if not ph: return
        
        # Prevent showing the same alert multiple times for the same interaction
        if hasattr(self, "_last_alert_phone") and self._last_alert_phone == ph:
            return
            
        try:
            # Use smart normalization in check as well
            p_alt = ph[1:] if ph.startswith('0') else '0' + ph
            self.db.cursor.execute("SELECT note FROM customer_notes WHERE phone=? OR phone=?", (ph, p_alt))
            res = self.db.cursor.fetchone()
            if res and res[0]:
                self._last_alert_phone = ph
                note_content = res[0]
                # Aggressive alert: Native Windows MessageBox
                # For native Windows dialogs, we pass raw strings as Windows handles RTL/Arabic correctly.
                messagebox.showwarning(
                    str("تنبيه ملاحظة العميل"),
                    str(f"تنبيه مهم بخصوص العميل ({ph}):\n\n{note_content}")
                )
        except Exception:
            pass

    def ui_pos(self):
        for w in self.main_view.winfo_children(): w.destroy()
        self.create_header("نقطة البيع")
        
        # Row 1: Customer details
        top = ctk.CTkFrame(self.main_view, fg_color="transparent"); top.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(top, text=fix_arabic("هاتف العميل:", for_ui=True), font=FONT_BOLD, text_color=COLOR_CRIMSON).pack(side="right", padx=5)
        self.pos_cust_phone = ctk.CTkEntry(top, font=FONT_NORMAL_BOLD, width=150, justify="right", corner_radius=8); self.pos_cust_phone.pack(side="right", padx=5)
        self.pos_cust_phone.bind("<KeyRelease>", lambda e: self.lookup_customer_name(self.pos_cust_phone, self.pos_cust_name))
        ctk.CTkLabel(top, text=fix_arabic("الاسم:", for_ui=True), font=FONT_BOLD, text_color=COLOR_CRIMSON).pack(side="right", padx=5)
        self.pos_cust_name = ctk.CTkEntry(top, font=FONT_NORMAL_BOLD, width=150, justify="right", corner_radius=8); self.pos_cust_name.pack(side="right", padx=5)
        ctk.CTkLabel(top, text=fix_arabic("الدفع:", for_ui=True), font=FONT_BOLD, text_color=COLOR_CRIMSON).pack(side="right", padx=5)
        self.payment_method = ctk.CTkComboBox(top, values=["Cash", "Visa", "CLIQ"], width=100, height=38, font=FONT_NORMAL_BOLD, justify="center")
        self.payment_method.pack(side="right", padx=5); self.payment_method.set("Cash")
        
        # Row 2: Barcode and Search by Name
        top2 = ctk.CTkFrame(self.main_view, fg_color="transparent"); top2.pack(fill="x", padx=10, pady=5)
        ctk.CTkButton(top2, text=fix_arabic("بحث بالاسم", for_ui=True), command=self.open_product_search_window, font=FONT_BOLD, width=110, fg_color="#1565C0", hover_color="#0D47A1", height=40).pack(side="right", padx=5)
        ctk.CTkLabel(top2, text=fix_arabic("الباركود:", for_ui=True), font=FONT_BOLD, text_color=COLOR_CRIMSON).pack(side="right", padx=5)
        self.code_entry = ctk.CTkEntry(top2, font=FONT_NORMAL_BOLD, width=220, height=40, justify="right", corner_radius=8); self.code_entry.pack(side="right", padx=5)
        self.code_entry.bind("<Return>", lambda e: self.add_to_cart())
        self.code_entry.focus_set()
        ctk.CTkButton(top2, text=fix_arabic("إضافة", for_ui=True), command=self.add_to_cart, font=FONT_BOLD, width=90, height=40, fg_color=COLOR_CRIMSON, hover_color=COLOR_CRIMSON_DARK).pack(side="right", padx=5)

        self.cart_tree = ttk.Treeview(self.main_view, columns=("total", "price", "qty", "name", "code"), show="headings")
        for col, head in zip(self.cart_tree["columns"], ["الإجمالي", "السعر", "الكمية", "الاسم", "الكود"]): self.cart_tree.heading(col, text=fix_arabic(head, for_ui=True))
        self.cart_tree.pack(fill="both", expand=True, padx=15, pady=10)
        
        act_btns = ctk.CTkFrame(self.main_view, fg_color="transparent")
        act_btns.pack(fill="x", padx=15, pady=5)
        ctk.CTkButton(act_btns, text=fix_arabic("خصم / تعديل السعر", for_ui=True), command=self.show_discount_ui, font=FONT_BOLD, fg_color="#f57c00", hover_color="#e64a19", height=40).pack(side="right", padx=5)
        ctk.CTkButton(act_btns, text=fix_arabic("حذف من السلة", for_ui=True), command=self.remove_from_cart, font=FONT_BOLD, fg_color="#d32f2f", hover_color="#b71c1c", height=40).pack(side="right", padx=5)

        bottom = ctk.CTkFrame(self.main_view, fg_color="transparent"); bottom.pack(fill="x", padx=20, pady=20)
        self.total_lbl = ctk.CTkLabel(bottom, text=fix_arabic(f"المجموع: 0.00 {CURRENCY}", for_ui=True), font=("Arial", 24, "bold"), text_color=COLOR_CRIMSON_DARK); self.total_lbl.pack(side="right")
        ctk.CTkButton(bottom, text=fix_arabic("إتمام العملية + فاتورة", for_ui=True), fg_color="#2e7d32", hover_color="#1b5e20", command=self.checkout, font=FONT_BOLD, height=60, width=250, corner_radius=12).pack(side="left")
        self.cart = []

    def open_product_search_window(self):
        sw = ctk.CTkToplevel(self)
        sw.title(fix_arabic("البحث عن منتج بالاسم", is_title=True))
        sw.geometry("600x450")
        sw.attributes("-topmost", True)
        sw.grab_set()
        
        f_search = ctk.CTkFrame(sw, fg_color="transparent")
        f_search.pack(fill="x", padx=15, pady=15)
        
        s_entry = ctk.CTkEntry(f_search, placeholder_text=fix_arabic("اكتب جزءاً من اسم المنتج...", for_ui=True), width=400, height=45, font=FONT_NORMAL_BOLD, justify="right")
        s_entry.pack(side="right", padx=5)
        s_entry.focus_set()
        
        # Results tree
        tree = ttk.Treeview(sw, columns=("stock", "price", "name", "code"), show="headings")
        for col, head in zip(tree["columns"], ["الكمية", "السعر", "اسم المنتج", "الكود"]):
            tree.heading(col, text=fix_arabic(head, for_ui=True))
        tree.pack(fill="both", expand=True, padx=15, pady=10)
        
        def run_search(event=None):
            for i in tree.get_children(): tree.delete(i)
            q = s_entry.get().strip()
            self.db.cursor.execute("SELECT code, name, sell_price, stock FROM products WHERE name LIKE ?", (f"%{q}%",))
            for r in self.db.cursor.fetchall():
                tree.insert("", "end", values=(r[3], f"{r[2]:.2f}", fix_arabic(r[1], for_ui=True), r[0]))
                
        s_entry.bind("<KeyRelease>", run_search)
        run_search() # load all initially
        
        def select_product(event=None):
            selected = tree.selection()
            if not selected: return
            vals = tree.item(selected[0])['values']
            code = vals[3]
            sw.destroy()
            self.code_entry.delete(0, 'end')
            self.code_entry.insert(0, str(code))
            self.add_to_cart()
            
        tree.bind("<Double-1>", select_product)
        ctk.CTkButton(sw, text=fix_arabic("إضافة للسلة", for_ui=True), command=select_product, font=FONT_BOLD, fg_color="#2e7d32", height=45, width=200).pack(pady=15)

    def add_to_cart(self):
        code = self.code_entry.get().strip()
        if not code:
            return
        self.db.cursor.execute("SELECT code, name, sell_price, buy_price, stock FROM products WHERE code=?", (code,))
        p = self.db.cursor.fetchone()
        if p:
            already = sum(item["qty"] for item in self.cart if item["code"] == p[0])
            if p[4] <= already:
                self.show_msg("تنبيه", "الكمية المطلوبة تتجاوز المخزون المتوفر")
                return
            self.cart.append({"code": p[0], "name": p[1], "price": float(p[2] or 0), "buy_cost": float(p[3] or 0), "qty": 1, "total": float(p[2] or 0)})
            self.refresh_cart(); self.code_entry.delete(0, "end"); self.code_entry.focus_set()
        else:
            self.show_msg("خطأ", "باركود المنتج غير موجود")

    def refresh_cart(self):
        for i in self.cart_tree.get_children(): self.cart_tree.delete(i)
        total = sum(item['total'] for item in self.cart)
        for item in self.cart: self.cart_tree.insert("", "end", values=(f"{item['total']:.2f}", f"{item['price']:.2f}", item['qty'], fix_arabic(item['name'], for_ui=True), item['code']))
        self.total_lbl.configure(text=fix_arabic(f"المجموع: {total:.2f} {CURRENCY}", for_ui=True))

    def remove_from_cart(self):
        selected = self.cart_tree.selection()
        if not selected: return
        idx = self.cart_tree.index(selected[0])
        self.cart.pop(idx); self.refresh_cart()

    def show_discount_ui(self):
        selected = self.cart_tree.selection()
        if not selected: return
        idx = self.cart_tree.index(selected[0])
        item = self.cart[idx]
        ds = ctk.CTkToplevel(self); ds.title(fix_arabic("تعديل السعر / خصم", is_title=True)); ds.geometry("400x300"); ds.attributes("-topmost", True); ds.grab_set()
        ctk.CTkLabel(ds, text=fix_arabic(f"تعديل سعر: {item['name']}", for_ui=True), font=FONT_BOLD, text_color=COLOR_CRIMSON).pack(pady=20)
        price_entry = ctk.CTkEntry(ds, placeholder_text=fix_arabic("السعر الجديد", for_ui=True), font=FONT_NORMAL_BOLD, justify="center", height=45); price_entry.pack(pady=10, padx=40, fill="x")
        price_entry.insert(0, str(item['price']))
        def apply():
            new_p = clean_float(price_entry.get())
            if new_p >= 0:
                self.cart[idx]['price'] = new_p
                self.cart[idx]['total'] = new_p * self.cart[idx]['qty']
                self.refresh_cart(); ds.destroy()
        ctk.CTkButton(ds, text=fix_arabic("تطبيق السعر", for_ui=True), command=apply, font=FONT_BOLD, fg_color="#f57c00", height=45).pack(pady=20)

    def get_or_create_customer(self, phone, name="عميل جديد"):
        if not phone:
            return None
        self.db.cursor.execute("SELECT phone, points, name FROM customers WHERE phone=?", (phone,))
        res = self.db.cursor.fetchone()
        if res:
            if name != "عميل جديد" and res[2] != name:
                self.db.cursor.execute("UPDATE customers SET name=? WHERE phone=?", (name, phone))
            return res
        self.db.cursor.execute("SELECT value FROM settings WHERE key='reg_points'")
        reg_points = int(clean_float(self.db.cursor.fetchone()[0] or 20))
        self.db.cursor.execute("INSERT INTO customers (phone, name, points) VALUES (?,?,?)", (phone, name, reg_points))
        self.show_msg("عميل جديد", f"تم تسجيل العميل بنجاح!\nتم منح العميل {reg_points} نقطة هدية مجانية.")
        return (phone, reg_points, name)

    def checkout(self):
        if not self.cart:
            self.show_msg("تنبيه", "السلة فارغة")
            return
        phone = self.pos_cust_phone.get().strip()
        name = self.pos_cust_name.get().strip() or "عميل جديد"
        payment = self.payment_method.get() if hasattr(self, "payment_method") else fix_arabic("نقدي", for_ui=True)
        total = sum(float(i["total"]) for i in self.cart)
        now = datetime.datetime.now()
        try:
            # Re-check stock at commit time, protecting against stale screens.
            for item in self.cart:
                row = self.db.cursor.execute("SELECT stock FROM products WHERE code=?", (item["code"],)).fetchone()
                if not row or int(row[0]) < int(item["qty"]):
                    raise ValueError(f"المخزون غير كافٍ للمنتج: {item['name']}")
            customer = self.get_or_create_customer(phone, name) if phone else None
            for item in self.cart:
                self.db.cursor.execute("UPDATE products SET stock = stock - ? WHERE code=?", (item["qty"], item["code"]))
                self.db.cursor.execute("INSERT INTO sales (code, name, qty, price, total, buy_cost, date, time, user, customer_phone, payment_method) VALUES (?,?,?,?,?,?,?,?,?,?,?)", 
                                       (item["code"], item["name"], item["qty"], item["price"], item["total"], item["buy_cost"] * item["qty"], now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"), self.current_user, phone, payment))
            points_earned = int(total * 10) if customer else 0
            if customer and points_earned:
                self.db.cursor.execute("UPDATE customers SET points = points + ? WHERE phone=?", (points_earned, phone))
            self.db.conn.commit()
            self.log_action("بيع", "sales", f"المبلغ: {total:.2f}; الدفع: {payment}; العميل: {phone or 'نقدي'}")
            self.generate_invoice(total, "SALE", {"points": points_earned, "phone": phone, "client": name, "payment": payment})
            self.cart = []; self.refresh_cart(); self.code_entry.focus_set()
        except (ValueError, sqlite3.Error) as exc:
            self.db.conn.rollback()
            self.show_msg("تعذر إتمام البيع", str(exc))

    def ui_maintenance(self):
        for w in self.main_view.winfo_children(): w.destroy()
        self.create_header("قسم الصيانة")
        f1 = ctk.CTkFrame(self.main_view, fg_color="transparent"); f1.pack(fill="x", padx=15, pady=5)
        self.m_phone = ctk.CTkEntry(f1, placeholder_text=fix_arabic("رقم الهاتف", for_ui=True), height=45, font=FONT_NORMAL_BOLD, justify="right", corner_radius=10); self.m_phone.pack(side="right", padx=5)
        self.m_phone.bind("<KeyRelease>", lambda e: self.lookup_customer_name(self.m_phone, self.m_client))
        self.m_client = ctk.CTkEntry(f1, placeholder_text=fix_arabic("اسم العميل", for_ui=True), height=45, font=FONT_NORMAL_BOLD, justify="right", corner_radius=10); self.m_client.pack(side="right", padx=5, expand=True, fill="x")
        self.m_device = ctk.CTkEntry(f1, placeholder_text=fix_arabic("الجهاز", for_ui=True), height=45, font=FONT_NORMAL_BOLD, justify="right", corner_radius=10); self.m_device.pack(side="right", padx=5)
        f2 = ctk.CTkFrame(self.main_view, fg_color="transparent"); f2.pack(fill="x", padx=15, pady=5)
        self.m_desc = ctk.CTkEntry(f2, placeholder_text=fix_arabic("وصف الإصلاح", for_ui=True), height=45, font=FONT_NORMAL_BOLD, justify="right", corner_radius=10); self.m_desc.pack(side="right", padx=5, expand=True, fill="x")
        self.m_rev = ctk.CTkEntry(f2, placeholder_text=fix_arabic("المبلغ", for_ui=True), height=45, font=FONT_NORMAL_BOLD, width=120, justify="right", corner_radius=10); self.m_rev.pack(side="right", padx=5)
        ctk.CTkLabel(f2, text=fix_arabic("الدفع:", for_ui=True), font=FONT_BOLD, text_color=COLOR_CRIMSON).pack(side="right", padx=5)
        self.m_pay = ctk.CTkComboBox(f2, values=["Cash", "Visa", "CLIQ"], width=100, height=45, font=FONT_NORMAL_BOLD, justify="center")
        self.m_pay.pack(side="right", padx=5); self.m_pay.set("Cash")
        ctk.CTkButton(f2, text=fix_arabic("تسجيل صيانة + فاتورة", for_ui=True), fg_color=COLOR_CRIMSON, hover_color=COLOR_CRIMSON_DARK, command=self.add_maintenance, font=FONT_BOLD, height=45, corner_radius=10).pack(side="right", padx=5)
        admin_f = ctk.CTkFrame(self.main_view, fg_color="#E3F2FD", corner_radius=10); admin_f.pack(fill="x", padx=15, pady=5)
        if self.current_role == "admin":
            ctk.CTkButton(admin_f, text=fix_arabic("حذف", for_ui=True), command=lambda: self.delete_record("maintenance", self.m_tree), font=FONT_BOLD, width=100, fg_color="#c62828").pack(side="left", padx=5)
            ctk.CTkButton(admin_f, text=fix_arabic("تعديل", for_ui=True), command=lambda: self.edit_record_ui("maintenance", self.m_tree), font=FONT_BOLD, width=100, fg_color="#1565C0").pack(side="left", padx=5)
        ctk.CTkLabel(admin_f, text=fix_arabic("تكلفة القطع:", for_ui=True), font=FONT_BOLD, text_color=COLOR_CRIMSON_DARK).pack(side="right", padx=10)
        self.m_id_sel = ctk.CTkEntry(admin_f, placeholder_text="ID", width=60, justify="center"); self.m_id_sel.pack(side="right", padx=5)
        self.m_cost_in = ctk.CTkEntry(admin_f, placeholder_text=fix_arabic("المبلغ", for_ui=True), width=100, justify="right"); self.m_cost_in.pack(side="right", padx=5)
        ctk.CTkButton(admin_f, text=fix_arabic("تحديث", for_ui=True), command=self.update_m_cost, font=FONT_BOLD, width=100, fg_color=COLOR_CRIMSON_DARK).pack(side="right", padx=10)
        self.m_tree = ttk.Treeview(self.main_view, columns=("cost", "revenue", "desc", "phone", "client", "id"), show="headings")
        for col, head in zip(self.m_tree["columns"], ["تكلفة القطع", "المبلغ", "الوصف", "الهاتف", "العميل", "ID"]): self.m_tree.heading(col, text=fix_arabic(head, for_ui=True))
        self.m_tree.pack(fill="both", expand=True, padx=15, pady=10)
        self.refresh_maintenance_tree()

    def refresh_maintenance_tree(self):
        for i in self.m_tree.get_children(): self.m_tree.delete(i)
        self.db.cursor.execute("SELECT internal_cost, revenue, repair_desc, client_phone, client_name, id FROM maintenance ORDER BY id DESC")
        [self.m_tree.insert("", "end", values=(r[0], r[1], fix_arabic(r[2], for_ui=True), r[3], fix_arabic(r[4], for_ui=True), r[5])) for r in self.db.cursor.fetchall()]

    def update_m_cost(self):
        m_id, cost = self.m_id_sel.get(), self.m_cost_in.get()
        if m_id and cost:
            self.db.cursor.execute("UPDATE maintenance SET internal_cost = ? WHERE id = ?", (float(cost), int(m_id)))
            self.db.conn.commit(); self.show_msg("نجاح", "تم تحديث التكلفة"); self.refresh_maintenance_tree()

    def add_maintenance(self):
        c, ph, d, ds, r_raw = self.m_client.get().strip(), self.m_phone.get().strip(), self.m_device.get().strip(), self.m_desc.get().strip(), self.m_rev.get().strip()
        payment = self.m_pay.get()
        if not all([c, ph, d, ds, r_raw]):
            self.show_msg("تنبيه", "يرجى تعبئة اسم العميل والهاتف والجهاز ووصف الإصلاح والمبلغ")
            return
        try:
            rev = self.positive_number(r_raw, "مبلغ الصيانة")
            now = datetime.datetime.now()
            self.get_or_create_customer(ph, c)
            points_earned = 5
            if ph:
                self.db.cursor.execute("UPDATE customers SET points = points + ? WHERE phone=?", (points_earned, ph))
            self.db.cursor.execute("INSERT INTO maintenance (device_name, repair_desc, client_name, client_phone, revenue, payment_method, date, time, user) VALUES (?,?,?,?,?,?,?,?,?)", (d, ds, c, ph, rev, payment, now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"), self.current_user))
            self.db.conn.commit()
            self.log_action("تسجيل صيانة", "maintenance", f"العميل: {c}; المبلغ: {rev:.2f}; الدفع: {payment}")
            self.generate_invoice(rev, "MAINTENANCE", {"client": c, "device": d, "desc": ds, "phone": ph, "points": points_earned, "payment": payment})
            self.ui_maintenance()
        except (ValueError, sqlite3.Error) as exc:
            self.db.conn.rollback(); self.show_msg("تعذر تسجيل الصيانة", str(exc))

    def ui_transfers(self):
        for w in self.main_view.winfo_children(): w.destroy()
        self.create_header("الحوالات والفواتير")
        f = ctk.CTkFrame(self.main_view, fg_color="transparent"); f.pack(fill="x", padx=15, pady=5)
        self.t_type_raws = ["خروج حوالة", "دخول حوالة", "دفع فاتورة"]
        self.t_type = ctk.CTkOptionMenu(f, values=[fix_arabic(x, for_ui=True) for x in self.t_type_raws], font=FONT_BOLD, width=180, fg_color=COLOR_CRIMSON); self.t_type.pack(side="right", padx=5)
        self.t_phone = ctk.CTkEntry(f, placeholder_text=fix_arabic("الهاتف", for_ui=True), height=40, justify="right"); self.t_phone.pack(side="right", padx=5)
        self.t_phone.bind("<KeyRelease>", lambda e: self.lookup_customer_name(self.t_phone, self.t_client))
        self.t_client = ctk.CTkEntry(f, placeholder_text=fix_arabic("اسم العميل (الاسم الأول ثم العائلة)", for_ui=True), height=40, justify="right", font=FONT_NORMAL_BOLD); self.t_client.pack(side="right", padx=5, expand=True, fill="x")
        f2 = ctk.CTkFrame(self.main_view, fg_color="transparent"); f2.pack(fill="x", padx=15, pady=5)
        self.t_amt = ctk.CTkEntry(f2, placeholder_text=fix_arabic("القيمة", for_ui=True), height=40, justify="right"); self.t_amt.pack(side="right", padx=5)
        self.t_amt.bind("<KeyRelease>", self.calc_commission)
        self.t_comm = ctk.CTkEntry(f2, placeholder_text=fix_arabic("العمولة", for_ui=True), width=100, height=40, justify="right"); self.t_comm.pack(side="right", padx=5)
        self.t_ref = ctk.CTkEntry(f2, placeholder_text=fix_arabic("المرجع", for_ui=True), height=40, justify="right"); self.t_ref.pack(side="right", padx=5)
        ctk.CTkLabel(f2, text=fix_arabic("الدفع:", for_ui=True), font=FONT_BOLD, text_color=COLOR_CRIMSON).pack(side="right", padx=5)
        self.t_pay = ctk.CTkComboBox(f2, values=["Cash", "Visa", "CLIQ"], width=90, height=38, font=FONT_NORMAL_BOLD, justify="center")
        self.t_pay.pack(side="right", padx=5); self.t_pay.set("Cash")
        ctk.CTkButton(f2, text=fix_arabic("تسجيل + فاتورة", for_ui=True), fg_color="#2e7d32", command=self.add_transfer, font=FONT_BOLD, height=40).pack(side="right", padx=5)
        if self.current_role == "admin":
            ctk.CTkButton(f2, text=fix_arabic("حذف", for_ui=True), command=lambda: self.delete_record("transfers", self.t_tree), font=FONT_BOLD, height=40, fg_color="#c62828").pack(side="left", padx=5)
            ctk.CTkButton(f2, text=fix_arabic("تعديل", for_ui=True), command=lambda: self.edit_record_ui("transfers", self.t_tree), font=FONT_BOLD, height=40, fg_color="#1565C0").pack(side="left", padx=5)
        self.t_tree = ttk.Treeview(self.main_view, columns=("comm", "amt", "ref", "client", "type", "id"), show="headings")
        for col, head in zip(self.t_tree["columns"], ["العمولة", "المبلغ", "المرجع", "العميل", "النوع", "ID"]): self.t_tree.heading(col, text=fix_arabic(head, for_ui=True))
        self.t_tree.pack(fill="both", expand=True, padx=15, pady=10)
        self.refresh_transfers_tree()

    def refresh_transfers_tree(self):
        for i in self.t_tree.get_children(): self.t_tree.delete(i)
        self.db.cursor.execute("SELECT commission, amount, reference, client_name, type, id FROM transfers ORDER BY id DESC")
        [self.t_tree.insert("", "end", values=(r[0], r[1], r[2], fix_arabic(r[3], for_ui=True), fix_arabic(r[4], for_ui=True), r[5])) for r in self.db.cursor.fetchall()]

    def calc_commission(self, event=None):
        try:
            amt = clean_float(self.t_amt.get())
            comm = 0.5 if amt < 50 else (1.0 if amt <= 100 else 1.5)
            self.t_comm.delete(0, 'end'); self.t_comm.insert(0, str(comm))
        except: pass

    def add_transfer(self):
        t_ui = self.t_type.get()
        t = next((raw for raw in self.t_type_raws if fix_arabic(raw, for_ui=True) == t_ui), "خروج حوالة")
        c, ph, a_raw, cm_raw, r = self.t_client.get().strip(), self.t_phone.get().strip(), self.t_amt.get().strip(), self.t_comm.get().strip(), self.t_ref.get().strip()
        payment = self.t_pay.get()
        if not c or not a_raw:
            self.show_msg("تنبيه", "يرجى إدخال اسم العميل وقيمة العملية")
            return
        try:
            amt = self.positive_number(a_raw, "قيمة العملية")
            comm = self.positive_number(cm_raw, "العمولة", allow_zero=True)
            now = datetime.datetime.now()
            self.get_or_create_customer(ph, c)
            points_earned = 2
            if ph:
                self.db.cursor.execute("UPDATE customers SET points = points + ? WHERE phone=?", (points_earned, ph))
            self.db.cursor.execute("INSERT INTO transfers (type, client_name, client_phone, amount, commission, reference, payment_method, date, time, user) VALUES (?,?,?,?,?,?,?,?,?,?)", (t, c, ph, amt, comm, r, payment, now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"), self.current_user))
            self.db.conn.commit()
            self.log_action("تسجيل حوالة/فاتورة", "transfers", f"النوع: {t}; المبلغ: {amt:.2f}; العميل: {c}; الدفع: {payment}")
            
            # User rules for transfer invoice totals:
            # - دخول حوالة (Receive to Send): Invoice type = "ارسال حوالة", Total = amount + commission
            # - خروج حوالة (Pay out Received): Invoice type = "استلام حوالة", Total = amount - commission
            # - دفع فاتورة (Bill Payment): Invoice type = "دفع فاتورة", Total = amount + commission
            if t == "دخول حوالة":
                inv_total = amt + comm
            elif t == "خروج حوالة":
                inv_total = amt - comm
            else:
                inv_total = amt + comm
                
            self.generate_invoice(inv_total, "TRANSFER", {"client": c, "type": t, "ref": r, "phone": ph, "points": points_earned, "payment": payment})
            self.ui_transfers()
        except (ValueError, sqlite3.Error) as exc:
            self.db.conn.rollback(); self.show_msg("تعذر تسجيل العملية", str(exc))

    def delete_record(self, table, tree):
        selected = tree.selection()
        if not selected:
            self.show_msg("تنبيه", "حدد سجلاً أولاً")
            return
        item = tree.item(selected[0]); rid = item['values'][-1]
        if messagebox.askyesno(str("تأكيد الحذف"), str("هل تريد حذف السجل؟")):
            try:
                self.db.cursor.execute(f"DELETE FROM {table} WHERE id=?", (rid,))
                if self.db.cursor.rowcount == 0:
                    raise ValueError("السجل غير موجود")
                self.db.conn.commit()
                self.log_action("حذف سجل", table, f"المعرف: {rid}")
                self.show_msg("نجاح", "تم الحذف")
                if table == "transfers": self.refresh_transfers_tree()
                elif table == "maintenance": self.refresh_maintenance_tree()
            except (ValueError, sqlite3.Error) as exc:
                self.db.conn.rollback(); self.show_msg("تعذر الحذف", str(exc))

    def edit_record_ui(self, table, tree):
        selected = tree.selection()
        if not selected: return
        item = tree.item(selected[0]); vals = item['values']; rid = vals[-1]
        ed = ctk.CTkToplevel(self); ed.title(fix_arabic("تعديل", is_title=True)); ed.geometry("400x500"); ed.attributes("-topmost", True); ed.grab_set()
        if table == "maintenance":
            e1 = ctk.CTkEntry(ed, justify="right"); e1.insert(0, vals[4]); e1.pack(pady=10, padx=20, fill="x")
            e2 = ctk.CTkEntry(ed, justify="right"); e2.insert(0, vals[2]); e2.pack(pady=10, padx=20, fill="x")
            e3 = ctk.CTkEntry(ed, justify="right"); e3.insert(0, vals[1]); e3.pack(pady=10, padx=20, fill="x")
            def save():
                try:
                    revenue = self.positive_number(e3.get(), "المبلغ")
                    self.db.cursor.execute("UPDATE maintenance SET client_name=?, repair_desc=?, revenue=? WHERE id=?", (e1.get().strip(), e2.get().strip(), revenue, rid))
                    self.db.conn.commit(); self.log_action("تعديل سجل", table, f"المعرف: {rid}"); ed.destroy(); self.refresh_maintenance_tree()
                except (ValueError, sqlite3.Error) as exc:
                    self.db.conn.rollback(); self.show_msg("تعذر الحفظ", str(exc))
        elif table == "transfers":
            e1 = ctk.CTkEntry(ed, justify="right"); e1.insert(0, vals[3]); e1.pack(pady=10, padx=20, fill="x")
            e2 = ctk.CTkEntry(ed, justify="right"); e2.insert(0, vals[1]); e2.pack(pady=10, padx=20, fill="x")
            def save():
                try:
                    amount = self.positive_number(e2.get(), "المبلغ")
                    self.db.cursor.execute("UPDATE transfers SET client_name=?, amount=? WHERE id=?", (e1.get().strip(), amount, rid))
                    self.db.conn.commit(); self.log_action("تعديل سجل", table, f"المعرف: {rid}"); ed.destroy(); self.refresh_transfers_tree()
                except (ValueError, sqlite3.Error) as exc:
                    self.db.conn.rollback(); self.show_msg("تعذر الحفظ", str(exc))
        ctk.CTkButton(ed, text=fix_arabic("حفظ", for_ui=True), command=save, fg_color=COLOR_CRIMSON).pack(pady=20)

    def ui_loyalty(self):
        for w in self.main_view.winfo_children(): w.destroy()
        self.create_header("نظام الولاء")
        f = ctk.CTkFrame(self.main_view, fg_color="transparent"); f.pack(fill="x", padx=20, pady=20)
        self.l_phone = ctk.CTkEntry(f, placeholder_text=fix_arabic("رقم الهاتف", for_ui=True), height=50, justify="right"); self.l_phone.pack(side="right", padx=10, expand=True, fill="x")
        ctk.CTkButton(f, text=fix_arabic("بحث", for_ui=True), command=self.search_loyalty, font=FONT_BOLD, height=50, fg_color=COLOR_CRIMSON).pack(side="right", padx=10)
        self.l_info = ctk.CTkLabel(self.main_view, text="", font=FONT_BOLD, text_color=COLOR_CRIMSON_DARK); self.l_info.pack(pady=20)
        
        redeem_frame = ctk.CTkFrame(self.main_view, fg_color="#FFF9C4", corner_radius=20); redeem_frame.pack(pady=10, padx=50, fill="x")
        ctk.CTkLabel(redeem_frame, text=fix_arabic("النقاط للاستبدال:", for_ui=True), font=FONT_BOLD, text_color=COLOR_TEXT_DARK).pack(side="right", padx=20, pady=25)
        self.l_redeem_amt = ctk.CTkEntry(redeem_frame, placeholder_text="0", width=120, height=50, justify="center", font=FONT_BOLD); self.l_redeem_amt.pack(side="right", padx=10, pady=25)
        ctk.CTkButton(redeem_frame, text=fix_arabic("استبدال النقاط", for_ui=True), fg_color="#F57F17", command=self.redeem_points, font=FONT_BOLD, height=50, width=150).pack(side="right", padx=20)

    def search_loyalty(self):
        ph = self.l_phone.get().strip()
        self.db.cursor.execute("SELECT name, points FROM customers WHERE phone=?", (ph,))
        res = self.db.cursor.fetchone()
        if res: self.l_info.configure(text=fix_arabic(f"العميل: {res[0]}  |  رصيد النقاط: {res[1]} نقطة", for_ui=True))
        else: self.show_msg("تنبيه", "رقم الهاتف غير مسجل في نظام العملاء")

    def redeem_points(self):
        ph = self.l_phone.get().strip()
        try:
            amt = self.positive_integer(self.l_redeem_amt.get(), "عدد النقاط")
            self.db.cursor.execute("SELECT points FROM customers WHERE phone=?", (ph,))
            res = self.db.cursor.fetchone()
            if not res or res[0] < amt:
                raise ValueError("رصيد النقاط غير كافٍ")
            self.db.cursor.execute("UPDATE customers SET points = points - ? WHERE phone=?", (amt, ph))
            self.db.conn.commit(); self.log_action("استبدال نقاط", "customers", f"الهاتف: {ph}; النقاط: {amt}"); self.show_msg("نجاح", "تم استبدال النقاط بنجاح"); self.search_loyalty()
        except (ValueError, sqlite3.Error) as exc:
            self.db.conn.rollback(); self.show_msg("تعذر الاستبدال", str(exc))

    def ui_inventory(self):
        for w in self.main_view.winfo_children(): w.destroy()
        self.create_header("إدارة المخزون")
        f1 = ctk.CTkFrame(self.main_view, fg_color="transparent"); f1.pack(fill="x", padx=15, pady=5)
        self.i_code = ctk.CTkEntry(f1, placeholder_text=fix_arabic("باركود", for_ui=True), height=45, font=FONT_NORMAL_BOLD, justify="right", corner_radius=10); self.i_code.pack(side="right", padx=5)
        self.i_code.bind("<Return>", lambda e: self.lookup_product_inventory())
        self.i_name = ctk.CTkEntry(f1, placeholder_text=fix_arabic("اسم المنتج", for_ui=True), height=45, font=FONT_NORMAL_BOLD, justify="right", corner_radius=10); self.i_name.pack(side="right", padx=5, expand=True, fill="x")
        
        f2 = ctk.CTkFrame(self.main_view, fg_color="transparent"); f2.pack(fill="x", padx=15, pady=5)
        self.i_buy = ctk.CTkEntry(f2, placeholder_text=fix_arabic("سعر الشراء", for_ui=True), height=45, font=FONT_NORMAL_BOLD, width=120, justify="right", corner_radius=10); self.i_buy.pack(side="right", padx=5)
        self.i_sell = ctk.CTkEntry(f2, placeholder_text=fix_arabic("سعر البيع", for_ui=True), height=45, font=FONT_NORMAL_BOLD, width=120, justify="right", corner_radius=10); self.i_sell.pack(side="right", padx=5)
        self.i_stock = ctk.CTkEntry(f2, placeholder_text=fix_arabic("الكمية", for_ui=True), height=45, font=FONT_NORMAL_BOLD, width=100, justify="right", corner_radius=10); self.i_stock.pack(side="right", padx=5)
        ctk.CTkButton(f2, text=fix_arabic("حفظ المنتج", for_ui=True), command=self.add_product, font=FONT_BOLD, height=45, corner_radius=10, fg_color=COLOR_CRIMSON).pack(side="right", padx=10)
        ctk.CTkButton(f2, text=fix_arabic("تعريف منتج بدون باركود", for_ui=True), command=self.open_no_barcode_window, font=FONT_BOLD, height=45, corner_radius=10, fg_color="#1565C0", hover_color="#0D47A1").pack(side="right", padx=10)

        v_frame = ctk.CTkFrame(self.main_view, fg_color="#E8F5E9", corner_radius=10); v_frame.pack(fill="x", padx=15, pady=5)
        self.val_buy_lbl = ctk.CTkLabel(v_frame, text=fix_arabic("قيمة المخزون (شراء): 0.00", for_ui=True), font=FONT_BOLD, text_color="#2E7D32"); self.val_buy_lbl.pack(side="right", padx=20, pady=5)
        self.val_sell_lbl = ctk.CTkLabel(v_frame, text=fix_arabic("القيمة المتوقعة (بيع): 0.00", for_ui=True), font=FONT_BOLD, text_color="#1565C0"); self.val_sell_lbl.pack(side="right", padx=20, pady=5)

        self.inv_tree = ttk.Treeview(self.main_view, columns=("stock", "sell", "buy", "name", "code"), show="headings")
        for col, head in zip(self.inv_tree["columns"], ["المخزون", "البيع", "الشراء", "الاسم", "الكود"]): self.inv_tree.heading(col, text=fix_arabic(head, for_ui=True))
        self.inv_tree.pack(fill="both", expand=True, padx=15, pady=10)
        self.refresh_inventory_tree()

    def open_no_barcode_window(self):
        nw = ctk.CTkToplevel(self)
        nw.title(fix_arabic("تعريف منتج بدون باركود", is_title=True))
        nw.geometry("450x400")
        nw.attributes("-topmost", True)
        nw.grab_set()
        
        ctk.CTkLabel(nw, text=fix_arabic("تعريف منتج جديد وتوليد باركود تلقائي", for_ui=True), font=FONT_BOLD, text_color=COLOR_CRIMSON).pack(pady=15)
        
        e_name = ctk.CTkEntry(nw, placeholder_text=fix_arabic("اسم المنتج", for_ui=True), width=350, height=45, font=FONT_NORMAL_BOLD, justify="right"); e_name.pack(pady=10)
        e_buy = ctk.CTkEntry(nw, placeholder_text=fix_arabic("التكلفة الفردية (سعر الشراء)", for_ui=True), width=350, height=45, font=FONT_NORMAL_BOLD, justify="right"); e_buy.pack(pady=10)
        e_sell = ctk.CTkEntry(nw, placeholder_text=fix_arabic("سعر البيع", for_ui=True), width=350, height=45, font=FONT_NORMAL_BOLD, justify="right"); e_sell.pack(pady=10)
        e_qty = ctk.CTkEntry(nw, placeholder_text=fix_arabic("الكمية المتوفرة", for_ui=True), width=350, height=45, font=FONT_NORMAL_BOLD, justify="right"); e_qty.pack(pady=10)
        
        def save_generated():
            name = e_name.get().strip(); buy = e_buy.get().strip(); sell = e_sell.get().strip(); qty = e_qty.get().strip()
            if not all([name, buy, sell, qty]):
                self.show_msg("تنبيه", "الرجاء تعبئة كافة الحقول"); return
            try:
                buy_value = self.positive_number(buy, "تكلفة القطعة")
                sell_value = self.positive_number(sell, "سعر البيع")
                quantity = self.positive_integer(qty, "الكمية")
                gen_code = f"NB{datetime.datetime.now().strftime('%m%d%H%M%S%f')[-14:]}"
                while self.db.cursor.execute("SELECT 1 FROM products WHERE code=?", (gen_code,)).fetchone():
                    gen_code = f"NB{datetime.datetime.now().strftime('%m%d%H%M%S%f')[-14:]}"
                self.db.cursor.execute("INSERT INTO products (code, name, buy_price, sell_price, stock, description) VALUES (?,?,?,?,?,?)", (gen_code, name, buy_value, sell_value, quantity, "بدون باركود"))
                self.db.conn.commit(); self.log_action("إضافة منتج", "products", f"الكود: {gen_code}; الاسم: {name}")
                nw.destroy(); self.show_msg("نجاح", f"تم إنشاء المنتج بنجاح!\nالباركود المولّد: {gen_code}"); self.refresh_inventory_tree()
            except (ValueError, sqlite3.Error) as exc:
                self.db.conn.rollback(); self.show_msg("تعذر إضافة المنتج", str(exc))
            
        ctk.CTkButton(nw, text=fix_arabic("إضافة منتج", for_ui=True), command=save_generated, font=FONT_BOLD, fg_color="#2e7d32", height=45, width=200).pack(pady=15)

    def refresh_inventory_tree(self):
        for i in self.inv_tree.get_children(): self.inv_tree.delete(i)
        self.db.cursor.execute("SELECT stock, sell_price, buy_price, name, code, min_stock FROM products")
        rows = self.db.cursor.fetchall()
        total_buy = 0; total_sell = 0
        for r in rows:
            tag = "low" if r[0] <= r[5] else "normal"
            self.inv_tree.insert("", "end", values=(r[0], f"{r[1]:.2f}", f"{r[2]:.2f}", fix_arabic(r[3], for_ui=True), r[4]), tags=(tag,))
            total_buy += (r[0] * r[2]); total_sell += (r[0] * r[1])
        self.inv_tree.tag_configure("low", background="#FFEBEE")
        self.val_buy_lbl.configure(text=fix_arabic(f"قيمة المخزون (شراء): {total_buy:.2f} {CURRENCY}", for_ui=True))
        self.val_sell_lbl.configure(text=fix_arabic(f"القيمة المتوقعة (بيع): {total_sell:.2f} {CURRENCY}", for_ui=True))

    def lookup_product_inventory(self):
        code = self.i_code.get().strip()
        self.db.cursor.execute("SELECT name, buy_price, sell_price, stock FROM products WHERE code=?", (code,))
        p = self.db.cursor.fetchone()
        if p:
            self.i_name.delete(0, 'end'); self.i_name.insert(0, p[0])
            self.i_buy.delete(0, 'end'); self.i_buy.insert(0, str(p[1])); self.i_sell.delete(0, 'end'); self.i_sell.insert(0, str(p[2]))
            self.i_stock.delete(0, 'end'); self.i_stock.insert(0, str(p[3]))

    def add_product(self):
        c, n, b, s, q = (self.i_code.get().strip(), self.i_name.get().strip(), self.i_buy.get().strip(), self.i_sell.get().strip(), self.i_stock.get().strip())
        if not all([c, n, b, s, q]):
            self.show_msg("تنبيه", "يرجى ملء الكود والاسم وسعر الشراء وسعر البيع والكمية"); return
        try:
            buy, sell, stock = self.positive_number(b, "سعر الشراء"), self.positive_number(s, "سعر البيع"), self.positive_integer(q, "الكمية")
            self.db.cursor.execute("INSERT INTO products (code, name, buy_price, sell_price, stock, description) VALUES (?,?,?,?,?,?) ON CONFLICT(code) DO UPDATE SET name=excluded.name, buy_price=excluded.buy_price, sell_price=excluded.sell_price, stock=excluded.stock", (c, n, buy, sell, stock, ""))
            self.db.conn.commit(); self.log_action("حفظ منتج", "products", f"الكود: {c}; الاسم: {n}"); self.refresh_inventory_tree(); self.show_msg("نجاح", "تم حفظ المنتج وتحديث المخزون بنجاح")
        except (ValueError, sqlite3.Error) as exc:
            self.db.conn.rollback(); self.show_msg("تعذر حفظ المنتج", str(exc))

    def ui_purchases(self):
        for w in self.main_view.winfo_children(): w.destroy()
        self.create_header("المشتريات")
        f = ctk.CTkFrame(self.main_view, fg_color="transparent"); f.pack(fill="x", padx=15, pady=5)
        self.p_code = ctk.CTkEntry(f, placeholder_text=fix_arabic("باركود المنتج", for_ui=True), height=45, font=FONT_NORMAL_BOLD, justify="right", corner_radius=10); self.p_code.pack(side="right", padx=5)
        self.p_code.bind("<Return>", lambda e: self.lookup_product_purchase())
        self.p_name = ctk.CTkEntry(f, placeholder_text=fix_arabic("اسم المنتج الجديد", for_ui=True), height=45, font=FONT_NORMAL_BOLD, justify="right", corner_radius=10); self.p_name.pack(side="right", padx=5, expand=True, fill="x")
        
        f2 = ctk.CTkFrame(self.main_view, fg_color="transparent"); f2.pack(fill="x", padx=15, pady=5)
        self.p_qty = ctk.CTkEntry(f2, placeholder_text=fix_arabic("الكمية", for_ui=True), height=45, font=FONT_NORMAL_BOLD, width=100, justify="right", corner_radius=10); self.p_qty.pack(side="right", padx=5)
        self.p_cost = ctk.CTkEntry(f2, placeholder_text=fix_arabic("تكلفة القطعة", for_ui=True), height=45, font=FONT_NORMAL_BOLD, width=150, justify="right", corner_radius=10); self.p_cost.pack(side="right", padx=5)
        self.p_sell = ctk.CTkEntry(f2, placeholder_text=fix_arabic("سعر البيع", for_ui=True), height=45, font=FONT_NORMAL_BOLD, width=150, justify="right", corner_radius=10); self.p_sell.pack(side="right", padx=5)
        self.p_supplier = ctk.CTkEntry(f2, placeholder_text=fix_arabic("المورد (اختياري)", for_ui=True), height=45, font=FONT_NORMAL_BOLD, width=170, justify="right", corner_radius=10); self.p_supplier.pack(side="right", padx=5)
        
        self.p_total_lbl = ctk.CTkLabel(f2, text=fix_arabic("إجمالي الفاتورة: 0.00", for_ui=True), font=FONT_BOLD, text_color=COLOR_CRIMSON); self.p_total_lbl.pack(side="right", padx=15)
        
        def update_p_total(*args):
            try:
                q = float(clean_float(self.p_qty.get()))
                c = float(clean_float(self.p_cost.get()))
                self.p_total_lbl.configure(text=fix_arabic(f"إجمالي الفاتورة: {q*c:.2f}", for_ui=True))
            except: self.p_total_lbl.configure(text=fix_arabic("إجمالي الفاتورة: 0.00", for_ui=True))
            
        self.p_qty.bind("<KeyRelease>", update_p_total)
        self.p_cost.bind("<KeyRelease>", update_p_total)

        ctk.CTkButton(f2, text=fix_arabic("تسجيل الشراء", for_ui=True), command=self.add_purchase, font=FONT_BOLD, height=45, corner_radius=10, fg_color=COLOR_CRIMSON).pack(side="right", padx=10)
        ctk.CTkButton(f2, text=fix_arabic("تعريف بدون باركود", for_ui=True), command=self.open_no_barcode_window, font=FONT_BOLD, height=45, corner_radius=10, fg_color="#1565C0", hover_color="#0D47A1").pack(side="right", padx=10)
        
        self.pur_tree = ttk.Treeview(self.main_view, columns=("date", "total", "supplier", "cost", "qty", "name", "code"), show="headings")
        for col, head in zip(self.pur_tree["columns"], ["التاريخ", "إجمالي الشراء", "المورد", "تكلفة القطعة", "الكمية", "الاسم", "الكود"]): self.pur_tree.heading(col, text=fix_arabic(head, for_ui=True))
        self.pur_tree.pack(fill="both", expand=True, padx=15, pady=10)
        self.refresh_purchases_tree()

    def refresh_purchases_tree(self):
        for i in self.pur_tree.get_children(): self.pur_tree.delete(i)
        self.db.cursor.execute("SELECT date, (qty * cost), supplier, cost, qty, name, code FROM purchases ORDER BY id DESC")
        [self.pur_tree.insert("", "end", values=(r[0], f"{r[1]:.2f}", r[2] or "-", r[3], r[4], fix_arabic(r[5], for_ui=True), r[6])) for r in self.db.cursor.fetchall()]

    def lookup_product_purchase(self):
        code = self.p_code.get().strip()
        self.db.cursor.execute("SELECT name, buy_price, sell_price FROM products WHERE code=?", (code,))
        res = self.db.cursor.fetchone()
        if res:
            self.p_name.delete(0, 'end'); self.p_name.insert(0, res[0])
            self.p_cost.delete(0, 'end'); self.p_cost.insert(0, str(res[1]))
            self.p_sell.delete(0, 'end'); self.p_sell.insert(0, str(res[2]))

    def add_purchase(self):
        c, n = self.p_code.get().strip(), self.p_name.get().strip()
        q_str, cost_str, sell_str = self.p_qty.get().strip(), self.p_cost.get().strip(), self.p_sell.get().strip()
        supplier = self.p_supplier.get().strip()
        if not all([c, n, q_str, cost_str]):
            self.show_msg("تنبيه", "يرجى ملء الكود والاسم والكمية وتكلفة القطعة"); return
        try:
            qty = self.positive_integer(q_str, "الكمية")
            cost = self.positive_number(cost_str, "تكلفة القطعة")
            sell_price = self.positive_number(sell_str, "سعر البيع") if sell_str else (cost * 1.2)
            now = datetime.datetime.now(); date, time = now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S")
            total = qty * cost
            self.db.cursor.execute("INSERT INTO purchases (code, name, qty, cost, supplier, date, time, description, user) VALUES (?,?,?,?,?,?,?,?,?)", (c, n, qty, cost, supplier, date, time, "شراء مخزون", self.current_user))
            prod = self.db.cursor.execute("SELECT stock FROM products WHERE code=?", (c,)).fetchone()
            if prod:
                self.db.cursor.execute("UPDATE products SET stock = stock + ?, buy_price = ?, sell_price = MAX(sell_price, ?) WHERE code=?", (qty, cost, sell_price, c))
            else:
                self.db.cursor.execute("INSERT INTO products (code, name, buy_price, sell_price, stock, description) VALUES (?,?,?,?,?,?)", (c, n, cost, sell_price, qty, "مشتريات جديدة"))
            if supplier:
                self.db.cursor.execute("INSERT INTO suppliers (name, balance) VALUES (?, ?) ON CONFLICT(name) DO UPDATE SET balance = balance + excluded.balance", (supplier, total))
            self.db.conn.commit(); self.log_action("تسجيل شراء", "purchases", f"الكود: {c}; الإجمالي: {total:.2f}; المورد: {supplier or '-'}")
            self.show_msg("نجاح", f"تم تسجيل الشراء بقيمة {total:.2f} {CURRENCY} وإضافة {qty} قطعة إلى المخزون")
            self.refresh_purchases_tree(); self.refresh_inventory_tree() if hasattr(self, "inv_tree") else None
        except (ValueError, sqlite3.Error) as exc:
            self.db.conn.rollback(); self.show_msg("تعذر تسجيل الشراء", str(exc))

    def ui_suppliers(self):
        for w in self.main_view.winfo_children(): w.destroy()
        self.create_header("الموردون والديون")
        form = ctk.CTkFrame(self.main_view, fg_color="transparent"); form.pack(fill="x", padx=15, pady=10)
        self.sup_name = ctk.CTkEntry(form, placeholder_text=fix_arabic("اسم المورد", for_ui=True), font=FONT_NORMAL_BOLD, height=42, justify="right"); self.sup_name.pack(side="right", padx=5, expand=True, fill="x")
        self.sup_phone = ctk.CTkEntry(form, placeholder_text=fix_arabic("الهاتف", for_ui=True), font=FONT_NORMAL_BOLD, height=42, justify="right", width=150); self.sup_phone.pack(side="right", padx=5)
        self.sup_address = ctk.CTkEntry(form, placeholder_text=fix_arabic("العنوان", for_ui=True), font=FONT_NORMAL_BOLD, height=42, justify="right", width=180); self.sup_address.pack(side="right", padx=5)
        self.sup_balance = ctk.CTkEntry(form, placeholder_text=fix_arabic("الرصيد/الدين", for_ui=True), font=FONT_NORMAL_BOLD, height=42, justify="right", width=130); self.sup_balance.pack(side="right", padx=5)
        ctk.CTkButton(form, text=fix_arabic("حفظ المورد", for_ui=True), command=self.save_supplier, font=FONT_BOLD, height=42, fg_color=COLOR_CRIMSON).pack(side="right", padx=8)
        self.sup_tree = ttk.Treeview(self.main_view, columns=("balance", "address", "phone", "name"), show="headings")
        for col, head in zip(self.sup_tree["columns"], ["الرصيد/الدين", "العنوان", "الهاتف", "اسم المورد"]): self.sup_tree.heading(col, text=fix_arabic(head, for_ui=True))
        self.sup_tree.pack(fill="both", expand=True, padx=15, pady=10)
        self.refresh_suppliers()

    def save_supplier(self):
        name, phone, address, balance = self.sup_name.get().strip(), self.sup_phone.get().strip(), self.sup_address.get().strip(), self.sup_balance.get().strip() or "0"
        if not name:
            self.show_msg("تنبيه", "يرجى إدخال اسم المورد"); return
        try:
            balance_value = self.positive_number(balance, "الرصيد", allow_zero=True)
            self.db.cursor.execute("INSERT INTO suppliers (name, phone, address, balance) VALUES (?,?,?,?) ON CONFLICT(name) DO UPDATE SET phone=excluded.phone, address=excluded.address, balance=excluded.balance", (name, phone, address, balance_value))
            self.db.conn.commit(); self.log_action("حفظ مورد", "suppliers", f"المورد: {name}; الرصيد: {balance_value:.2f}"); self.refresh_suppliers(); self.show_msg("نجاح", "تم حفظ بيانات المورد")
        except (ValueError, sqlite3.Error) as exc:
            self.db.conn.rollback(); self.show_msg("تعذر حفظ المورد", str(exc))

    def refresh_suppliers(self):
        for i in self.sup_tree.get_children(): self.sup_tree.delete(i)
        self.db.cursor.execute("SELECT balance, address, phone, name FROM suppliers ORDER BY name")
        for row in self.db.cursor.fetchall():
            self.sup_tree.insert("", "end", values=(f"{float(row[0] or 0):.2f}", row[1] or "-", row[2] or "-", fix_arabic(row[3], for_ui=True)))

    def ui_audit_logs(self):
        for w in self.main_view.winfo_children(): w.destroy()
        self.create_header("سجل الرقابة والعمليات")
        top = ctk.CTkFrame(self.main_view, fg_color="transparent"); top.pack(fill="x", padx=15, pady=8)
        ctk.CTkButton(top, text=fix_arabic("تحديث", for_ui=True), command=self.refresh_audit_logs, font=FONT_BOLD, fg_color=COLOR_CRIMSON, height=40).pack(side="right", padx=5)
        ctk.CTkLabel(top, text=fix_arabic("يسجل النظام عمليات الدخول والإضافة والتعديل والحذف دون تغيير السجلات الأصلية.", for_ui=True), font=FONT_NORMAL_BOLD, text_color=COLOR_TEXT_DARK).pack(side="right", padx=15)
        self.audit_tree = ttk.Treeview(self.main_view, columns=("details", "entity", "action", "time", "date", "user"), show="headings")
        for col, head in zip(self.audit_tree["columns"], ["التفاصيل", "الكيان", "العملية", "الساعة", "التاريخ", "المستخدم"]): self.audit_tree.heading(col, text=fix_arabic(head, for_ui=True))
        self.audit_tree.pack(fill="both", expand=True, padx=15, pady=10)
        self.refresh_audit_logs()

    def ui_operations_management(self):
        for w in self.main_view.winfo_children():
            w.destroy()
        self.create_header("إدارة العمليات")
        f_top = ctk.CTkFrame(self.main_view, fg_color="transparent")
        f_top.pack(fill="x", padx=15, pady=8)

        try:
            usernames = [r[0] for r in self.db.cursor.execute("SELECT username FROM users ORDER BY username").fetchall() if r[0]]
        except sqlite3.Error:
            usernames = []
        self.op_user = ctk.CTkComboBox(f_top, values=[fix_arabic("الكل", for_ui=True)] + usernames, width=150, height=40, font=FONT_NORMAL_BOLD, justify="center")
        self.op_user.pack(side="right", padx=5)
        self.op_user.set(fix_arabic("الكل", for_ui=True))
        ctk.CTkLabel(f_top, text=fix_arabic("المستخدم:", for_ui=True), font=FONT_BOLD, text_color=COLOR_CRIMSON).pack(side="right", padx=3)
        self.op_to = ctk.CTkEntry(f_top, placeholder_text="YYYY-MM-DD", width=135, height=40, justify="center", font=FONT_NORMAL_BOLD)
        self.op_to.pack(side="right", padx=5)
        ctk.CTkLabel(f_top, text=fix_arabic("إلى:", for_ui=True), font=FONT_BOLD, text_color=COLOR_CRIMSON).pack(side="right", padx=2)
        self.op_from = ctk.CTkEntry(f_top, placeholder_text="YYYY-MM-DD", width=135, height=40, justify="center", font=FONT_NORMAL_BOLD)
        self.op_from.pack(side="right", padx=5)
        ctk.CTkLabel(f_top, text=fix_arabic("من:", for_ui=True), font=FONT_BOLD, text_color=COLOR_CRIMSON).pack(side="right", padx=2)
        ctk.CTkButton(f_top, text=fix_arabic("فلترة", for_ui=True), command=self.refresh_operations_tree, font=FONT_BOLD, fg_color=COLOR_CRIMSON, height=40, width=90).pack(side="right", padx=5)
        ctk.CTkButton(f_top, text=fix_arabic("تعديل العملية", for_ui=True), command=self.edit_operation_record_ui, font=FONT_BOLD, fg_color="#1565C0", height=40, width=125).pack(side="left", padx=5)
        ctk.CTkButton(f_top, text=fix_arabic("حذف العملية", for_ui=True), command=self.delete_operation_record, font=FONT_BOLD, fg_color="#C62828", height=40, width=125).pack(side="left", padx=5)

        cols = ("source", "user", "payment", "total", "desc", "type", "date", "id")
        heads = ["المصدر", "المستخدم", "الدفع", "الإجمالي", "الوصف/المنتج", "النوع", "التاريخ", "ID"]
        table_frame = ctk.CTkFrame(self.main_view, fg_color="transparent")
        table_frame.pack(fill="both", expand=True, padx=15, pady=8)
        self.ops_tree = ttk.Treeview(table_frame, columns=cols, displaycolumns=("user", "payment", "total", "desc", "type", "date", "id"), show="headings")
        for c, h in zip(cols, heads):
            self.ops_tree.heading(c, text=fix_arabic(h, for_ui=True))
        widths = {"source": 0, "user": 130, "payment": 100, "total": 110, "desc": 300, "type": 150, "date": 120, "id": 70}
        for c, width in widths.items():
            self.ops_tree.column(c, width=width, minwidth=width if c != "source" else 0, stretch=(c in {"desc", "type"}), anchor="center")
        ybar = ttk.Scrollbar(table_frame, orient="vertical", command=self.ops_tree.yview)
        xbar = ttk.Scrollbar(table_frame, orient="horizontal", command=self.ops_tree.xview)
        self.ops_tree.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        self.ops_tree.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")
        table_frame.grid_rowconfigure(0, weight=1); table_frame.grid_columnconfigure(0, weight=1)
        self.refresh_operations_tree()

    def _operation_where(self, start, end, user):
        where, params = self.date_filter("date", start, end)
        user = (user or "").strip()
        all_label = fix_arabic("الكل", for_ui=True)
        if user and user != all_label:
            where = (where + " AND " if where else "WHERE ") + "user=?"
            params.append(user)
        return where, params

    def refresh_operations_tree(self):
        for i in self.ops_tree.get_children():
            self.ops_tree.delete(i)
        try:
            start, end = self.op_from.get().strip(), self.op_to.get().strip()
            user = self.op_user.get().strip()
            where, params = self._operation_where(start, end, user)
            rows = []
            queries = [
                ("sales", f"SELECT user, COALESCE(payment_method,'Cash'), total, COALESCE(name,''), 'مبيعات', date, id FROM sales {where} ORDER BY date DESC, id DESC LIMIT 500", params),
                ("maintenance", f"SELECT user, COALESCE(payment_method,'Cash'), revenue, TRIM(COALESCE(device_name,'') || CASE WHEN COALESCE(repair_desc,'')<>'' THEN ' - ' || repair_desc ELSE '' END), 'صيانة', date, id FROM maintenance {where} ORDER BY date DESC, id DESC LIMIT 500", params),
                ("transfers", f"SELECT user, COALESCE(payment_method,'Cash'), CASE WHEN type='خروج حوالة' THEN (amount - commission) ELSE (amount + commission) END, TRIM(COALESCE(type,'') || CASE WHEN COALESCE(reference,'')<>'' THEN ' - ' || reference ELSE '' END), 'حوالات/فواتير', date, id FROM transfers {where} ORDER BY date DESC, id DESC LIMIT 500", params),
                ("purchases", f"SELECT COALESCE(user,'-'), 'Cash', (qty * cost), TRIM(COALESCE(name,'') || CASE WHEN COALESCE(supplier,'')<>'' THEN ' - ' || supplier ELSE '' END), 'مشتريات', date, id FROM purchases {where} ORDER BY date DESC, id DESC LIMIT 500", params),
                ("expenses", f"SELECT COALESCE(user,'-'), 'Cash', amount, COALESCE(desc,''), 'مصروف', date, id FROM expenses {where} ORDER BY date DESC, id DESC LIMIT 500", params),
            ]
            for source, query, query_params in queries:
                self.db.cursor.execute(query, list(query_params))
                rows.extend((source, *row) for row in self.db.cursor.fetchall())
            rows.sort(key=lambda row: (row[6] or "", int(row[7] or 0)), reverse=True)
            for source, user_name, payment, total, desc, op_type, date, rid in rows:
                self.ops_tree.insert("", "end", iid=f"{source}:{rid}", values=(source, user_name or "-", payment or "Cash", f"{float(total or 0):.2f}", fix_arabic(desc or "", for_ui=True), fix_arabic(op_type, for_ui=True), date or "", rid))
        except (ValueError, sqlite3.Error) as exc:
            self.show_msg("تعذر تحميل العمليات", str(exc))

    def _adjust_customer_points(self, phone, delta):
        if phone and delta:
            self.db.cursor.execute("UPDATE customers SET points=MAX(0, points + ?) WHERE phone=?", (int(delta), phone))

    def delete_operation_record(self):
        selected = self.ops_tree.selection()
        if not selected:
            self.show_msg("تنبيه", "يرجى تحديد عملية للحذف")
            return
        source, rid_text = str(selected[0]).split(":", 1)
        rid = int(rid_text)
        if not messagebox.askyesno(str("تأكيد الحذف"), str("سيتم عكس أثر العملية على المخزون والتقارير والرصيد. هل تريد المتابعة؟")):
            return
        try:
            if source == "sales":
                row = self.db.cursor.execute("SELECT code, qty, total, customer_phone FROM sales WHERE id=?", (rid,)).fetchone()
                if not row: raise ValueError("عملية البيع غير موجودة")
                self.db.cursor.execute("UPDATE products SET stock=stock+? WHERE code=?", (int(row[1] or 0), row[0]))
                self._adjust_customer_points(row[3], -int(float(row[2] or 0) * 10))
                self.db.cursor.execute("DELETE FROM sales WHERE id=?", (rid,))
            elif source == "maintenance":
                row = self.db.cursor.execute("SELECT client_phone FROM maintenance WHERE id=?", (rid,)).fetchone()
                if not row: raise ValueError("عملية الصيانة غير موجودة")
                self._adjust_customer_points(row[0], -5)
                self.db.cursor.execute("DELETE FROM maintenance WHERE id=?", (rid,))
            elif source == "transfers":
                row = self.db.cursor.execute("SELECT client_phone FROM transfers WHERE id=?", (rid,)).fetchone()
                if not row: raise ValueError("عملية الحوالة غير موجودة")
                self._adjust_customer_points(row[0], -2)
                self.db.cursor.execute("DELETE FROM transfers WHERE id=?", (rid,))
            elif source == "purchases":
                row = self.db.cursor.execute("SELECT code, qty, cost, supplier FROM purchases WHERE id=?", (rid,)).fetchone()
                if not row: raise ValueError("عملية الشراء غير موجودة")
                stock_row = self.db.cursor.execute("SELECT stock FROM products WHERE code=?", (row[0],)).fetchone()
                if not stock_row or int(stock_row[0] or 0) < int(row[1] or 0):
                    raise ValueError("لا يمكن حذف الشراء لأن المخزون الحالي أقل من الكمية المشتراة")
                self.db.cursor.execute("UPDATE products SET stock=stock-? WHERE code=?", (int(row[1] or 0), row[0]))
                if row[3]: self.db.cursor.execute("UPDATE suppliers SET balance=balance-? WHERE name=?", (float(row[1] or 0) * float(row[2] or 0), row[3]))
                self.db.cursor.execute("DELETE FROM purchases WHERE id=?", (rid,))
            elif source == "expenses":
                if not self.db.cursor.execute("DELETE FROM expenses WHERE id=?", (rid,)).rowcount:
                    raise ValueError("المصروف غير موجود")
            else:
                raise ValueError("نوع العملية غير معروف")
            self.db.conn.commit()
            self.log_action("حذف عملية", source, f"المعرف: {rid}")
            self.show_msg("نجاح", "تم حذف العملية وعكس أثرها على الحسابات والمخزون")
            self.refresh_operations_tree()
        except (ValueError, sqlite3.Error) as exc:
            self.db.conn.rollback()
            self.show_msg("تعذر الحذف", str(exc))

    def _edit_field(self, parent, label, value="", secret=False):
        ctk.CTkLabel(parent, text=fix_arabic(label, for_ui=True), font=FONT_NORMAL_BOLD).pack(anchor="e", padx=25, pady=(7, 2))
        entry = ctk.CTkEntry(parent, font=FONT_NORMAL_BOLD, justify="right", height=38, show="*" if secret else "")
        entry.pack(fill="x", padx=20, pady=(0, 4))
        if value is not None: entry.insert(0, str(value))
        return entry

    def edit_operation_record_ui(self):
        selected = self.ops_tree.selection()
        if not selected:
            self.show_msg("تنبيه", "يرجى تحديد عملية للتعديل")
            return
        source, rid_text = str(selected[0]).split(":", 1)
        rid = int(rid_text)
        win = ctk.CTkToplevel(self); win.title(fix_arabic("تعديل العملية", is_title=True)); win.geometry("560x760"); win.attributes("-topmost", True); win.grab_set()
        ctk.CTkLabel(win, text=fix_arabic(f"تعديل {source} رقم {rid}", for_ui=True), font=FONT_BOLD, text_color=COLOR_CRIMSON).pack(pady=12)
        fields = {}
        combos = {}
        try:
            if source == "sales":
                row = self.db.cursor.execute("SELECT qty, price FROM sales WHERE id=?", (rid,)).fetchone()
                if not row: raise ValueError("عملية البيع غير موجودة")
                fields["qty"] = self._edit_field(win, "الكمية", row[0])
                fields["price"] = self._edit_field(win, "سعر القطعة", row[1])
            elif source == "maintenance":
                row = self.db.cursor.execute("SELECT client_name, client_phone, device_name, repair_desc, revenue, internal_cost, payment_method FROM maintenance WHERE id=?", (rid,)).fetchone()
                if not row: raise ValueError("عملية الصيانة غير موجودة")
                for key, label, value in zip(("client", "phone", "device", "desc", "revenue", "cost"), ("اسم العميل", "الهاتف", "الجهاز", "وصف الإصلاح", "المبلغ", "تكلفة القطع"), row[:6]): fields[key] = self._edit_field(win, label, value)
                ctk.CTkLabel(win, text=fix_arabic("طريقة الدفع", for_ui=True), font=FONT_NORMAL_BOLD).pack(anchor="e", padx=25, pady=(7, 2))
                combos["payment"] = ctk.CTkComboBox(win, values=["Cash", "Visa", "CLIQ"], font=FONT_NORMAL_BOLD, height=38); combos["payment"].pack(fill="x", padx=20, pady=(0, 4)); combos["payment"].set(row[6] or "Cash")
            elif source == "transfers":
                row = self.db.cursor.execute("SELECT type, client_name, client_phone, amount, commission, reference, payment_method FROM transfers WHERE id=?", (rid,)).fetchone()
                if not row: raise ValueError("عملية الحوالة غير موجودة")
                ctk.CTkLabel(win, text=fix_arabic("نوع الخدمة", for_ui=True), font=FONT_NORMAL_BOLD).pack(anchor="e", padx=25, pady=(7, 2))
                type_values = [fix_arabic(x, for_ui=True) for x in ["خروج حوالة", "دخول حوالة", "دفع فاتورة"]]
                combos["type"] = ctk.CTkComboBox(win, values=type_values, font=FONT_NORMAL_BOLD, height=38); combos["type"].pack(fill="x", padx=20, pady=(0, 4)); combos["type"].set(fix_arabic(row[0] or "خروج حوالة", for_ui=True))
                for key, label, value in zip(("client", "phone", "amount", "commission", "reference"), ("اسم العميل", "الهاتف", "القيمة", "العمولة", "المرجع"), (row[1], row[2], row[3], row[4], row[5])): fields[key] = self._edit_field(win, label, value)
                ctk.CTkLabel(win, text=fix_arabic("طريقة الدفع", for_ui=True), font=FONT_NORMAL_BOLD).pack(anchor="e", padx=25, pady=(7, 2))
                combos["payment"] = ctk.CTkComboBox(win, values=["Cash", "Visa", "CLIQ"], font=FONT_NORMAL_BOLD, height=38); combos["payment"].pack(fill="x", padx=20, pady=(0, 4)); combos["payment"].set(row[6] or "Cash")
            elif source == "purchases":
                row = self.db.cursor.execute("SELECT qty, cost, supplier FROM purchases WHERE id=?", (rid,)).fetchone()
                if not row: raise ValueError("عملية الشراء غير موجودة")
                for key, label, value in zip(("qty", "cost", "supplier"), ("الكمية", "تكلفة القطعة", "المورد"), row): fields[key] = self._edit_field(win, label, value)
            elif source == "expenses":
                row = self.db.cursor.execute("SELECT desc, amount FROM expenses WHERE id=?", (rid,)).fetchone()
                if not row: raise ValueError("المصروف غير موجود")
                fields["desc"] = self._edit_field(win, "وصف المصروف", row[0])
                fields["amount"] = self._edit_field(win, "المبلغ", row[1])
            else:
                raise ValueError("نوع العملية غير معروف")
        except (ValueError, sqlite3.Error) as exc:
            win.destroy(); self.show_msg("تعذر فتح العملية", str(exc)); return

        def save_edit():
            try:
                if source == "sales":
                    new_qty = self.positive_integer(fields["qty"].get(), "الكمية")
                    new_price = self.positive_number(fields["price"].get(), "سعر القطعة", allow_zero=True)
                    old = self.db.cursor.execute("SELECT code, qty, total, customer_phone FROM sales WHERE id=?", (rid,)).fetchone()
                    stock = self.db.cursor.execute("SELECT stock FROM products WHERE code=?", (old[0],)).fetchone()
                    diff = new_qty - int(old[1] or 0)
                    if not stock or int(stock[0] or 0) < diff: raise ValueError("المخزون غير كافٍ للكمية الجديدة")
                    self.db.cursor.execute("UPDATE products SET stock=stock-? WHERE code=?", (diff, old[0]))
                    new_total = new_qty * new_price
                    self.db.cursor.execute("UPDATE sales SET qty=?, price=?, total=? WHERE id=?", (new_qty, new_price, new_total, rid))
                    self._adjust_customer_points(old[3], int(new_total * 10) - int(float(old[2] or 0) * 10))
                elif source == "maintenance":
                    revenue = self.positive_number(fields["revenue"].get(), "مبلغ الصيانة", allow_zero=True)
                    cost = self.positive_number(fields["cost"].get(), "تكلفة القطع", allow_zero=True)
                    self.db.cursor.execute("UPDATE maintenance SET client_name=?, client_phone=?, device_name=?, repair_desc=?, revenue=?, internal_cost=?, payment_method=? WHERE id=?", (fields["client"].get().strip(), fields["phone"].get().strip(), fields["device"].get().strip(), fields["desc"].get().strip(), revenue, cost, combos["payment"].get(), rid))
                elif source == "transfers":
                    raw_type = combos["type"].get()
                    raw_types = ["خروج حوالة", "دخول حوالة", "دفع فاتورة"]
                    transfer_type = next((x for x in raw_types if fix_arabic(x, for_ui=True) == raw_type), raw_types[0])
                    amount = self.positive_number(fields["amount"].get(), "القيمة")
                    commission = self.positive_number(fields["commission"].get(), "العمولة", allow_zero=True)
                    self.db.cursor.execute("UPDATE transfers SET type=?, client_name=?, client_phone=?, amount=?, commission=?, reference=?, payment_method=? WHERE id=?", (transfer_type, fields["client"].get().strip(), fields["phone"].get().strip(), amount, commission, fields["reference"].get().strip(), combos["payment"].get(), rid))
                elif source == "purchases":
                    new_qty = self.positive_integer(fields["qty"].get(), "الكمية")
                    new_cost = self.positive_number(fields["cost"].get(), "تكلفة القطعة")
                    new_supplier = fields["supplier"].get().strip()
                    old = self.db.cursor.execute("SELECT code, qty, cost, supplier FROM purchases WHERE id=?", (rid,)).fetchone()
                    stock = self.db.cursor.execute("SELECT stock FROM products WHERE code=?", (old[0],)).fetchone()
                    diff = new_qty - int(old[1] or 0)
                    if not stock or int(stock[0] or 0) < diff: raise ValueError("المخزون الحالي لا يسمح بهذه الكمية")
                    self.db.cursor.execute("UPDATE products SET stock=stock+?, buy_price=? WHERE code=?", (-diff, new_cost, old[0]))
                    old_total, new_total = int(old[1] or 0) * float(old[2] or 0), new_qty * new_cost
                    if old[3]: self.db.cursor.execute("UPDATE suppliers SET balance=balance-? WHERE name=?", (old_total, old[3]))
                    if new_supplier: self.db.cursor.execute("INSERT INTO suppliers (name, balance) VALUES (?, ?) ON CONFLICT(name) DO UPDATE SET balance=balance+excluded.balance", (new_supplier, new_total))
                    self.db.cursor.execute("UPDATE purchases SET qty=?, cost=?, supplier=? WHERE id=?", (new_qty, new_cost, new_supplier, rid))
                else:
                    amount = self.positive_number(fields["amount"].get(), "المبلغ", allow_zero=True)
                    self.db.cursor.execute("UPDATE expenses SET desc=?, amount=? WHERE id=?", (fields["desc"].get().strip(), amount, rid))
                self.db.conn.commit()
                self.log_action("تعديل عملية", source, f"المعرف: {rid}")
                win.destroy(); self.show_msg("نجاح", "تم تعديل العملية وتحديث أثرها المحاسبي"); self.refresh_operations_tree()
            except (ValueError, sqlite3.Error) as exc:
                self.db.conn.rollback(); self.show_msg("تعذر حفظ التعديل", str(exc))
        ctk.CTkButton(win, text=fix_arabic("حفظ التعديل", for_ui=True), command=save_edit, font=FONT_BOLD, fg_color="#2e7d32", height=45).pack(fill="x", padx=20, pady=20)

    def refresh_audit_logs(self):
        for i in self.audit_tree.get_children(): self.audit_tree.delete(i)
        self.db.cursor.execute("SELECT details, entity, action, time, date, username FROM audit_logs ORDER BY id DESC LIMIT 1000")
        for row in self.db.cursor.fetchall():
            self.audit_tree.insert("", "end", values=(fix_arabic(row[0] or "", for_ui=True), row[1], fix_arabic(row[2], for_ui=True), row[3], row[4], row[5]))

    def ui_customers(self):
        for w in self.main_view.winfo_children(): w.destroy()
        self.create_header("إدارة العملاء")
        top = ctk.CTkFrame(self.main_view, fg_color="transparent"); top.pack(fill="x", padx=20, pady=10)
        self.c_search = ctk.CTkEntry(top, placeholder_text=fix_arabic("بحث بالاسم...", for_ui=True), height=45, justify="right", corner_radius=10); self.c_search.pack(side="right", padx=10, expand=True, fill="x")
        ctk.CTkButton(top, text=fix_arabic("بحث", for_ui=True), command=self.refresh_customers, font=FONT_BOLD, width=100, height=45, fg_color=COLOR_CRIMSON).pack(side="right", padx=5)
        ctk.CTkButton(top, text=fix_arabic("إدارة ملاحظة العميل", for_ui=True), command=self.open_customer_note_manager, font=FONT_BOLD, height=45, fg_color="#6A1B9A", hover_color="#4A148C").pack(side="right", padx=5)
        ctk.CTkButton(top, text=fix_arabic("تصدير إكسل", for_ui=True), command=self.export_customers, font=FONT_BOLD, height=45, fg_color="#1565C0").pack(side="left", padx=5)
        ctk.CTkLabel(self.main_view, text=fix_arabic("اضغط مرتين على العميل لرؤية السجل الكامل (CRM)", for_ui=True), font=FONT_NORMAL_BOLD, text_color="gray").pack()
        self.c_tree = ttk.Treeview(self.main_view, columns=("note", "points", "phone", "name"), show="headings")
        for col, head in zip(self.c_tree["columns"], ["الملاحظة التنبيهية", "النقاط", "الهاتف", "الاسم"]): self.c_tree.heading(col, text=fix_arabic(head, for_ui=True))
        self.c_tree.pack(fill="both", expand=True, padx=25, pady=10)
        self.c_tree.bind("<Double-1>", lambda e: self.show_customer_history())
        self.refresh_customers()

    def open_customer_note_manager(self):
        sel = self.c_tree.selection()
        if not sel:
            self.show_msg("تنبيه", "يرجى اختيار عميل من الجدول أولاً")
            return
        vals = self.c_tree.item(sel[0])['values']
        phone, name = str(vals[2] or "").strip(), str(vals[3] or "")
        win = ctk.CTkToplevel(self); win.title(fix_arabic(f"إدارة ملاحظة العميل: {name}", is_title=True)); win.geometry("480x450"); win.attributes("-topmost", True); win.grab_set()
        ctk.CTkLabel(win, text=fix_arabic(f"الملاحظة التنبيهية للعميل: {name}", for_ui=True), font=FONT_BOLD, text_color=COLOR_CRIMSON).pack(pady=15)
        ctk.CTkLabel(win, text=fix_arabic(f"رقم الهاتف: {phone}", for_ui=True), font=FONT_NORMAL_BOLD).pack(pady=5)
        self.db.cursor.execute("SELECT note FROM customer_notes WHERE phone=?", (phone,))
        res = self.db.cursor.fetchone()
        current_note = res[0] if res else ""
        ctk.CTkLabel(win, text=fix_arabic("نص الملاحظة (ستظهر كمنبه للموظف عند إدخال رقم الهاتف):", for_ui=True), font=FONT_NORMAL_BOLD).pack(anchor="e", padx=30, pady=(10, 2))
        note_text = ctk.CTkTextbox(win, height=120, font=FONT_NORMAL_BOLD)
        note_text.pack(fill="x", padx=25, pady=5)
        if current_note:
            note_text.insert("1.0", current_note)
            
        def save_note():
            txt = note_text.get("1.0", "end-1c").strip()
            try:
                if txt:
                    self.db.cursor.execute("INSERT OR REPLACE INTO customer_notes (phone, note, updated_at) VALUES (?, ?, datetime('now'))", (phone, txt))
                    self.db.conn.commit()
                    self.log_action("تحديث ملاحظة عميل", "customer_notes", f"الهاتف: {phone}")
                    self.show_msg("نجاح", "تم حفظ الملاحظة التنبيهية بنجاح")
                    win.destroy(); self.refresh_customers()
                else:
                    delete_note()
            except sqlite3.Error as exc:
                self.db.conn.rollback(); self.show_msg("تعذر الحفظ", str(exc))

        def delete_note():
            try:
                self.db.cursor.execute("DELETE FROM customer_notes WHERE phone=?", (phone,))
                self.db.conn.commit()
                self.log_action("حذف ملاحظة عميل", "customer_notes", f"الهاتف: {phone}")
                self.show_msg("نجاح", "تم حذف الملاحظة بنجاح")
                win.destroy(); self.refresh_customers()
            except sqlite3.Error as exc:
                self.db.conn.rollback(); self.show_msg("تعذر الحذف", str(exc))

        btn_f = ctk.CTkFrame(win, fg_color="transparent")
        btn_f.pack(pady=15, fill="x", padx=25)
        ctk.CTkButton(btn_f, text=fix_arabic("حفظ الملاحظة", for_ui=True), command=save_note, font=FONT_BOLD, fg_color="#2e7d32", height=42).pack(side="right", expand=True, fill="x", padx=5)
        ctk.CTkButton(btn_f, text=fix_arabic("إزالة الملاحظة", for_ui=True), command=delete_note, font=FONT_BOLD, fg_color="#C62828", height=42).pack(side="right", expand=True, fill="x", padx=5)

    def send_whatsapp(self, phone, message):
        if not phone:
            return
        clean_ph = re.sub(r'\D', '', phone)
        if clean_ph.startswith('0'):
            clean_ph = '962' + clean_ph[1:]
        elif not clean_ph.startswith('962') and len(clean_ph) == 9:
            clean_ph = '962' + clean_ph
        url = f"https://wa.me/{clean_ph}?text={urllib.parse.quote(message)}"
        try:
            webbrowser.open(url)
        except Exception as e:
            self.show_msg("تنبيه", f"تعذر فتح واتساب: {str(e)}")

    def show_customer_history(self):
        sel = self.c_tree.selection()
        if not sel: return
        vals = self.c_tree.item(sel[0])['values']
        phone, name = str(vals[1] or ""), str(vals[2] or "")
        win = ctk.CTkToplevel(self); win.title(fix_arabic(f"سجل العميل: {name}", is_title=True)); win.geometry("850x600"); win.attributes("-topmost", True); win.grab_set()
        ctk.CTkLabel(win, text=fix_arabic(f"تاريخ معاملات العميل: {name} ({phone})", for_ui=True), font=FONT_BOLD, text_color=COLOR_CRIMSON).pack(pady=10)
        tabs = ctk.CTkTabview(win, corner_radius=15); tabs.pack(fill="both", expand=True, padx=10, pady=10)
        t1, t2, t3 = tabs.add(fix_arabic("المشتريات", for_ui=True)), tabs.add(fix_arabic("الصيانة", for_ui=True)), tabs.add(fix_arabic("الحوالات والفواتير", for_ui=True))
        
        tr1 = ttk.Treeview(t1, columns=("payment", "total", "qty", "name", "date"), show="headings")
        for c, h in zip(tr1["columns"], ["الدفع", "الإجمالي", "الكمية", "المنتج", "التاريخ"]): tr1.heading(c, text=fix_arabic(h, for_ui=True))
        tr1.pack(fill="both", expand=True)
        self.db.cursor.execute("SELECT payment_method, total, qty, name, date FROM sales WHERE customer_phone=? OR customer_phone IN (SELECT phone FROM customers WHERE name=?)", (phone, name))
        [tr1.insert("", "end", values=(r[0] or "Cash", f"{float(r[1] or 0):.2f}", r[2], fix_arabic(r[3], for_ui=True), r[4])) for r in self.db.cursor.fetchall()]
        
        tr2 = ttk.Treeview(t2, columns=("payment", "revenue", "desc", "device", "date"), show="headings")
        for c, h in zip(tr2["columns"], ["الدفع", "المبلغ", "وصف الإصلاح", "الجهاز", "التاريخ"]): tr2.heading(c, text=fix_arabic(h, for_ui=True))
        tr2.pack(fill="both", expand=True)
        self.db.cursor.execute("SELECT payment_method, revenue, repair_desc, device_name, date FROM maintenance WHERE client_phone=? OR client_name=?", (phone, name))
        [tr2.insert("", "end", values=(r[0] or "Cash", f"{float(r[1] or 0):.2f}", fix_arabic(r[2], for_ui=True), fix_arabic(r[3], for_ui=True), r[4])) for r in self.db.cursor.fetchall()]
        
        tr3 = ttk.Treeview(t3, columns=("payment", "ref", "comm", "amount", "type", "date"), show="headings")
        for c, h in zip(tr3["columns"], ["الدفع", "المرجع", "العمولة", "المبلغ", "النوع", "التاريخ"]): tr3.heading(c, text=fix_arabic(h, for_ui=True))
        tr3.pack(fill="both", expand=True)
        self.db.cursor.execute("SELECT payment_method, reference, commission, amount, type, date FROM transfers WHERE client_phone=? OR client_name=?", (phone, name))
        [tr3.insert("", "end", values=(r[0] or "Cash", r[1] or "-", f"{float(r[2] or 0):.2f}", f"{float(r[3] or 0):.2f}", fix_arabic(r[4], for_ui=True), r[5])) for r in self.db.cursor.fetchall()]

    def ui_settings(self):
        for w in self.main_view.winfo_children(): w.destroy()
        self.create_header("إعدادات النظام وإدارة المستخدمين")
        scroll = ctk.CTkScrollableFrame(self.main_view, fg_color="transparent"); scroll.pack(fill="both", expand=True, padx=20, pady=10)
        f_shop = ctk.CTkFrame(scroll, corner_radius=15, border_width=1); f_shop.pack(fill="x", pady=10, padx=10)
        ctk.CTkLabel(f_shop, text=fix_arabic("إعدادات المحل", for_ui=True), font=FONT_BOLD, text_color=COLOR_CRIMSON).pack(pady=10)
        self.db.cursor.execute("SELECT key, value FROM settings"); sets = {k: v for k, v in self.db.cursor.fetchall()}
        self.s_entries = {}
        fields = [('shop_name', "اسم المحل"), ('phone', "رقم الهاتف"), ('location', "الموقع"), ('reg_points', "نقاط التسجيل المجانية")]
        for k, label in fields:
            r = ctk.CTkFrame(f_shop, fg_color="transparent"); r.pack(fill="x", padx=20, pady=5)
            ctk.CTkLabel(r, text=fix_arabic(label, for_ui=True), font=FONT_NORMAL_BOLD, width=150).pack(side="right")
            e = ctk.CTkEntry(r, font=FONT_NORMAL_BOLD, justify="right", height=40); e.pack(side="right", fill="x", expand=True, padx=10)
            e.insert(0, sets.get(k, "")); self.s_entries[k] = e
        ctk.CTkButton(f_shop, text=fix_arabic("حفظ الإعدادات", for_ui=True), command=self.save_settings, font=FONT_BOLD, fg_color="#2e7d32", height=45).pack(pady=15)
        f_user = ctk.CTkFrame(scroll, corner_radius=15, border_width=1); f_user.pack(fill="x", pady=10, padx=10)
        ctk.CTkLabel(f_user, text=fix_arabic("إدارة المستخدمين", for_ui=True), font=FONT_BOLD, text_color=COLOR_CRIMSON).pack(pady=10)
        u_row = ctk.CTkFrame(f_user, fg_color="transparent"); u_row.pack(fill="x", padx=20, pady=5)
        self.new_u = ctk.CTkEntry(u_row, placeholder_text=fix_arabic("اسم المستخدم", for_ui=True), height=40, justify="right", font=FONT_NORMAL_BOLD); self.new_u.pack(side="right", padx=5, expand=True, fill="x")
        self.new_p = ctk.CTkEntry(u_row, placeholder_text=fix_arabic("كلمة المرور", for_ui=True), height=40, justify="right", font=FONT_NORMAL_BOLD); self.new_p.pack(side="right", padx=5, expand=True, fill="x")
        self.new_r = ctk.CTkComboBox(u_row, values=["employee", "admin"], height=40); self.new_r.pack(side="right", padx=5)
        ctk.CTkButton(f_user, text=fix_arabic("إضافة مستخدم", for_ui=True), command=self.add_new_user, font=FONT_BOLD, fg_color=COLOR_CRIMSON_DARK, height=45).pack(pady=15)
        self.u_tree = ttk.Treeview(f_user, columns=("role", "user"), show="headings", height=5)
        for c, h in zip(self.u_tree["columns"], ["الصلاحية", "المستخدم"]): self.u_tree.heading(c, text=fix_arabic(h, for_ui=True))
        self.u_tree.pack(fill="x", padx=20, pady=10)
        
        btn_row = ctk.CTkFrame(f_user, fg_color="transparent"); btn_row.pack(fill="x", padx=20, pady=5)
        ctk.CTkButton(btn_row, text=fix_arabic("حذف المستخدم", for_ui=True), command=self.delete_user, font=FONT_BOLD, fg_color="#C62828", height=40).pack(side="left", padx=5, expand=True, fill="x")
        ctk.CTkButton(btn_row, text=fix_arabic("تعديل المستخدم", for_ui=True), command=self.edit_user_ui, font=FONT_BOLD, fg_color="#1565C0", height=40).pack(side="left", padx=5, expand=True, fill="x")
        
        self.refresh_users_tree()

    def delete_user(self):
        selected = self.u_tree.selection()
        if not selected:
            self.show_msg("تنبيه", "يرجى تحديد مستخدم للحذف"); return
        username = self.u_tree.item(selected[0])['values'][1]
        if username.lower() == "admin":
            self.show_msg("خطأ", "لا يمكن حذف المستخدم الرئيسي (admin)"); return
        if messagebox.askyesno(str("تأكيد الحذف"), str(f"هل أنت متأكد من حذف المستخدم '{username}'؟")):
            try:
                self.db.cursor.execute("DELETE FROM users WHERE username=?", (username,))
                self.db.conn.commit()
                self.log_action("حذف مستخدم", "users", f"المستخدم: {username}")
                self.show_msg("نجاح", "تم حذف المستخدم بنجاح"); self.refresh_users_tree()
            except sqlite3.Error as e: self.show_msg("خطأ", str(e))

    def edit_user_ui(self):
        selected = self.u_tree.selection()
        if not selected:
            self.show_msg("تنبيه", "يرجى تحديد مستخدم للتعديل"); return
        old_role, old_user = self.u_tree.item(selected[0])['values']
        
        ed = ctk.CTkToplevel(self); ed.title(fix_arabic("تعديل المستخدم", is_title=True)); ed.geometry("400x400"); ed.attributes("-topmost", True); ed.grab_set()
        ctk.CTkLabel(ed, text=fix_arabic(f"تعديل المستخدم: {old_user}", for_ui=True), font=FONT_BOLD, text_color=COLOR_CRIMSON).pack(pady=15)
        
        ctk.CTkLabel(ed, text=fix_arabic("الاسم الجديد:", for_ui=True), font=FONT_NORMAL_BOLD).pack(anchor="e", padx=25)
        e_user = ctk.CTkEntry(ed, font=FONT_NORMAL_BOLD, justify="right", height=40); e_user.pack(pady=5, padx=20, fill="x")
        e_user.insert(0, old_user)
        
        ctk.CTkLabel(ed, text=fix_arabic("كلمة المرور الجديدة:", for_ui=True), font=FONT_NORMAL_BOLD).pack(anchor="e", padx=25)
        e_pass = ctk.CTkEntry(ed, font=FONT_NORMAL_BOLD, justify="right", height=40, show="*"); e_pass.pack(pady=5, padx=20, fill="x")
        
        ctk.CTkLabel(ed, text=fix_arabic("الصلاحية:", for_ui=True), font=FONT_NORMAL_BOLD).pack(anchor="e", padx=25)
        e_role = ctk.CTkComboBox(ed, values=["employee", "admin"], height=40); e_role.pack(pady=5, padx=20, fill="x")
        e_role.set(old_role)
        
        def save_user_edit():
            new_u, new_p, new_r = e_user.get().strip(), e_pass.get().strip(), e_role.get()
            if not new_u: self.show_msg("خطأ", "الاسم لا يمكن أن يكون فارغاً"); return
            try:
                if new_p:
                    self.db.cursor.execute("UPDATE users SET username=?, password=?, role=? WHERE username=?", (new_u.lower(), new_p, new_r, old_user))
                else:
                    self.db.cursor.execute("UPDATE users SET username=?, role=? WHERE username=?", (new_u.lower(), new_r, old_user))
                self.db.conn.commit()
                self.log_action("تعديل مستخدم", "users", f"المستخدم القديم: {old_user}; الجديد: {new_u}")
                self.show_msg("نجاح", "تم تعديل بيانات المستخدم بنجاح"); ed.destroy(); self.refresh_users_tree()
            except sqlite3.Error as e: self.show_msg("خطأ", str(e))
            
        ctk.CTkButton(ed, text=fix_arabic("حفظ التعديلات", for_ui=True), command=save_user_edit, font=FONT_BOLD, fg_color="#2e7d32", height=45).pack(pady=20, padx=20, fill="x")

    def save_settings(self):
        try:
            for k, e in self.s_entries.items():
                value = e.get().strip()
                if k == "reg_points" and int(clean_float(value)) < 0:
                    raise ValueError("نقاط التسجيل لا يمكن أن تكون سالبة")
                self.db.cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (k, value))
            self.db.conn.commit(); self.log_action("تعديل الإعدادات", "settings", "إعدادات المحل"); self.show_msg("نجاح", "تم حفظ الإعدادات بنجاح. يرجى إعادة تشغيل البرنامج.")
        except (ValueError, sqlite3.Error) as exc:
            self.db.conn.rollback(); self.show_msg("تعذر حفظ الإعدادات", str(exc))

    def add_new_user(self):
        u, p, r = self.new_u.get().strip(), self.new_p.get().strip(), self.new_r.get()
        if not u or not p:
            self.show_msg("تنبيه", "يرجى إدخال اسم المستخدم وكلمة المرور"); return
        try:
            self.db.cursor.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)", (u.lower(), p, r))
            self.db.conn.commit(); self.log_action("إضافة مستخدم", "users", f"المستخدم: {u}; الصلاحية: {r}"); self.refresh_users_tree(); self.show_msg("نجاح", "تم إضافة المستخدم")
        except sqlite3.IntegrityError:
            self.show_msg("خطأ", "اسم المستخدم موجود مسبقاً")

    def refresh_users_tree(self):
        for i in self.u_tree.get_children(): self.u_tree.delete(i)
        self.db.cursor.execute("SELECT role, username FROM users")
        [self.u_tree.insert("", "end", values=(r[0], r[1])) for r in self.db.cursor.fetchall()]

    def refresh_customers(self):
        for i in self.c_tree.get_children(): self.c_tree.delete(i)
        q = self.c_search.get().strip()
        if q:
            self.db.cursor.execute("SELECT points, phone, name FROM customers WHERE name LIKE ? ORDER BY name ASC", (f"%{q}%",))
        else:
            self.db.cursor.execute("SELECT points, phone, name FROM customers ORDER BY name ASC")
        for r in self.db.cursor.fetchall():
            # r[1] is phone. Check note with robust variations (with/without leading zero)
            p_val = str(r[1]).strip()
            p_alt = p_val[1:] if p_val.startswith('0') else '0' + p_val
            self.db.cursor.execute("SELECT note FROM customer_notes WHERE phone=? OR phone=?", (p_val, p_alt))
            n_res = self.db.cursor.fetchone()
            note_str = "يوجد ملاحظة ⚠️" if n_res and n_res[0] else "-"
            # Ensure phone is formatted as string explicitly
            self.c_tree.insert("", "end", values=(note_str, r[0], str(r[1]), fix_arabic(r[2], for_ui=True)))

    def export_customers(self):
        try:
            df = pd.read_sql_query("SELECT name, phone, points FROM customers", self.db.conn)
            df.to_excel("Customers.xlsx", index=False); self.show_msg("نجاح", "تم التصدير")
        except Exception as e: self.show_msg("خطأ", str(e))

    def ui_advanced_reports(self):
        for w in self.main_view.winfo_children(): w.destroy()
        self.create_header("التقارير المتقدمة")
        
        f_top = ctk.CTkFrame(self.main_view, fg_color="transparent"); f_top.pack(fill="x", padx=15, pady=10)
        ctk.CTkLabel(f_top, text=fix_arabic("من تاريخ:", for_ui=True), font=FONT_BOLD, text_color=COLOR_CRIMSON).pack(side="right", padx=5)
        self.ar_from = ctk.CTkEntry(f_top, placeholder_text="YYYY-MM-DD", font=FONT_NORMAL_BOLD, width=130, justify="right", corner_radius=8); self.ar_from.pack(side="right", padx=5)
        ctk.CTkLabel(f_top, text=fix_arabic("إلى تاريخ:", for_ui=True), font=FONT_BOLD, text_color=COLOR_CRIMSON).pack(side="right", padx=5)
        self.ar_to = ctk.CTkEntry(f_top, placeholder_text="YYYY-MM-DD", font=FONT_NORMAL_BOLD, width=130, justify="right", corner_radius=8); self.ar_to.pack(side="right", padx=5)
        
        ctk.CTkLabel(f_top, text=fix_arabic("النوع:", for_ui=True), font=FONT_BOLD, text_color=COLOR_CRIMSON).pack(side="right", padx=5)
        self.ar_type = ctk.CTkComboBox(f_top, values=[fix_arabic("الكل", for_ui=True), fix_arabic("مبيعات", for_ui=True), fix_arabic("صيانة", for_ui=True), fix_arabic("حوالات وفواتير", for_ui=True)], font=FONT_NORMAL_BOLD, width=150, justify="right", corner_radius=8)
        self.ar_type.pack(side="right", padx=5); self.ar_type.set(fix_arabic("الكل", for_ui=True))
        
        ctk.CTkButton(f_top, text=fix_arabic("عرض", for_ui=True), command=self.refresh_advanced_reports, font=FONT_BOLD, width=90, fg_color=COLOR_CRIMSON, height=38).pack(side="right", padx=10)
        ctk.CTkButton(f_top, text=fix_arabic("تصدير إكسل", for_ui=True), command=self.export_advanced_reports, font=FONT_BOLD, width=110, fg_color="#2e7d32", height=38).pack(side="left", padx=10)
        
        self.ar_tree = ttk.Treeview(self.main_view, columns=("user", "time", "desc", "amount", "date", "client", "type"), show="headings")
        for col, head in zip(self.ar_tree["columns"], ["المستخدم", "الساعة", "التفاصيل", "المبلغ", "التاريخ", "العميل", "نوع الخدمة"]): 
            self.ar_tree.heading(col, text=fix_arabic(head, for_ui=True))
        self.ar_tree.pack(fill="both", expand=True, padx=15, pady=10)
        self.refresh_advanced_reports()

    def _advanced_rows(self):
        start, end, tp = self.ar_from.get(), self.ar_to.get(), self.ar_type.get()
        where, params = self.date_filter("date", start, end)
        all_lbl, sales_lbl = fix_arabic("الكل", for_ui=True), fix_arabic("مبيعات", for_ui=True)
        maint_lbl, trans_lbl = fix_arabic("صيانة", for_ui=True), fix_arabic("حوالات وفواتير", for_ui=True)
        data = []
        if tp in [all_lbl, sales_lbl]:
            self.db.cursor.execute("SELECT name, date, total, code, time, user, payment_method FROM sales" + (" " + where if where else ""), params)
            for r in self.db.cursor.fetchall(): data.append(("مبيعات", r[0] or "نقدي", r[1], float(r[2] or 0), f"منتج: {r[3]} | الدفع: {r[6] or 'نقدي'}", r[4], r[5] or "admin"))
        if tp in [all_lbl, maint_lbl]:
            self.db.cursor.execute("SELECT client_name, date, revenue, repair_desc, time, user FROM maintenance" + (" " + where if where else ""), params)
            for r in self.db.cursor.fetchall(): data.append(("صيانة", r[0] or "-", r[1], float(r[2] or 0), r[3] or "", r[4], r[5] or "admin"))
        if tp in [all_lbl, trans_lbl]:
            self.db.cursor.execute("SELECT type, client_name, date, (amount + commission), reference, time, user FROM transfers" + (" " + where if where else ""), params)
            for r in self.db.cursor.fetchall(): data.append((r[0] or "حوالة", r[1] or "-", r[2], float(r[3] or 0), f"مرجع: {r[4] or '-'}", r[5], r[6] or "admin"))
        return sorted(data, key=lambda x: (x[2], x[5]), reverse=True)

    def refresh_advanced_reports(self):
        for i in self.ar_tree.get_children(): self.ar_tree.delete(i)
        try:
            for row in self._advanced_rows():
                self.ar_tree.insert("", "end", values=(row[6], row[5], fix_arabic(row[4], for_ui=True), f"{row[3]:.2f}", row[2], fix_arabic(row[1], for_ui=True), fix_arabic(row[0], for_ui=True)))
        except (ValueError, sqlite3.Error) as exc:
            self.show_msg("خطأ في التقرير", str(exc))

    def export_advanced_reports(self):
        try:
            rows = self._advanced_rows()
            df = pd.DataFrame([{"نوع الخدمة": r[0], "العميل": r[1], "التاريخ": r[2], "المبلغ": r[3], "التفاصيل": r[4], "الساعة": r[5], "المستخدم": r[6]} for r in rows])
            df.to_excel("Advanced_Reports.xlsx", index=False)
            self.log_action("تصدير تقرير", "advanced_reports", f"عدد السجلات: {len(rows)}")
            self.show_msg("نجاح", "تم تصدير التقرير إلى Advanced_Reports.xlsx بنجاح")
        except (ValueError, sqlite3.Error, OSError, ImportError) as exc:
            self.show_msg("خطأ", str(exc))

    def ui_expenses(self):
        for w in self.main_view.winfo_children(): w.destroy()
        self.create_header("المصاريف")
        f = ctk.CTkFrame(self.main_view, fg_color="transparent"); f.pack(fill="x", padx=15, pady=5)
        self.e_desc = ctk.CTkEntry(f, placeholder_text=fix_arabic("الوصف", for_ui=True), width=300, height=45, justify="right", corner_radius=10); self.e_desc.pack(side="right", padx=5)
        self.e_amt = ctk.CTkEntry(f, placeholder_text=fix_arabic("المبلغ", for_ui=True), height=45, justify="right", corner_radius=10); self.e_amt.pack(side="right", padx=5)
        ctk.CTkButton(f, text=fix_arabic("إضافة", for_ui=True), command=self.add_expense, font=FONT_BOLD, fg_color=COLOR_CRIMSON, height=45).pack(side="right", padx=5)
        self.exp_tree = ttk.Treeview(self.main_view, columns=("date", "amount", "desc"), show="headings")
        for col, head in zip(self.exp_tree["columns"], ["التاريخ", "المبلغ", "الوصف"]): self.exp_tree.heading(col, text=fix_arabic(head, for_ui=True))
        self.exp_tree.pack(fill="both", expand=True, padx=15, pady=10)
        self.db.cursor.execute("SELECT date, amount, desc FROM expenses ORDER BY id DESC"); [self.exp_tree.insert("", "end", values=(r[0], r[1], fix_arabic(r[2], for_ui=True))) for r in self.db.cursor.fetchall()]

    def add_expense(self):
        d, a = self.e_desc.get().strip(), self.e_amt.get().strip()
        if not d or not a:
            self.show_msg("تنبيه", "يرجى إدخال وصف المصروف والمبلغ"); return
        try:
            amount = self.positive_number(a, "المبلغ")
            now = datetime.datetime.now()
            self.db.cursor.execute("INSERT INTO expenses (desc, amount, date, time, user) VALUES (?,?,?,?,?)", (d, amount, now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"), self.current_user))
            self.db.conn.commit(); self.log_action("تسجيل مصروف", "expenses", f"الوصف: {d}; المبلغ: {amount:.2f}"); self.ui_expenses()
        except (ValueError, sqlite3.Error) as exc:
            self.db.conn.rollback(); self.show_msg("تعذر تسجيل المصروف", str(exc))

    def draw_visual_dashboard(self, parent):
        chart_frame = ctk.CTkFrame(parent, corner_radius=15, border_width=1)
        chart_frame.pack(fill="x", pady=10, padx=10)
        ctk.CTkLabel(chart_frame, text=fix_arabic("منحنيات الأداء والخدمات - آخر 30 يوماً", for_ui=True), font=FONT_BOLD, text_color=COLOR_CRIMSON).pack(pady=8)
        
        # Build 3 separate sub-canvases for Sales, Maintenance, and Transfers over last 30 days
        services = [
            ("المبيعات (Sales)", "SELECT date, COALESCE(SUM(total),0) FROM sales GROUP BY date ORDER BY date DESC LIMIT 30", "#1565C0"),
            ("الصيانة (Maintenance)", "SELECT date, COALESCE(SUM(revenue),0) FROM maintenance GROUP BY date ORDER BY date DESC LIMIT 30", "#E65100"),
            ("عمولات الحوالات (Transfers)", "SELECT date, COALESCE(SUM(commission),0) FROM transfers GROUP BY date ORDER BY date DESC LIMIT 30", "#00838F")
        ]
        
        for title, query, color in services:
            sub_f = ctk.CTkFrame(chart_frame, fg_color="transparent")
            sub_f.pack(fill="x", padx=10, pady=5)
            ctk.CTkLabel(sub_f, text=fix_arabic(title, for_ui=True), font=FONT_BOLD, text_color=color).pack(anchor="w", padx=15)
            canvas = ctk.CTkCanvas(sub_f, height=180, background=COLOR_WHITE, highlightthickness=0)
            canvas.pack(fill="x", padx=15, pady=(0, 10))
            
            self.db.cursor.execute(query)
            rows = list(reversed(self.db.cursor.fetchall()))
            if not rows:
                canvas.create_text(450, 90, text=fix_arabic("لا توجد بيانات كافية لهذه الفترة", for_ui=True), font=FONT_BOLD, fill=COLOR_TEXT_DARK)
                continue
            width, bottom, top = 880, 150, 20
            canvas.configure(width=width)
            max_val = max(float(r[1] or 0) for r in rows) or 1.0
            canvas.create_line(50, top, 50, bottom, fill="#888888", width=2)
            canvas.create_line(50, bottom, width-20, bottom, fill="#888888", width=2)
            points = []
            step = max(10, (width - 80) / max(1, len(rows) - 1))
            for idx, (dt, val) in enumerate(rows):
                x = 50 + idx * step
                y = bottom - (float(val or 0) / max_val) * (bottom - top)
                points.append((x, y))
                if idx % max(1, len(rows)//6) == 0:
                    canvas.create_text(x, bottom + 12, text=str(dt)[5:], font=("Arial", 9), fill="#444444")
            if len(points) > 1:
                for p1, p2 in zip(points, points[1:]):
                    canvas.create_line(*p1, *p2, fill=color, width=3)
            for x, y in points:
                canvas.create_oval(x-3, y-3, x+3, y+3, fill=color, outline=color)

    def ui_analytics(self):
        for w in self.main_view.winfo_children(): w.destroy()
        self.create_header("تقارير الأداء والتحليلات الذكية")
        
        scroll = ctk.CTkScrollableFrame(self.main_view, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=20, pady=10)
        
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        
        # 1. Daily & Instant Stats Card
        f_daily = ctk.CTkFrame(scroll, corner_radius=15, fg_color="#E3F2FD", border_color="#1565C0", border_width=2)
        f_daily.pack(fill="x", pady=10, padx=10)
        ctk.CTkLabel(f_daily, text=fix_arabic(f"الأداء اليومي والفوري (تاريخ اليوم: {today})", for_ui=True), font=("Arial", 18, "bold"), text_color="#0D47A1").pack(pady=10)
        
        self.db.cursor.execute("SELECT SUM(total), SUM(buy_cost) FROM sales WHERE date=?", (today,))
        d_res = self.db.cursor.fetchone(); d_rev = d_res[0] or 0; d_cogs = d_res[1] or 0; d_prof = d_rev - d_cogs
        
        self.db.cursor.execute("SELECT SUM(revenue) FROM maintenance WHERE date=?", (today,))
        d_maint = self.db.cursor.fetchone()[0] or 0

        self.db.cursor.execute("SELECT SUM(commission) FROM transfers WHERE date=?", (today,))
        d_trans_comm = self.db.cursor.fetchone()[0] or 0
        
        row_d = ctk.CTkFrame(f_daily, fg_color="transparent"); row_d.pack(fill="x", padx=20, pady=10)
        ctk.CTkLabel(row_d, text=fix_arabic(f"مبيعات اليوم: {d_rev:.2f} {CURRENCY}", for_ui=True), font=FONT_BOLD, text_color="#1565C0").pack(side="right", padx=15)
        ctk.CTkLabel(row_d, text=fix_arabic(f"أرباح المبيعات: {d_prof:.2f} {CURRENCY}", for_ui=True), font=FONT_BOLD, text_color="#2E7D32").pack(side="right", padx=15)
        ctk.CTkLabel(row_d, text=fix_arabic(f"إيرادات الصيانة: {d_maint:.2f} {CURRENCY}", for_ui=True), font=FONT_BOLD, text_color="#E65100").pack(side="right", padx=15)
        ctk.CTkLabel(row_d, text=fix_arabic(f"عمولات الحوالات: {d_trans_comm:.2f} {CURRENCY}", for_ui=True), font=FONT_BOLD, text_color="#00838F").pack(side="right", padx=15)
        
        self.draw_visual_dashboard(scroll)
        # 2. Top Selling Products Table
        f_top = ctk.CTkFrame(scroll, corner_radius=15, border_width=1)
        f_top.pack(fill="x", pady=10, padx=10)
        ctk.CTkLabel(f_top, text=fix_arabic("المنتجات الأكثر طلباً ومبيعاً", for_ui=True), font=FONT_BOLD, text_color=COLOR_CRIMSON).pack(pady=10)
        
        top_tree = ttk.Treeview(f_top, columns=("rev", "qty", "name"), show="headings", height=5)
        for c, h in zip(top_tree["columns"], ["إجمالي الإيرادات", "الكمية المباعة", "اسم المنتج"]): top_tree.heading(c, text=fix_arabic(h, for_ui=True))
        top_tree.pack(fill="x", padx=20, pady=10)
        
        self.db.cursor.execute("SELECT name, SUM(qty), SUM(total) FROM sales GROUP BY name ORDER BY SUM(qty) DESC LIMIT 5")
        for r in self.db.cursor.fetchall():
            top_tree.insert("", "end", values=(f"{r[2]:.2f} {CURRENCY}", r[1], fix_arabic(r[0], for_ui=True)))
            
        # 3. Peak Time Analysis
        f_peak = ctk.CTkFrame(scroll, corner_radius=15, border_width=1)
        f_peak.pack(fill="x", pady=10, padx=10)
        ctk.CTkLabel(f_peak, text=fix_arabic("تحليل أوقات الذروة (حسب ساعة البيع)", for_ui=True), font=FONT_BOLD, text_color=COLOR_CRIMSON).pack(pady=10)
        
        peak_tree = ttk.Treeview(f_peak, columns=("count", "hour"), show="headings", height=5)
        for c, h in zip(peak_tree["columns"], ["عدد العمليات", "الساعة"]): peak_tree.heading(c, text=fix_arabic(h, for_ui=True))
        peak_tree.pack(fill="x", padx=20, pady=10)
        
        self.db.cursor.execute("SELECT SUBSTR(time, 1, 2) AS hr, COUNT(*) FROM sales GROUP BY hr ORDER BY COUNT(*) DESC LIMIT 5")
        for r in self.db.cursor.fetchall():
            peak_tree.insert("", "end", values=(r[1], fix_arabic(f"الساعة {r[0]}:00", for_ui=True)))

    def ui_reports(self):
        for w in self.main_view.winfo_children(): w.destroy()
        self.create_header("التقارير والأرباح")
        
        # Filter frame at the top
        f_top = ctk.CTkFrame(self.main_view, fg_color="transparent"); f_top.pack(fill="x", padx=20, pady=(0, 10))
        ctk.CTkButton(f_top, text=fix_arabic("جرد الكاش اليومي", for_ui=True), command=self.show_cash_reconciliation, font=FONT_BOLD, fg_color="#2e7d32", height=40, width=160).pack(side="left", padx=5)
        ctk.CTkButton(f_top, text=fix_arabic("تقرير الأرباح والخسائر P&L", for_ui=True), command=self.show_p_and_l_statement, font=FONT_BOLD, fg_color="#006064", height=40, width=220).pack(side="left", padx=5)
        
        ctk.CTkButton(f_top, text=fix_arabic("فلترة", for_ui=True), command=self.refresh_reports, font=FONT_BOLD, fg_color=COLOR_CRIMSON, height=40, width=90).pack(side="right", padx=5)
        self.rep_to = ctk.CTkEntry(f_top, placeholder_text="YYYY-MM-DD", width=130, height=40, justify="right"); self.rep_to.pack(side="right", padx=5)
        ctk.CTkLabel(f_top, text=fix_arabic("إلى:", for_ui=True), font=FONT_BOLD, text_color=COLOR_CRIMSON).pack(side="right", padx=2)
        self.rep_from = ctk.CTkEntry(f_top, placeholder_text="YYYY-MM-DD", width=130, height=40, justify="right"); self.rep_from.pack(side="right", padx=5)
        ctk.CTkLabel(f_top, text=fix_arabic("من:", for_ui=True), font=FONT_BOLD, text_color=COLOR_CRIMSON).pack(side="right", padx=2)

        self.rep_scroll = ctk.CTkScrollableFrame(self.main_view, fg_color="transparent"); self.rep_scroll.pack(fill="both", expand=True, padx=10, pady=10)
        self.refresh_reports()

    def refresh_reports(self):
        for w in self.rep_scroll.winfo_children(): w.destroy()
        try:
            start, end = self.rep_from.get(), self.rep_to.get()
            where, params = self.date_filter("date", start, end)
            def scalar(query, values=params):
                self.db.cursor.execute(query + (" " + where if where else ""), values)
                return self.db.cursor.fetchone()[0] or 0.0
            self.db.cursor.execute("SELECT COALESCE(SUM(total),0), COALESCE(SUM(buy_cost),0) FROM sales" + (" " + where if where else ""), params)
            s_rev, s_cogs = (self.db.cursor.fetchone() or (0, 0)); s_rev, s_cogs = float(s_rev or 0), float(s_cogs or 0)
            self.db.cursor.execute("SELECT COALESCE(SUM(revenue),0), COALESCE(SUM(internal_cost),0) FROM maintenance" + (" " + where if where else ""), params)
            m_rev, m_cost = (self.db.cursor.fetchone() or (0, 0)); m_rev, m_cost = float(m_rev or 0), float(m_cost or 0)
            t_comm = float(scalar("SELECT COALESCE(SUM(commission),0) FROM transfers"))
            exp = float(scalar("SELECT COALESCE(SUM(amount),0) FROM expenses"))
            pur_total = float(scalar("SELECT COALESCE(SUM(qty * cost),0) FROM purchases"))
            self.db.cursor.execute("SELECT COALESCE(SUM(buy_price * stock),0), COALESCE(SUM(sell_price * stock),0) FROM products")
            stock_buy, stock_sell = self.db.cursor.fetchone(); stock_buy, stock_sell = float(stock_buy or 0), float(stock_sell or 0)
        except ValueError as exc:
            self.show_msg("فلترة غير صحيحة", str(exc)); return
        except sqlite3.Error as exc:
            self.show_msg("خطأ في التقرير", str(exc)); return

        s_profit, m_profit = s_rev - s_cogs, m_rev - m_cost
        data = [("إجمالي المبيعات", s_rev, "#1565C0"), ("قيمة المنتجات المباعة (من رأس المال - COGS)", s_cogs, "#D32F2F"), ("ربح المبيعات الصافي", s_profit, "#2E7D32"), ("إجمالي إيرادات الصيانة", m_rev, "#1565C0"), ("تكلفة قطع الصيانة", m_cost, "#D32F2F"), ("ربح الصيانة الصافي", m_profit, "#2E7D32"), ("إجمالي عمولات الحوالات والفواتير", t_comm, "#00838F"), ("إجمالي المصاريف", exp, "#E65100"), ("إجمالي المشتريات (الكمية × تكلفة القطعة)", pur_total, "#C2185B")]
        for label, val, color in data:
            row = ctk.CTkFrame(self.rep_scroll, height=70, corner_radius=12); row.pack(fill="x", pady=4, padx=20)
            ctk.CTkLabel(row, text=fix_arabic(label, for_ui=True), font=FONT_BOLD).pack(side="right", padx=20)
            ctk.CTkLabel(row, text=f"{val:.2f} {CURRENCY}", font=FONT_BOLD, text_color=color).pack(side="left", padx=20)

        inv_val_frame = ctk.CTkFrame(self.rep_scroll, height=90, corner_radius=15, fg_color="#E8F5E9", border_color="#2E7D32", border_width=2); inv_val_frame.pack(fill="x", pady=10, padx=20)
        ctk.CTkLabel(inv_val_frame, text=fix_arabic("تقييم المخزون الحالي", for_ui=True), font=("Arial", 16, "bold"), text_color="#1B5E20").pack(pady=2)
        sub_inv = ctk.CTkFrame(inv_val_frame, fg_color="transparent"); sub_inv.pack(fill="x", padx=20)
        ctk.CTkLabel(sub_inv, text=fix_arabic(f"قيمة المخزون (سعر الشراء): {stock_buy:.2f} {CURRENCY}", for_ui=True), font=FONT_BOLD, text_color="#2E7D32").pack(side="right", padx=10)
        ctk.CTkLabel(sub_inv, text=fix_arabic(f"القيمة المتوقعة (سعر البيع): {stock_sell:.2f} {CURRENCY}", for_ui=True), font=FONT_BOLD, text_color="#1565C0").pack(side="left", padx=10)
        net_profit = s_profit + m_profit + t_comm - exp
        f_p = ctk.CTkFrame(self.rep_scroll, height=110, corner_radius=15, fg_color="#FFFDE7", border_color="#F57F17", border_width=2); f_p.pack(fill="x", pady=15, padx=20)
        ctk.CTkLabel(f_p, text=fix_arabic("صافي الربح الفعلي", for_ui=True), font=("Arial", 20, "bold"), text_color="#E65100").pack(pady=5)
        ctk.CTkLabel(f_p, text=f"{net_profit:.2f} {CURRENCY}", font=("Arial", 28, "bold"), text_color="#2E7D32").pack(pady=5)

    def show_p_and_l_statement(self):
        try:
            start, end = self.rep_from.get(), self.rep_to.get()
            where, params = self.date_filter("date", start, end)
            
            def scalar(query, values=params):
                self.db.cursor.execute(query + (" " + where if where else ""), values)
                return float(self.db.cursor.fetchone()[0] or 0.0)

            # Revenue Components
            s_rev = scalar("SELECT SUM(total) FROM sales")
            m_rev = scalar("SELECT SUM(revenue) FROM maintenance")
            t_comm = scalar("SELECT SUM(commission) FROM transfers")
            total_revenue = s_rev + m_rev + t_comm

            # Cost Components
            s_cogs = scalar("SELECT SUM(buy_cost) FROM sales")
            m_cost = scalar("SELECT SUM(internal_cost) FROM maintenance")
            expenses = scalar("SELECT SUM(amount) FROM expenses")
            total_costs = s_cogs + m_cost + expenses

            net_profit = total_revenue - total_costs
            
            win = ctk.CTkToplevel(self); win.title(fix_arabic("تقرير الأرباح والخسائر P&L Statement", is_title=True))
            win.geometry("600x750"); win.attributes("-topmost", True); win.grab_set()
            
            ctk.CTkLabel(win, text=fix_arabic("بيان الأرباح والخسائر الرسمي", for_ui=True), font=("Arial", 22, "bold"), text_color=COLOR_CRIMSON).pack(pady=20)
            ctk.CTkLabel(win, text=fix_arabic(f"الفترة: {start or 'البداية'} إلى {end or 'اليوم'}", for_ui=True), font=FONT_NORMAL_BOLD).pack(pady=5)
            
            # 1. Revenue Frame
            f_rev = ctk.CTkFrame(win, fg_color="#E3F2FD", corner_radius=15, border_width=1); f_rev.pack(fill="x", padx=30, pady=10)
            ctk.CTkLabel(f_rev, text=fix_arabic("أولاً: إجمالي الإيرادات (Revenue)", for_ui=True), font=FONT_BOLD, text_color="#0D47A1").pack(pady=10)
            rev_items = [("مبيعات المنتجات", s_rev), ("إيرادات الصيانة", m_rev), ("عمولات الخدمات", t_comm)]
            for lbl, val in rev_items:
                r = ctk.CTkFrame(f_rev, fg_color="transparent"); r.pack(fill="x", padx=20, pady=2)
                ctk.CTkLabel(r, text=fix_arabic(lbl, for_ui=True), font=FONT_NORMAL_BOLD).pack(side="right")
                ctk.CTkLabel(r, text=f"{val:.2f} {CURRENCY}", font=FONT_BOLD).pack(side="left")
            ctk.CTkLabel(f_rev, text=f"-------------------------", text_color="gray").pack()
            ctk.CTkLabel(f_rev, text=fix_arabic(f"مجموع الإيرادات: {total_revenue:.2f} {CURRENCY}", for_ui=True), font=FONT_BOLD, text_color="#1565C0").pack(pady=10)

            # 2. Costs Frame
            f_cost = ctk.CTkFrame(win, fg_color="#FFEBEE", corner_radius=15, border_width=1); f_cost.pack(fill="x", padx=30, pady=10)
            ctk.CTkLabel(f_cost, text=fix_arabic("ثانياً: التكاليف والمصاريف (Costs)", for_ui=True), font=FONT_BOLD, text_color="#C62828").pack(pady=10)
            cost_items = [("تكلفة البضاعة المباعة", s_cogs), ("تكلفة الصيانة الداخلية", m_cost), ("المصاريف التشغيلية", expenses)]
            for lbl, val in cost_items:
                r = ctk.CTkFrame(f_cost, fg_color="transparent"); r.pack(fill="x", padx=20, pady=2)
                ctk.CTkLabel(r, text=fix_arabic(lbl, for_ui=True), font=FONT_NORMAL_BOLD).pack(side="right")
                ctk.CTkLabel(r, text=f"{val:.2f} {CURRENCY}", font=FONT_BOLD).pack(side="left")
            ctk.CTkLabel(f_cost, text=f"-------------------------", text_color="gray").pack()
            ctk.CTkLabel(f_cost, text=fix_arabic(f"مجموع التكاليف: {total_costs:.2f} {CURRENCY}", for_ui=True), font=FONT_BOLD, text_color="#D32F2F").pack(pady=10)

            # 3. Net Profit Frame
            f_net = ctk.CTkFrame(win, fg_color="#E8F5E9", corner_radius=15, border_width=2, border_color="#2E7D32"); f_net.pack(fill="x", padx=30, pady=20)
            ctk.CTkLabel(f_net, text=fix_arabic("صافي الربح الحقيقي (Net Profit)", for_ui=True), font=("Arial", 20, "bold"), text_color="#1B5E20").pack(pady=10)
            ctk.CTkLabel(f_net, text=f"{net_profit:.2f} {CURRENCY}", font=("Arial", 32, "bold"), text_color="#2E7D32").pack(pady=10)
            ctk.CTkLabel(f_net, text=fix_arabic("هذا المبلغ يمثل صافي الربح القابل للسحب بعد تغطية كافة التكاليف.", for_ui=True), font=("Arial", 11), text_color="#388E3C").pack(pady=5)

            ctk.CTkButton(win, text=fix_arabic("إغلاق التقرير", for_ui=True), command=win.destroy, font=FONT_BOLD, fg_color=COLOR_CRIMSON, height=45).pack(pady=20)

        except Exception as e:
            self.show_msg("خطأ في التقرير", str(e))

    def show_cash_reconciliation(self):
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        
        # Payment breakdown queries
        def get_pm_sum(table, col, pm, extra_where=""):
            w = f"date=? AND payment_method=?" + (f" AND ({extra_where})" if extra_where else "")
            self.db.cursor.execute(f"SELECT COALESCE(SUM({col}),0) FROM {table} WHERE {w}", (today, pm))
            return self.db.cursor.fetchone()[0] or 0.0

        # Sales by PM
        s_cash = get_pm_sum("sales", "total", "Cash")
        s_visa = get_pm_sum("sales", "total", "Visa")
        s_cliq = get_pm_sum("sales", "total", "CLIQ")
        s_sum = s_cash + s_visa + s_cliq
        
        # Maintenance by PM
        m_cash = get_pm_sum("maintenance", "revenue", "Cash")
        m_visa = get_pm_sum("maintenance", "revenue", "Visa")
        m_cliq = get_pm_sum("maintenance", "revenue", "CLIQ")
        m_sum = m_cash + m_visa + m_cliq
        
        # Transfers by PM
        def get_transfer_pm(t_type, pm):
            self.db.cursor.execute(f"SELECT COALESCE(SUM(amount + commission),0) FROM transfers WHERE type=? AND payment_method=? AND date=?", (t_type, pm, today))
            return self.db.cursor.fetchone()[0] or 0.0

        # دفع فاتورة حسب طريقة الدفع
        def get_bill_pm(pm):
            self.db.cursor.execute("SELECT COALESCE(SUM(amount + commission),0) FROM transfers WHERE type='دفع فاتورة' AND payment_method=? AND date=?", (pm, today))
            return self.db.cursor.fetchone()[0] or 0.0

        # دخول حوالة حسب طريقة الدفع
        def get_in_pm(pm):
            self.db.cursor.execute("SELECT COALESCE(SUM(amount + commission),0) FROM transfers WHERE type='دخول حوالة' AND payment_method=? AND date=?", (pm, today))
            return self.db.cursor.fetchone()[0] or 0.0

        # خروج حوالة بجميع طرق الدفع (يُخصم النقد الصافي من الدرج: amount - commission)
        def get_out_cash_all():
            self.db.cursor.execute("SELECT COALESCE(SUM(amount - commission),0) FROM transfers WHERE type='خروج حوالة' AND date=?", (today,))
            return self.db.cursor.fetchone()[0] or 0.0

        # خروج حوالة عبر الفيزا أو الكليك (يزيد رصيد الفيزا أو الكليك بقيمة العقد الإجمالية = amount)
        def get_out_digital(pm):
            self.db.cursor.execute("SELECT COALESCE(SUM(amount),0) FROM transfers WHERE type='خروج حوالة' AND payment_method=? AND date=?", (pm, today))
            return self.db.cursor.fetchone()[0] or 0.0

        t_in_cash, t_in_visa, t_in_cliq = get_in_pm("Cash"), get_in_pm("Visa"), get_in_pm("CLIQ")
        b_pay_cash, b_pay_visa, b_pay_cliq = get_bill_pm("Cash"), get_bill_pm("Visa"), get_bill_pm("CLIQ")
        t_out_net_all = get_out_cash_all() # الصافي المخصوم من الدرج لكافة حوالات الخروج
        t_out_visa_raw = get_out_digital("Visa")
        t_out_cliq_raw = get_out_digital("CLIQ")

        # إجمالي الفيزا والكليك: مبيعات + صيانة + دخول حوالة + دفع فاتورة + خروج حوالة (بكامل القيمة)
        total_visa = s_visa + m_visa + t_in_visa + b_pay_visa + t_out_visa_raw
        total_cliq = s_cliq + m_cliq + t_in_cliq + b_pay_cliq + t_out_cliq_raw
        
        # الكاش المفترض في الدرج:
        # - المبيعات النقدية + إيرادات الصيانة النقدية
        # - دخول حوالة نقداً
        # - دفع فاتورة نقداً
        # - خروج حوالة (تخصم من الدرج بغض النظر عن طريقة الدفع لأن النقد يخرج فعلياً من الدرج للعميل)
        expected_cash = s_cash + m_cash + t_in_cash + b_pay_cash - t_out_net_all
        
        win = ctk.CTkToplevel(self)
        win.title(fix_arabic("جرد الكاش اليومي وتعدد الدفع", is_title=True))
        win.geometry("550x620")
        win.attributes("-topmost", True)
        win.grab_set()
        
        scroll = ctk.CTkScrollableFrame(win, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=10, pady=10)
        
        ctk.CTkLabel(scroll, text=fix_arabic(f"جرد الكاش وتفصيل الدفع لتاريخ: {today}", for_ui=True), font=("Arial", 18, "bold"), text_color=COLOR_CRIMSON).pack(pady=10)
        
        # Breakdown card
        f_break = ctk.CTkFrame(scroll, fg_color=COLOR_BG_LIGHT, corner_radius=15)
        f_break.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(f_break, text=fix_arabic("إجمالي العمليات حسب طريقة الدفع", for_ui=True), font=FONT_BOLD, text_color="#1565C0").pack(pady=8)
        
        pm_items = [
            ("إجمالي الكاش (Cash):", s_cash + m_cash + t_in_cash + b_pay_cash - t_out_net_all),
            ("إجمالي الفيزا (Visa):", total_visa),
            ("إجمالي الكليك (CLIQ):", total_cliq)
        ]
        for lbl, val in pm_items:
            row = ctk.CTkFrame(f_break, fg_color="transparent")
            row.pack(fill="x", padx=15, pady=4)
            ctk.CTkLabel(row, text=fix_arabic(lbl, for_ui=True), font=FONT_NORMAL_BOLD).pack(side="right", padx=10)
            ctk.CTkLabel(row, text=f"{val:.2f} {CURRENCY}", font=FONT_BOLD, text_color="#2E7D32").pack(side="left", padx=10)

        f_box = ctk.CTkFrame(scroll, fg_color=COLOR_BG_LIGHT, corner_radius=15)
        f_box.pack(fill="both", expand=True, padx=10, pady=10)
        ctk.CTkLabel(f_box, text=fix_arabic("حركة الدرج النقدي اليومية", for_ui=True), font=FONT_BOLD, text_color=COLOR_CRIMSON).pack(pady=8)
        
        items = [
            ("المبيعات النقدية:", s_cash),
            ("إيرادات الصيانة النقدية:", m_cash),
            ("استلام حوالة كاش (مع العمولة):", t_in_cash),
            ("دفع فاتورة كاش (مع العمولة):", b_pay_cash),
            ("ارسال حوالة كاش (مخصوماً منها العمولة):", -t_out_net_all)
        ]
        
        for lbl, val in items:
            row = ctk.CTkFrame(f_box, fg_color="transparent")
            row.pack(fill="x", padx=15, pady=5)
            ctk.CTkLabel(row, text=fix_arabic(lbl, for_ui=True), font=FONT_NORMAL_BOLD).pack(side="right", padx=10)
            ctk.CTkLabel(row, text=f"{val:.2f} {CURRENCY}", font=FONT_BOLD, text_color=COLOR_CRIMSON_DARK if val < 0 else COLOR_TEXT_DARK).pack(side="left", padx=10)
            
        tot_frame = ctk.CTkFrame(win, height=70, fg_color="#E8F5E9", corner_radius=12)
        tot_frame.pack(fill="x", padx=20, pady=15)
        ctk.CTkLabel(tot_frame, text=fix_arabic("الكاش المفترض في الدرج:", for_ui=True), font=("Arial", 16, "bold"), text_color="#1B5E20").pack(side="right", padx=15)
        ctk.CTkLabel(tot_frame, text=f"{expected_cash:.2f} {CURRENCY}", font=("Arial", 22, "bold"), text_color="#2E7D32").pack(side="left", padx=15)
        win.update_idletasks()

    def generate_invoice(self, total, type="SALE", extra=None):
        inv_path = f"Invoice_{type}_{datetime.datetime.now().strftime('%H%M%S')}.png"
        img = Image.new('RGB', (500, 850), color=(255, 255, 255)); d = ImageDraw.Draw(img)
        d.rectangle([0, 0, 500, 100], fill=COLOR_CRIMSON)
        try: font = ImageFont.truetype("arial.ttf", 20); bfont = ImageFont.truetype("arial.ttf", 28)
        except: font = bfont = None
        
        d.text((250, 50), fix_arabic(SHOP_NAME, for_ui=False), fill=(255,255,255), font=bfont, anchor="mm")
        d.text((450, 130), fix_arabic(f"الموقع: {LOCATION}", for_ui=False), fill=(0,0,0), font=font, anchor="rm")
        d.text((450, 165), fix_arabic(f"الهاتف: {PHONE}", for_ui=False), fill=(0,0,0), font=font, anchor="rm")
        d.text((450, 200), fix_arabic(f"التاريخ: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}", for_ui=False), fill=(0,0,0), font=font, anchor="rm")
        d.line([20, 230, 480, 230], fill=(0,0,0), width=2); y = 270
        
        if extra and 'client' in extra:
            d.text((450, y), fix_arabic(f"العميل: {extra['client']}", for_ui=False), fill=(0,0,0), font=font, anchor="rm"); y += 40
            
        if extra and 'payment' in extra:
            d.text((450, y), fix_arabic(f"طريقة الدفع: {extra['payment']}", for_ui=False), fill=(165,42,42), font=font, anchor="rm"); y += 40
            
        if type == "SALE":
            for i in self.cart: 
                d.text((450, y), fix_arabic(f"{i['name']} x{i['qty']} : {i['total']:.2f}", for_ui=False), fill=(0,0,0), font=font, anchor="rm"); y += 40
        elif type == "MAINTENANCE":
            d.text((450, y), fix_arabic(f"الجهاز: {extra['device']}", for_ui=False), fill=(0,0,0), font=font, anchor="rm"); y += 40
            d.text((450, y), fix_arabic(f"الإصلاح: {extra['desc']}", for_ui=False), fill=(0,0,0), font=font, anchor="rm"); y += 40
        elif type == "TRANSFER":
            raw_t = extra.get('type', '')
            # User rule for invoice titles:
            # - دخول حوالة -> ارسال حوالة
            # - خروج حوالة -> استلام حوالة
            # - دفع فاتورة -> دفع فاتورة
            if raw_t == "دخول حوالة":
                inv_t = "ارسال حوالة"
            elif raw_t == "خروج حوالة":
                inv_t = "استلام حوالة"
            else:
                inv_t = "دفع فاتورة"
            d.text((450, y), fix_arabic(f"النوع: {inv_t}", for_ui=False), fill=(0,0,0), font=font, anchor="rm"); y += 40
            d.text((450, y), fix_arabic(f"المرجع: {extra['ref']}", for_ui=False), fill=(0,0,0), font=font, anchor="rm"); y += 40
            
        if extra and "points" in extra and extra['points'] > 0:
            d.text((450, y+20), fix_arabic(f"النقاط المكتسبة: {extra['points']}", for_ui=False), fill=COLOR_CRIMSON, font=font, anchor="rm"); y += 50
            
        d.rectangle([20, y+20, 480, y+100], outline=COLOR_CRIMSON, width=3)
        d.text((250, y+60), fix_arabic(f"الإجمالي: {total:.2f} {CURRENCY}", for_ui=False), fill=(0,0,0), font=bfont, anchor="mm")
        img.save(inv_path)
        
        # Always show image preview for the user (Windows standard behavior)
        try:
            if sys.platform == "win32":
                os.startfile(inv_path)
            else:
                # For non-windows systems (like development environment), just skip or use a viewer if available
                pass
        except Exception:
            pass

        # Direct Thermal Printing for Xprinter XP-Q800 (80mm) in the background
        if sys.platform == "win32":
            try:
                import win32print
                import win32ui
                from PIL import ImageWin
                printer_name = None
                printers = win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS)
                for p in printers:
                    if "xprinter" in p[2].lower() or "xp-q800" in p[2].lower() or "pos" in p[2].lower() or "thermal" in p[2].lower():
                        printer_name = p[2]
                        break
                if not printer_name:
                    printer_name = win32print.GetDefaultPrinter()
                
                if printer_name:
                    hPrinter = win32print.OpenPrinter(printer_name)
                    try:
                        hdc = win32ui.CreateDC()
                        hdc.CreatePrinterDC(printer_name)
                        hdc.StartDoc("Trend Center Invoice")
                        hdc.StartPage()
                        
                        # 80mm thermal printer printable width (~576 dots at 203 DPI)
                        w, h = img.size
                        target_w = 576
                        target_h = int(h * (target_w / w))
                        print_img = img.resize((target_w, target_h), Image.Resampling.LANCZOS)
                        
                        dib = ImageWin.Dib(print_img)
                        dib.draw(hdc.GetHandleOutput(), (0, 0, target_w, target_h))
                        
                        hdc.EndPage()
                        hdc.EndDoc()
                        hdc.DeleteDC()
                    finally:
                        win32print.ClosePrinter(hPrinter)
            except Exception:
                # If printing fails, the image is already shown by startfile above
                pass
        
        # WhatsApp Marketing Integration with Loyalty Points Balance
        phone = extra.get('phone') if extra else None
        client = extra.get('client') if extra else "العميل"
        if phone:
            # Fetch total points for customer
            total_pts = 0
            try:
                self.cursor.execute("SELECT points FROM customers WHERE phone=?", (phone,))
                res = self.cursor.fetchone()
                if res:
                    total_pts = int(res[0] or 0)
            except Exception:
                pass
            
            earned_pts = extra.get('points', 0)
            service_desc = "المبيعات" if type == "SALE" else ("الصيانة" if type == "MAINTENANCE" else "الخدمات المالية")
            
            msg = (
                f"مرحباً بك يا {client} 🌸\n"
                f"شكراً لثقتك وزيارتك لـ {SHOP_NAME} ({LOCATION}).\n\n"
                f"✅ تمت خدمة ({service_desc}) بنجاح.\n"
                f"💰 المبلغ الإجمالي: {total:.2f} {CURRENCY}\n"
            )
            if earned_pts > 0:
                msg += f"🎁 النقاط المكتسبة لهذه العملية: +{earned_pts} نقطة\n"
            if total_pts > 0:
                msg += f"🌟 رصيد نقاط الولاء الإجمالي: {total_pts} نقطة\n"
            
            msg += "\nنسعد دائماً بخدمتكم! 🛍️✨"
            
            if messagebox.askyesno(str("تواصل واتساب"), str(f"هل تريد إرسال الفاتورة وتفاصيل الولاء للعميل {client} عبر واتساب فوراً؟")):
                self.send_whatsapp(phone, msg)

if __name__ == "__main__":
    app = TrendCenterApp(); app.mainloop()
