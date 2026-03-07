# HomeLibrary (Raspberry Pi Setup Guide)

This guide walks you step-by-step through building and running your **toddler home library app** on a Raspberry Pi.

It is written for beginners and uses a simple Python setup.

---

## 1) What this project does

The app is designed to work like a real library:

- Scan a **library card barcode** to select a user.
- Scan **book barcodes** to check books out.
- Scan books again to check them back in.
- Automatically calculate and show a **due date** based on rules you set.
- Save data after each transaction so it survives reboots/shutdowns.

---

## 2) Hardware you need

- Raspberry Pi (Pi 3/4/5 recommended)
- Raspberry Pi OS (Bookworm or newer)
- Monitor + keyboard
- USB barcode scanner (keyboard-emulation/HID type)
- Optional: mouse/touchscreen, USB printer

---

## 3) Prepare Raspberry Pi OS

Open Terminal and run:

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv git sqlite3
```

If you want Tkinter GUI support (recommended for beginner Python GUI):

```bash
sudo apt install -y python3-tk
```

---

## 4) Clone your project

Choose a folder and clone:

```bash
cd ~
git clone <YOUR_GIT_REPO_URL> HomeLibrary
cd HomeLibrary
```

If your repo already exists locally, just `cd` into it.

---

## 5) Create a Python virtual environment

```bash
cd ~/HomeLibrary
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

If your app has a `requirements.txt`, install dependencies:

```bash
pip install -r requirements.txt
```

---

## 6) Confirm scanner works on Pi

Most USB scanners behave like keyboards and “type” into the active text field.

Quick test:

1. Open Terminal.
2. Type `cat` and press Enter.
3. Scan a barcode.
4. You should see numbers appear (often followed by Enter automatically).
5. Press `Ctrl+C` to exit `cat`.

If this works, scanner setup is good.

---

## 7) Recommended project structure

Use this layout:

```text
HomeLibrary/
├── app.py
├── requirements.txt
├── data/
│   ├── library.db
│   └── backups/
├── assets/
│   ├── users/
│   └── icons/
└── README.md
```

- `library.db`: SQLite database file
- `assets/users/`: user photos/avatars
- `data/backups/`: optional rolling backups

---

## 8) Database design (simple and reliable)

Use SQLite (built into Python).

Minimum tables:

1. `users`
   - `id`
   - `name`
   - `card_barcode` (unique)
   - `photo_path`
2. `books`
   - `id`
   - `title`
   - `author`
   - `book_barcode` (unique)
   - `status` (`available` / `checked_out`)
3. `loans`
   - `id`
   - `user_id`
   - `book_id`
   - `checkout_at`
   - `due_at`
   - `returned_at` (null if still out)
4. `settings`
   - key/value table for rules (ex: `loan_days=14`)

**Important:** commit each checkout/check-in transaction immediately so power loss does not lose data.

---

## 9) Basic app flow

### Checkout flow

1. Tap **Checkout**
2. Scan user card
3. Show user name/photo
4. Scan one or more books
5. Compute due date (example: today + 14 days)
6. Save each loan to DB
7. Show printable summary (optional)

### Return flow

1. Tap **Return**
2. Scan book barcode(s)
3. Mark matching open loan as returned
4. Set book status back to `available`
5. Save immediately

---

## 10) Due-date rule examples

Start simple in settings:

- `loan_days = 14`
- `max_books_per_user = 5`

Optional later:

- Different loan periods by user
- Skip weekends
- Overdue warnings

---

## 11) Run the app

From project folder:

```bash
cd ~/HomeLibrary
source .venv/bin/activate
python app.py
```

---

## 12) Make it launch automatically on boot (optional)

Create a systemd service:

```bash
sudo nano /etc/systemd/system/homelibrary.service
```

Paste and adjust `User=` and `WorkingDirectory=`:

```ini
[Unit]
Description=HomeLibrary App
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/HomeLibrary
ExecStart=/home/pi/HomeLibrary/.venv/bin/python /home/pi/HomeLibrary/app.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

Enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable homelibrary.service
sudo systemctl start homelibrary.service
sudo systemctl status homelibrary.service
```

---

## 13) Backup strategy

At minimum:

- Keep `data/library.db`
- After each day (or each session), copy to:
  - USB drive, or
  - cloud folder (if online)

Quick manual backup command:

```bash
cp ~/HomeLibrary/data/library.db ~/HomeLibrary/data/backups/library-$(date +%F-%H%M).db
```

---

## 14) Troubleshooting

### Scanner does nothing

- Confirm USB connection.
- Test in Terminal with `cat`.
- Check scanner is in **HID keyboard** mode (scanner manual).

### App starts but no window appears

- Install GUI support: `sudo apt install python3-tk`
- If autostarted via systemd, check logs:

```bash
journalctl -u homelibrary.service -n 100 --no-pager
```

### Database errors

- Confirm `data/` exists and is writable.
- Confirm app creates tables on first run.

---

## 15) Nice toddler-friendly UI ideas

- Large buttons: **Checkout**, **Return**, **Admin**
- Bright colors and big icons
- Confirmation sounds on success/error
- Show user avatar after card scan
- Book cover image if available
- Minimal text on child-facing screens

---

## 16) Suggested next improvements

- Add admin screen for adding users/books
- Pull book info from online APIs by ISBN/UPC (fallback to manual)
- Print due-date slips to USB printer
- Add daily automatic backup cron job

---

## 17) Quick start checklist

- [ ] Pi updated and Python installed
- [ ] Project cloned to `~/HomeLibrary`
- [ ] Virtual environment created
- [ ] Scanner tested in Terminal
- [ ] App launches with `python app.py`
- [ ] Checkout + return tested
- [ ] Data persists after reboot

