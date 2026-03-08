#!/usr/bin/env python3
"""HomeLibrary - simple barcode-driven library app for Raspberry Pi."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen

DB_PATH = Path("data/library.db")
DEFAULT_LOAN_DAYS = 14
DEFAULT_MAX_BOOKS = 5


def lookup_book_online(isbn: str) -> tuple[str, str] | None:
    """Fetch book title/author from Open Library using an ISBN barcode."""
    params = urlencode(
        {
            "bibkeys": f"ISBN:{isbn}",
            "format": "json",
            "jscmd": "data",
        }
    )
    url = f"https://openlibrary.org/api/books?{params}"
    with urlopen(url, timeout=4) as response:  # nosec: B310 - trusted Open Library API endpoint
        payload = json.load(response)

    book_data = payload.get(f"ISBN:{isbn}")
    if not book_data:
        return None

    title = str(book_data.get("title", "")).strip()
    authors = book_data.get("authors") or []
    author_names = ", ".join(
        str(author.get("name", "")).strip() for author in authors if author.get("name")
    )
    return title, author_names


@dataclass
class User:
    id: int
    name: str
    card_barcode: str


@dataclass
class Book:
    id: int
    title: str
    author: str
    book_barcode: str
    status: str


class LibraryDB:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()
        self._init_defaults()

    def _init_schema(self) -> None:
        with self.conn:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    card_barcode TEXT UNIQUE NOT NULL,
                    photo_path TEXT
                );

                CREATE TABLE IF NOT EXISTS books (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    author TEXT,
                    book_barcode TEXT UNIQUE NOT NULL,
                    status TEXT NOT NULL DEFAULT 'available'
                        CHECK(status IN ('available', 'checked_out'))
                );

                CREATE TABLE IF NOT EXISTS loans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    book_id INTEGER NOT NULL,
                    checkout_at TEXT NOT NULL,
                    due_at TEXT NOT NULL,
                    returned_at TEXT,
                    FOREIGN KEY(user_id) REFERENCES users(id),
                    FOREIGN KEY(book_id) REFERENCES books(id)
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )

    def _init_defaults(self) -> None:
        defaults = {
            "loan_days": str(DEFAULT_LOAN_DAYS),
            "max_books_per_user": str(DEFAULT_MAX_BOOKS),
        }
        with self.conn:
            for key, value in defaults.items():
                self.conn.execute(
                    "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)",
                    (key, value),
                )

    def get_setting_int(self, key: str, fallback: int) -> int:
        row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        if not row:
            return fallback
        try:
            return int(row["value"])
        except (TypeError, ValueError):
            return fallback

    def set_setting(self, key: str, value: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def add_user(self, name: str, card_barcode: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO users(name, card_barcode) VALUES (?, ?)",
                (name.strip(), card_barcode.strip()),
            )

    def add_book(self, title: str, author: str, book_barcode: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO books(title, author, book_barcode, status) VALUES (?, ?, ?, 'available')",
                (title.strip(), author.strip(), book_barcode.strip()),
            )

    def find_user_by_card(self, barcode: str) -> User | None:
        row = self.conn.execute(
            "SELECT id, name, card_barcode FROM users WHERE card_barcode = ?",
            (barcode.strip(),),
        ).fetchone()
        return User(**dict(row)) if row else None

    def find_book_by_barcode(self, barcode: str) -> Book | None:
        row = self.conn.execute(
            "SELECT id, title, author, book_barcode, status FROM books WHERE book_barcode = ?",
            (barcode.strip(),),
        ).fetchone()
        return Book(**dict(row)) if row else None

    def open_loans_for_user(self, user_id: int) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS count FROM loans WHERE user_id = ? AND returned_at IS NULL",
            (user_id,),
        ).fetchone()
        return int(row["count"])

    def checkout_book(self, user_id: int, book_id: int, due_at: datetime) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with self.conn:
            self.conn.execute(
                "INSERT INTO loans(user_id, book_id, checkout_at, due_at) VALUES (?, ?, ?, ?)",
                (user_id, book_id, now, due_at.isoformat(timespec="seconds")),
            )
            self.conn.execute("UPDATE books SET status='checked_out' WHERE id = ?", (book_id,))

    def return_book(self, book_id: int) -> bool:
        now = datetime.now().isoformat(timespec="seconds")
        with self.conn:
            loan = self.conn.execute(
                "SELECT id FROM loans WHERE book_id = ? AND returned_at IS NULL ORDER BY checkout_at DESC LIMIT 1",
                (book_id,),
            ).fetchone()
            if not loan:
                return False
            self.conn.execute(
                "UPDATE loans SET returned_at = ? WHERE id = ?",
                (now, loan["id"]),
            )
            self.conn.execute("UPDATE books SET status='available' WHERE id = ?", (book_id,))
            return True

    def close(self) -> None:
        self.conn.close()


class HomeLibraryApp(tk.Tk):
    def __init__(self, db: LibraryDB) -> None:
        super().__init__()
        self.db = db
        self.title("HomeLibrary")
        self.geometry("800x520")
        self.minsize(700, 420)

        style = ttk.Style(self)
        style.configure("Header.TLabel", font=("TkDefaultFont", 16, "bold"))
        style.configure("Status.TLabel", font=("TkDefaultFont", 11))

        self.mode_var = tk.StringVar(value="checkout")
        self.active_user: User | None = None

        self._build_ui()

    def _build_ui(self) -> None:
        top = ttk.Frame(self, padding=12)
        top.pack(fill="x")

        ttk.Label(top, text="HomeLibrary", style="Header.TLabel").pack(side="left")

        mode_frame = ttk.Frame(top)
        mode_frame.pack(side="right")
        for mode in ("checkout", "return", "admin"):
            ttk.Radiobutton(
                mode_frame,
                text=mode.title(),
                value=mode,
                variable=self.mode_var,
                command=self._on_mode_change,
            ).pack(side="left", padx=6)

        body = ttk.Frame(self, padding=(12, 4, 12, 12))
        body.pack(fill="both", expand=True)

        left = ttk.LabelFrame(body, text="Scanner Input", padding=12)
        left.pack(side="left", fill="both", expand=True, padx=(0, 6))

        ttk.Label(left, text="Scan barcode and press Enter:").pack(anchor="w")
        self.scan_entry = ttk.Entry(left, font=("TkDefaultFont", 14))
        self.scan_entry.pack(fill="x", pady=(8, 8))
        self.scan_entry.bind("<Return>", self._on_scan)

        self.status_var = tk.StringVar(value="Ready. Select mode and scan.")
        ttk.Label(left, textvariable=self.status_var, style="Status.TLabel", wraplength=380).pack(
            anchor="w", pady=(6, 0)
        )

        self.user_var = tk.StringVar(value="No user selected")
        ttk.Label(left, textvariable=self.user_var, font=("TkDefaultFont", 12, "bold")).pack(
            anchor="w", pady=(18, 0)
        )

        right = ttk.LabelFrame(body, text="Activity Log", padding=12)
        right.pack(side="right", fill="both", expand=True, padx=(6, 0))

        self.log = tk.Text(right, height=18, wrap="word", state="disabled")
        self.log.pack(fill="both", expand=True)

        self.admin_frame = ttk.LabelFrame(self, text="Admin", padding=12)
        self._build_admin(self.admin_frame)
        self.admin_frame.pack(fill="x", padx=12, pady=(0, 12))

        self._on_mode_change()
        self.after(150, lambda: self.scan_entry.focus_set())

    def _build_admin(self, frame: ttk.LabelFrame) -> None:
        grid = ttk.Frame(frame)
        grid.pack(fill="x")

        ttk.Label(grid, text="User name").grid(row=0, column=0, sticky="w")
        self.user_name_entry = ttk.Entry(grid, width=24)
        self.user_name_entry.grid(row=0, column=1, padx=6)

        ttk.Label(grid, text="Card barcode").grid(row=0, column=2, sticky="w")
        self.user_card_entry = ttk.Entry(grid, width=18)
        self.user_card_entry.grid(row=0, column=3, padx=6)

        ttk.Button(grid, text="Add User", command=self._admin_add_user).grid(row=0, column=4, padx=6)

        ttk.Label(grid, text="Book title").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.book_title_entry = ttk.Entry(grid, width=24)
        self.book_title_entry.grid(row=1, column=1, padx=6, pady=(8, 0))

        ttk.Label(grid, text="Author").grid(row=1, column=2, sticky="w", pady=(8, 0))
        self.book_author_entry = ttk.Entry(grid, width=18)
        self.book_author_entry.grid(row=1, column=3, padx=6, pady=(8, 0))

        ttk.Label(grid, text="Book barcode").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.book_code_entry = ttk.Entry(grid, width=24)
        self.book_code_entry.grid(row=2, column=1, padx=6, pady=(8, 0))

        ttk.Button(grid, text="Lookup Online", command=self._admin_lookup_book).grid(
            row=2, column=3, sticky="w", padx=6, pady=(8, 0)
        )

        ttk.Button(grid, text="Add Book", command=self._admin_add_book).grid(row=2, column=4, padx=6, pady=(8, 0))

        ttk.Label(grid, text="Loan days").grid(row=3, column=0, sticky="w", pady=(8, 0))
        self.loan_days_entry = ttk.Entry(grid, width=10)
        self.loan_days_entry.insert(0, str(self.db.get_setting_int("loan_days", DEFAULT_LOAN_DAYS)))
        self.loan_days_entry.grid(row=3, column=1, sticky="w", padx=6, pady=(8, 0))

        ttk.Button(grid, text="Save Settings", command=self._admin_save_settings).grid(
            row=3, column=4, padx=6, pady=(8, 0)
        )

    def _set_status(self, msg: str) -> None:
        self.status_var.set(msg)

    def _append_log(self, msg: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log.configure(state="normal")
        self.log.insert("end", f"[{timestamp}] {msg}\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _on_mode_change(self) -> None:
        mode = self.mode_var.get()
        self.active_user = None if mode != "checkout" else self.active_user
        if mode == "checkout":
            self._set_status("Checkout mode: scan user card first, then books.")
            self.user_var.set("No user selected")
            self.admin_frame.pack_forget()
        elif mode == "return":
            self._set_status("Return mode: scan books to check in.")
            self.user_var.set("User selection not needed")
            self.admin_frame.pack_forget()
        else:
            self._set_status("Admin mode: use form below to add users/books/settings.")
            self.user_var.set("Admin tools enabled")
            self.admin_frame.pack(fill="x", padx=12, pady=(0, 12))
        self.scan_entry.focus_set()

    def _on_scan(self, _event: tk.Event) -> None:
        code = self.scan_entry.get().strip()
        self.scan_entry.delete(0, "end")
        if not code:
            return

        mode = self.mode_var.get()
        if mode == "checkout":
            self._handle_checkout_scan(code)
        elif mode == "return":
            self._handle_return_scan(code)
        else:
            self._set_status("Admin mode does not process scanner input.")
        self.scan_entry.focus_set()

    def _handle_checkout_scan(self, code: str) -> None:
        if not self.active_user:
            user = self.db.find_user_by_card(code)
            if not user:
                self._set_status(f"No user found for card '{code}'.")
                self._append_log(f"Unknown card scanned: {code}")
                return
            self.active_user = user
            self.user_var.set(f"User: {user.name} ({user.card_barcode})")
            self._set_status(f"User selected: {user.name}. Now scan books.")
            self._append_log(f"Selected user {user.name}")
            return

        book = self.db.find_book_by_barcode(code)
        if not book:
            self._set_status(f"No book found for barcode '{code}'.")
            self._append_log(f"Unknown book barcode scanned: {code}")
            return
        if book.status != "available":
            self._set_status(f"'{book.title}' is already checked out.")
            self._append_log(f"Checkout blocked (already out): {book.title}")
            return

        max_books = self.db.get_setting_int("max_books_per_user", DEFAULT_MAX_BOOKS)
        open_count = self.db.open_loans_for_user(self.active_user.id)
        if open_count >= max_books:
            self._set_status(f"Checkout blocked: user already has {open_count} open books.")
            self._append_log(f"Checkout blocked for {self.active_user.name}: max books reached")
            return

        loan_days = self.db.get_setting_int("loan_days", DEFAULT_LOAN_DAYS)
        due_at = datetime.now() + timedelta(days=loan_days)
        self.db.checkout_book(self.active_user.id, book.id, due_at)
        self._set_status(f"Checked out '{book.title}'. Due {due_at.date().isoformat()}.")
        self._append_log(
            f"Checkout: {book.title} to {self.active_user.name} (due {due_at.date().isoformat()})"
        )

    def _handle_return_scan(self, code: str) -> None:
        book = self.db.find_book_by_barcode(code)
        if not book:
            self._set_status(f"No book found for barcode '{code}'.")
            self._append_log(f"Unknown return barcode: {code}")
            return
        if book.status == "available":
            self._set_status(f"'{book.title}' is already marked available.")
            self._append_log(f"Return skipped (already available): {book.title}")
            return

        returned = self.db.return_book(book.id)
        if returned:
            self._set_status(f"Returned '{book.title}'.")
            self._append_log(f"Return: {book.title}")
        else:
            self._set_status(f"No open loan found for '{book.title}'.")
            self._append_log(f"Return failed: no open loan for {book.title}")

    def _admin_add_user(self) -> None:
        name = self.user_name_entry.get().strip()
        card = self.user_card_entry.get().strip()
        if not name or not card:
            messagebox.showerror("Missing data", "User name and card barcode are required.")
            return
        try:
            self.db.add_user(name, card)
        except sqlite3.IntegrityError:
            messagebox.showerror("Duplicate", "Card barcode already exists.")
            return
        self.user_name_entry.delete(0, "end")
        self.user_card_entry.delete(0, "end")
        self._append_log(f"Added user: {name}")

    def _admin_add_book(self) -> None:
        title = self.book_title_entry.get().strip()
        author = self.book_author_entry.get().strip()
        code = self.book_code_entry.get().strip()
        if not title or not code:
            messagebox.showerror("Missing data", "Book title and barcode are required.")
            return
        try:
            self.db.add_book(title, author, code)
        except sqlite3.IntegrityError:
            messagebox.showerror("Duplicate", "Book barcode already exists.")
            return
        self.book_title_entry.delete(0, "end")
        self.book_author_entry.delete(0, "end")
        self.book_code_entry.delete(0, "end")
        self._append_log(f"Added book: {title}")

    def _admin_lookup_book(self) -> None:
        code = self.book_code_entry.get().strip()
        if not code:
            messagebox.showerror("Missing data", "Book barcode/ISBN is required.")
            return
        if not code.isdigit():
            messagebox.showerror("Invalid", "Online lookup currently supports numeric ISBN barcodes.")
            return

        try:
            result = lookup_book_online(code)
        except (URLError, TimeoutError, json.JSONDecodeError):
            messagebox.showerror("Lookup failed", "Could not reach online book lookup service.")
            self._append_log(f"Online lookup failed for barcode {code}")
            return

        if not result:
            messagebox.showinfo("Not found", "No online book record found for this barcode.")
            self._append_log(f"Online lookup had no match for barcode {code}")
            return

        title, authors = result
        if title:
            self.book_title_entry.delete(0, "end")
            self.book_title_entry.insert(0, title)
        if authors:
            self.book_author_entry.delete(0, "end")
            self.book_author_entry.insert(0, authors)
        self._set_status("Filled book details from online lookup.")
        self._append_log(f"Online lookup populated details for barcode {code}")

    def _admin_save_settings(self) -> None:
        loan_days = self.loan_days_entry.get().strip()
        if not loan_days.isdigit() or int(loan_days) <= 0:
            messagebox.showerror("Invalid", "Loan days must be a positive integer.")
            return
        self.db.set_setting("loan_days", loan_days)
        self._append_log(f"Updated setting: loan_days={loan_days}")
        self._set_status("Settings saved.")


def main() -> None:
    with closing(LibraryDB(DB_PATH)) as db:
        app = HomeLibraryApp(db)
        app.mainloop()


if __name__ == "__main__":
    main()
