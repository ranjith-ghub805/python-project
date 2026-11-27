# SpendSmart

SpendSmart is a Flask + SQLite personal-finance tracker designed for college students. It includes individual student accounts, income and expense tracking, budgets, savings goals, reports, CSV export and responsive charts.

## Requirements

- Python 3.10 or newer
- pip

## Run locally

Open a terminal in this `spendsmart` folder, then:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:SPENDSMART_SECRET_KEY = (python -c "import secrets; print(secrets.token_hex(32))")
python app.py
```

If PowerShell blocks activation, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` in that terminal and activate again. On macOS/Linux, activate with `source .venv/bin/activate` and set the key with `export SPENDSMART_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"`.

Visit [http://127.0.0.1:5000](http://127.0.0.1:5000), create an account, and start adding transactions. The SQLite database is created automatically as `database.db` the first time the app starts. No sample transactions are inserted.

## Features

- Secure registration/login with Werkzeug password hashing and signed Flask sessions.
- Profile editing and password changes with current-password verification.
- Student-owned records enforced in database queries for every private operation.
- Income and expense CRUD, search, type/category/date filters, plus a one-click add-income shortcut.
- Monthly overall and category budgets with progress and threshold states.
- Savings goals with progress, achievements and remaining balance.
- Money-lent register with borrower, amount, due date, in-app dashboard reminders and repayment recording.
- Animated balance/income/expense/savings totals, budget warnings and a monthly summary.
- A visual 50/30/20 planning guide with a guilt-free personal-spending allowance based on recorded monthly income.
- Daily, weekly and monthly reports with interactive Chart.js visualizations.
- CSV download of the signed-in student's transaction history.
- Profile editing and responsive mobile navigation.

## Security notes

Set `SPENDSMART_SECRET_KEY` to a long, random value before deployment and use HTTPS. The app enables HTTP-only and SameSite=Lax session cookies; set `HTTPS_ONLY=1` in the environment only when serving over HTTPS. All modifying forms use a session-bound CSRF token; SQL values are parameterized; passwords are never stored in plaintext. Loan reminders appear in the dashboard when a loan is overdue, due today or due within seven days; reminders are in-app and require no notification permission.

This project is suitable for local learning and demonstration. For public deployment, add operational hardening such as rate limiting, production WSGI hosting, secure secret management, backups and account recovery.

## Deploy publicly

A Render blueprint is included in `render.yaml`. To deploy:

1. Push this `spendsmart` folder to a public or private GitHub repository.
2. In Render, choose **New > Blueprint** and select the repository.
3. Render creates a public HTTPS address and persistent SQLite database disk.
4. Open the generated address and register an account.

The app is also production-ready for other Flask hosts. Set these environment variables:

- `SPENDSMART_SECRET_KEY`: a long random value
- `SPENDSMART_DATABASE`: writable SQLite path, such as `/var/data/database.db`
- `HTTPS_ONLY=1`: enables secure session cookies on HTTPS

## Project layout

```text
spendsmart/
  app.py
  requirements.txt
  README.md
  templates/
  static/css/style.css
  static/js/script.js
```
