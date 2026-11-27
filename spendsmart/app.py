"""SpendSmart: a student-focused personal finance tracker."""

from __future__ import annotations

import csv
import io
import os
import re
import secrets
import sqlite3
from datetime import date, datetime, timedelta
from functools import wraps
from pathlib import Path
from typing import Any, Callable

from flask import (
    Flask,
    Response,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash


ROOT = Path(__file__).resolve().parent
DATABASE = ROOT / "database.db"
EXPENSE_CATEGORIES = [
    "Food",
    "Travel",
    "Shopping",
    "Education",
    "Entertainment",
    "Bills",
    "Others",
]
INCOME_CATEGORIES = [
    "Pocket money",
    "Allowance",
    "Scholarship",
    "Part-time work",
    "Gift",
    "Other income",
    "Loan repayment",
]


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SPENDSMART_SECRET_KEY", secrets.token_hex(32)),
        DATABASE=os.environ.get("SPENDSMART_DATABASE", str(DATABASE)),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )
    if test_config:
        app.config.update(test_config)
    if app.config.get("HTTPS_ONLY") or os.environ.get("HTTPS_ONLY") == "1":
        app.config["SESSION_COOKIE_SECURE"] = True

    @app.teardown_appcontext
    def close_database(_error: BaseException | None = None) -> None:
        db = g.pop("db", None)
        if db is not None:
            db.close()

    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
    with app.app_context():
        init_db()

    @app.before_request
    def set_csrf_token() -> None:
        session.setdefault("_csrf_token", secrets.token_hex(32))

    @app.before_request
    def verify_csrf_token() -> None:
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            submitted = request.form.get("csrf_token", "")
            expected = session.get("_csrf_token", "")
            if not submitted or not secrets.compare_digest(submitted, expected):
                abort(400, description="Your form session expired. Please refresh and try again.")

    @app.context_processor
    def inject_template_values() -> dict[str, Any]:
        return {
            "current_user": get_current_user(),
            "csrf_token": session.get("_csrf_token", ""),
            "expense_categories": EXPENSE_CATEGORIES,
            "income_categories": INCOME_CATEGORIES,
            "today": date.today().isoformat(),
            "greeting": (
                "morning" if datetime.now().hour < 12 else
                "afternoon" if datetime.now().hour < 18 else "evening"
            ),
        }

    @app.template_filter("currency")
    def currency(value: Any) -> str:
        return f"₹{float(value or 0):,.2f}"

    @app.template_filter("date_label")
    def date_label(value: str) -> str:
        return date.fromisoformat(value).strftime("%A, %d %b")

    def login_required(view: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(view)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            if not session.get("student_id"):
                flash("Please sign in to continue.", "info")
                return redirect(url_for("login"))
            return view(*args, **kwargs)

        return wrapped

    def owned_transaction(transaction_id: int) -> sqlite3.Row:
        transaction = get_db().execute(
            "SELECT * FROM transactions WHERE id = ? AND student_id = ?",
            (transaction_id, session["student_id"]),
        ).fetchone()
        if transaction is None:
            abort(404)
        return transaction

    def valid_amount(raw: str) -> float | None:
        try:
            amount = round(float(raw), 2)
        except (TypeError, ValueError):
            return None
        if not (0 < amount <= 1_000_000_000):
            return None
        return amount

    def valid_iso_date(raw: str) -> bool:
        try:
            return date.fromisoformat(raw).isoformat() == raw
        except (TypeError, ValueError):
            return False

    def transaction_form_values() -> tuple[dict[str, Any] | None, str | None]:
        kind = request.form.get("kind", "").strip().lower()
        category = request.form.get("category", "").strip()
        amount = valid_amount(request.form.get("amount", ""))
        tx_date = request.form.get("transaction_date", "").strip()
        description = request.form.get("description", "").strip()
        categories = INCOME_CATEGORIES if kind == "income" else EXPENSE_CATEGORIES
        if kind not in {"income", "expense"}:
            return None, "Choose whether this transaction is income or an expense."
        if category not in categories:
            return None, "Choose a valid category."
        if amount is None:
            return None, "Enter an amount greater than zero (up to 1,000,000,000)."
        if not valid_iso_date(tx_date):
            return None, "Enter a valid transaction date."
        if len(description) > 240:
            return None, "Description must be 240 characters or fewer."
        return {
            "kind": kind,
            "category": category,
            "amount": amount,
            "transaction_date": tx_date,
            "description": description,
        }, None

    @app.route("/")
    def index() -> Any:
        return redirect(url_for("dashboard" if session.get("student_id") else "login"))

    @app.route("/register", methods=["GET", "POST"])
    def register() -> Any:
        if session.get("student_id"):
            return redirect(url_for("dashboard"))
        if request.method == "POST":
            name = request.form.get("full_name", "").strip()
            email = request.form.get("email", "").strip().lower()
            college = request.form.get("college", "").strip()
            password = request.form.get("password", "")
            confirmation = request.form.get("confirm_password", "")
            errors = []
            if not 2 <= len(name) <= 80:
                errors.append("Full name must be between 2 and 80 characters.")
            if len(email) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
                errors.append("Enter a valid email address.")
            if not 2 <= len(college) <= 120:
                errors.append("College name must be between 2 and 120 characters.")
            if len(password) < 8:
                errors.append("Password must contain at least 8 characters.")
            if password != confirmation:
                errors.append("Passwords do not match.")
            if errors:
                for error in errors:
                    flash(error, "error")
            else:
                try:
                    cursor = get_db().execute(
                        """INSERT INTO students (full_name, email, college, password_hash)
                           VALUES (?, ?, ?, ?)""",
                        (name, email, college, generate_password_hash(password)),
                    )
                    get_db().commit()
                    session.clear()
                    session["student_id"] = cursor.lastrowid
                    flash("Your account is ready. Welcome to SpendSmart!", "success")
                    return redirect(url_for("dashboard"))
                except sqlite3.IntegrityError:
                    flash("An account with that email already exists.", "error")
        return render_template("register.html")

    @app.route("/login", methods=["GET", "POST"])
    def login() -> Any:
        if session.get("student_id"):
            return redirect(url_for("dashboard"))
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            student = get_db().execute(
                "SELECT id, password_hash FROM students WHERE email = ?", (email,)
            ).fetchone()
            if student and check_password_hash(student["password_hash"], password):
                session.clear()
                session["student_id"] = student["id"]
                flash("You are signed in.", "success")
                return redirect(url_for("dashboard"))
            flash("Email or password is incorrect.", "error")
        return render_template("login.html")

    @app.route("/logout", methods=["POST"])
    @login_required
    def logout() -> Any:
        session.clear()
        flash("You have been signed out.", "info")
        return redirect(url_for("login"))

    @app.route("/dashboard")
    @login_required
    def dashboard() -> Any:
        db = get_db()
        student_id = session["student_id"]
        student = db.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
        totals = db.execute(
            """SELECT
               COALESCE(SUM(CASE WHEN kind = 'income' THEN amount ELSE 0 END), 0) AS income,
               COALESCE(SUM(CASE WHEN kind = 'expense' THEN amount ELSE 0 END), 0) AS expenses,
               COALESCE(SUM(CASE WHEN kind = 'income' AND substr(transaction_date, 1, 7) = ?
                                 THEN amount ELSE 0 END), 0) AS month_income,
               COALESCE(SUM(CASE WHEN kind = 'expense' AND substr(transaction_date, 1, 7) = ?
                                 THEN amount ELSE 0 END), 0) AS month_expenses
               FROM transactions WHERE student_id = ?""",
            (date.today().strftime("%Y-%m"), date.today().strftime("%Y-%m"), student_id),
        ).fetchone()
        recent = db.execute(
            "SELECT * FROM transactions WHERE student_id = ? ORDER BY transaction_date DESC, id DESC LIMIT 6",
            (student_id,),
        ).fetchall()
        categories = db.execute(
            """SELECT category, SUM(amount) AS total FROM transactions
               WHERE student_id = ? AND kind = 'expense'
                 AND substr(transaction_date, 1, 7) = ?
               GROUP BY category ORDER BY total DESC""",
            (student_id, date.today().strftime("%Y-%m")),
        ).fetchall()
        chart_start = (date.today().replace(day=1) - timedelta(days=155)).replace(day=1)
        chart_rows = db.execute(
            """SELECT substr(transaction_date, 1, 7) AS month, kind, SUM(amount) AS total
               FROM transactions WHERE student_id = ? AND transaction_date >= ?
               GROUP BY month, kind ORDER BY month""",
            (student_id, chart_start.isoformat()),
        ).fetchall()
        chart_series: dict[str, dict[str, float]] = {}
        for row in chart_rows:
            chart_series.setdefault(row["month"], {"income": 0, "expense": 0})[row["kind"]] = row["total"]
        chart_months = []
        month_cursor = chart_start
        current_month = date.today().replace(day=1)
        while month_cursor <= current_month:
            chart_months.append(month_cursor.strftime("%Y-%m"))
            month_cursor = (month_cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
        budget_rows = db.execute(
            """SELECT b.category, b.amount,
               COALESCE(SUM(t.amount), 0) AS spent
               FROM budgets b LEFT JOIN transactions t
                 ON t.student_id = b.student_id AND t.kind = 'expense'
                AND (b.category = 'Overall' OR t.category = b.category)
                AND substr(t.transaction_date, 1, 7) = b.month
               WHERE b.student_id = ? AND b.month = ?
               GROUP BY b.id ORDER BY b.category""",
            (student_id, date.today().strftime("%Y-%m")),
        ).fetchall()
        all_budget_rows = budget_rows
        goals = db.execute(
            "SELECT * FROM savings_goals WHERE student_id = ? ORDER BY created_at DESC LIMIT 3",
            (student_id,),
        ).fetchall()
        total_savings = db.execute(
            "SELECT COALESCE(SUM(saved_amount), 0) AS total FROM savings_goals WHERE student_id = ?",
            (student_id,),
        ).fetchone()["total"]
        achieved_goals = db.execute(
            """SELECT name FROM savings_goals
               WHERE student_id = ? AND saved_amount >= target_amount
               ORDER BY created_at DESC LIMIT 3""",
            (student_id,),
        ).fetchall()
        loans = db.execute(
            """SELECT * FROM loans WHERE student_id = ? AND status = 'open'
               ORDER BY due_date IS NULL, due_date LIMIT 4""",
            (student_id,),
        ).fetchall()
        outstanding_loans = db.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM loans WHERE student_id = ? AND status = 'open'",
            (student_id,),
        ).fetchone()["total"]
        balance = totals["income"] - totals["expenses"] - outstanding_loans
        today = date.today()
        loan_reminders = []
        for loan in loans:
            if not loan["due_date"]:
                continue
            days_left = (date.fromisoformat(loan["due_date"]) - today).days
            if days_left < 0:
                message = f"{abs(days_left)} day{'s' if abs(days_left) != 1 else ''} overdue"
                tone = "overdue"
            elif days_left == 0:
                message, tone = "Due today", "today"
            elif days_left <= 7:
                message = f"Due in {days_left} day{'s' if days_left != 1 else ''}"
                tone = "soon"
            else:
                message = ""
                tone = ""
            if message:
                loan_reminders.append({"loan": loan, "message": message, "tone": tone})
        tips = []
        if balance < 0:
            tips.append("Your expenses are above your recorded income. Review recent spending and adjust this month's plan.")
        if totals["month_income"] and totals["month_expenses"] > totals["month_income"] * 0.8:
            tips.append("You have used more than 80% of this month's income. Consider pausing non-essential purchases.")
        if categories and categories[0]["total"] >= 5000:
            tips.append(f"{categories[0]['category']} is your top expense this month. A small weekly limit can make it easier to manage.")
        if not tips:
            tips.append("Nice work staying aware of your money. Keep recording purchases to make your insights more accurate.")
        savings_rate = (
            max(0, (totals["month_income"] - totals["month_expenses"]) / totals["month_income"] * 100)
            if totals["month_income"] else 0
        )
        allocation = {
            "needs": totals["month_income"] * 0.50,
            "wants": totals["month_income"] * 0.30,
            "savings": totals["month_income"] * 0.20,
        }
        return render_template(
            "dashboard.html",
            student=student,
            totals=totals,
            balance=balance,
            recent=recent,
            categories=categories,
            budgets=budget_rows,
            all_budgets=all_budget_rows,
            goals=goals,
            total_savings=total_savings,
            achieved_goals=achieved_goals,
            loans=loans,
            loan_reminders=loan_reminders,
            outstanding_loans=outstanding_loans,
            savings_rate=savings_rate,
            allocation=allocation,
            tips=tips,
            chart_months=chart_months,
            chart_income=[chart_series.get(month, {}).get("income", 0) for month in chart_months],
            chart_expenses=[chart_series.get(month, {}).get("expense", 0) for month in chart_months],
        )

    @app.route("/transactions")
    @login_required
    def transactions() -> Any:
        filters = {
            "q": request.args.get("q", "").strip()[:100],
            "kind": request.args.get("kind", "").strip(),
            "category": request.args.get("category", "").strip(),
            "start": request.args.get("start", "").strip(),
            "end": request.args.get("end", "").strip(),
        }
        clauses = ["student_id = ?"]
        params: list[Any] = [session["student_id"]]
        if filters["kind"] in {"income", "expense"}:
            clauses.append("kind = ?")
            params.append(filters["kind"])
        if filters["category"]:
            clauses.append("category = ?")
            params.append(filters["category"])
        if filters["q"]:
            clauses.append("(category LIKE ? OR description LIKE ?)")
            params.extend([f"%{filters['q']}%", f"%{filters['q']}%"])
        if valid_iso_date(filters["start"]):
            clauses.append("transaction_date >= ?")
            params.append(filters["start"])
        if valid_iso_date(filters["end"]):
            clauses.append("transaction_date <= ?")
            params.append(filters["end"])
        records = get_db().execute(
            f"SELECT * FROM transactions WHERE {' AND '.join(clauses)} "
            "ORDER BY transaction_date DESC, id DESC",
            params,
        ).fetchall()
        return render_template("transactions.html", records=records, filters=filters)

    @app.route("/transactions/new", methods=["GET", "POST"])
    @login_required
    def add_transaction() -> Any:
        if request.method == "POST":
            values, error = transaction_form_values()
            if error:
                flash(error, "error")
            else:
                get_db().execute(
                    """INSERT INTO transactions
                       (student_id, kind, category, amount, transaction_date, description)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        session["student_id"],
                        values["kind"],
                        values["category"],
                        values["amount"],
                        values["transaction_date"],
                        values["description"],
                    ),
                )
                get_db().commit()
                flash("Transaction added successfully.", "success")
                return redirect(url_for("transactions"))
        initial_kind = request.form.get(
            "kind", request.args.get("kind", "expense")
        )
        if initial_kind not in {"income", "expense"}:
            initial_kind = "expense"
        return render_template("add_transaction.html", record=None, initial_kind=initial_kind)

    @app.route("/transactions/<int:transaction_id>/edit", methods=["GET", "POST"])
    @login_required
    def edit_transaction(transaction_id: int) -> Any:
        record = owned_transaction(transaction_id)
        if request.method == "POST":
            values, error = transaction_form_values()
            if error:
                flash(error, "error")
            else:
                get_db().execute(
                    """UPDATE transactions SET kind = ?, category = ?, amount = ?,
                       transaction_date = ?, description = ?
                       WHERE id = ? AND student_id = ?""",
                    (
                        values["kind"],
                        values["category"],
                        values["amount"],
                        values["transaction_date"],
                        values["description"],
                        transaction_id,
                        session["student_id"],
                    ),
                )
                get_db().commit()
                flash("Transaction updated.", "success")
                return redirect(url_for("transactions"))
        return render_template("add_transaction.html", record=record)

    @app.route("/transactions/<int:transaction_id>/delete", methods=["POST"])
    @login_required
    def delete_transaction(transaction_id: int) -> Any:
        owned_transaction(transaction_id)
        get_db().execute(
            "DELETE FROM transactions WHERE id = ? AND student_id = ?",
            (transaction_id, session["student_id"]),
        )
        get_db().commit()
        flash("Transaction deleted.", "success")
        return redirect(request.referrer or url_for("transactions"))

    @app.route("/budgets", methods=["GET", "POST"])
    @login_required
    def budgets() -> Any:
        db = get_db()
        if request.method == "POST":
            month = request.form.get("month", "").strip()
            category = request.form.get("category", "").strip()
            amount = valid_amount(request.form.get("amount", ""))
            valid_month = bool(re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month))
            if not valid_month or category not in ["Overall", *EXPENSE_CATEGORIES] or amount is None:
                flash("Enter a valid month, budget category and amount greater than zero.", "error")
            else:
                db.execute(
                    """INSERT INTO budgets (student_id, month, category, amount)
                       VALUES (?, ?, ?, ?)
                       ON CONFLICT(student_id, month, category) DO UPDATE SET amount = excluded.amount""",
                    (session["student_id"], month, category, amount),
                )
                db.commit()
                flash("Budget saved.", "success")
                return redirect(url_for("budgets"))
        rows = db.execute(
            """SELECT b.*, COALESCE(SUM(t.amount), 0) AS spent FROM budgets b
               LEFT JOIN transactions t ON t.student_id = b.student_id
                 AND t.kind = 'expense' AND substr(t.transaction_date, 1, 7) = b.month
                 AND (b.category = 'Overall' OR t.category = b.category)
               WHERE b.student_id = ? GROUP BY b.id
               ORDER BY b.month DESC, b.category""",
            (session["student_id"],),
        ).fetchall()
        return render_template("budgets.html", budgets=rows, this_month=date.today().strftime("%Y-%m"))

    @app.route("/budgets/<int:budget_id>/delete", methods=["POST"])
    @login_required
    def delete_budget(budget_id: int) -> Any:
        get_db().execute(
            "DELETE FROM budgets WHERE id = ? AND student_id = ?",
            (budget_id, session["student_id"]),
        )
        get_db().commit()
        flash("Budget removed.", "success")
        return redirect(url_for("budgets"))

    @app.route("/savings", methods=["GET", "POST"])
    @login_required
    def savings() -> Any:
        db = get_db()
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            target = valid_amount(request.form.get("target_amount", ""))
            saved_raw = request.form.get("saved_amount", "0").strip() or "0"
            try:
                saved = round(float(saved_raw), 2)
                if saved < 0 or saved > 1_000_000_000:
                    saved = None
            except ValueError:
                saved = None
            deadline = request.form.get("deadline", "").strip() or None
            if not 2 <= len(name) <= 80 or target is None or saved is None:
                flash("Add a goal name and valid target and saved amounts.", "error")
            elif deadline and not valid_iso_date(deadline):
                flash("Enter a valid target date.", "error")
            else:
                db.execute(
                    """INSERT INTO savings_goals
                       (student_id, name, target_amount, saved_amount, deadline)
                       VALUES (?, ?, ?, ?, ?)""",
                    (session["student_id"], name, target, saved, deadline),
                )
                db.commit()
                flash("Savings goal created.", "success")
                return redirect(url_for("savings"))
        goals = db.execute(
            "SELECT * FROM savings_goals WHERE student_id = ? ORDER BY created_at DESC",
            (session["student_id"],),
        ).fetchall()
        balance = db.execute(
            """SELECT COALESCE(SUM(CASE WHEN kind = 'income' THEN amount ELSE -amount END), 0)
               AS balance FROM transactions WHERE student_id = ?""",
            (session["student_id"],),
        ).fetchone()["balance"]
        outstanding = db.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM loans WHERE student_id = ? AND status = 'open'",
            (session["student_id"],),
        ).fetchone()["total"]
        balance -= outstanding
        return render_template("savings.html", goals=goals, balance=balance)

    @app.route("/savings/<int:goal_id>/delete", methods=["POST"])
    @login_required
    def delete_savings_goal(goal_id: int) -> Any:
        get_db().execute(
            "DELETE FROM savings_goals WHERE id = ? AND student_id = ?",
            (goal_id, session["student_id"]),
        )
        get_db().commit()
        flash("Savings goal removed.", "success")
        return redirect(url_for("savings"))

    @app.route("/savings/<int:goal_id>/update", methods=["POST"])
    @login_required
    def update_savings_goal(goal_id: int) -> Any:
        db = get_db()
        goal = db.execute(
            "SELECT id, name, target_amount, saved_amount FROM savings_goals WHERE id = ? AND student_id = ?",
            (goal_id, session["student_id"]),
        ).fetchone()
        if goal is None:
            abort(404)
        raw_saved = request.form.get("saved_amount", "").strip()
        try:
            saved = round(float(raw_saved), 2)
        except ValueError:
            saved = -1
        if not 0 <= saved <= 1_000_000_000:
            flash("Enter a valid saved amount of zero or more.", "error")
        else:
            db.execute(
                "UPDATE savings_goals SET saved_amount = ? WHERE id = ? AND student_id = ?",
                (saved, goal_id, session["student_id"]),
            )
            db.commit()
            if goal["saved_amount"] < goal["target_amount"] <= saved:
                flash(f"Achievement unlocked — you reached your “{goal['name']}” goal! ✦", "success")
            else:
                flash("Savings progress updated.", "success")
        return redirect(url_for("savings"))

    @app.route("/loans", methods=["GET", "POST"])
    @login_required
    def loans() -> Any:
        db = get_db()
        if request.method == "POST":
            borrower = request.form.get("borrower_name", "").strip()
            amount = valid_amount(request.form.get("amount", ""))
            lent_date = request.form.get("lent_date", "").strip()
            due_date = request.form.get("due_date", "").strip() or None
            note = request.form.get("note", "").strip()
            if not 2 <= len(borrower) <= 80:
                flash("Borrower name must be between 2 and 80 characters.", "error")
            elif amount is None:
                flash("Enter an amount greater than zero.", "error")
            elif not valid_iso_date(lent_date):
                flash("Enter a valid date you lent the money.", "error")
            elif due_date and (not valid_iso_date(due_date) or due_date < lent_date):
                flash("The return date must be valid and on or after the lent date.", "error")
            elif len(note) > 240:
                flash("Note must be 240 characters or fewer.", "error")
            else:
                db.execute(
                    """INSERT INTO loans
                       (student_id, borrower_name, amount, lent_date, due_date, note)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (session["student_id"], borrower, amount, lent_date, due_date, note),
                )
                db.commit()
                flash(f"Added {borrower}'s loan. We'll remind you here as the due date approaches.", "success")
                return redirect(url_for("loans"))
        records = db.execute(
            """SELECT * FROM loans WHERE student_id = ?
               ORDER BY CASE status WHEN 'open' THEN 0 ELSE 1 END,
                        due_date IS NULL, due_date, lent_date DESC""",
            (session["student_id"],),
        ).fetchall()
        outstanding = sum(record["amount"] for record in records if record["status"] == "open")
        returned = sum(record["amount"] for record in records if record["status"] == "returned")
        return render_template(
            "loans.html", loans=records, outstanding=outstanding, returned=returned
        )

    @app.route("/loans/<int:loan_id>/returned", methods=["POST"])
    @login_required
    def mark_loan_returned(loan_id: int) -> Any:
        db = get_db()
        loan = db.execute(
            "SELECT * FROM loans WHERE id = ? AND student_id = ? AND status = 'open'",
            (loan_id, session["student_id"]),
        ).fetchone()
        if loan is None:
            abort(404)
        db.execute(
            "UPDATE loans SET status = 'returned', returned_date = ? WHERE id = ? AND student_id = ?",
            (date.today().isoformat(), loan_id, session["student_id"]),
        )
        db.execute(
            """INSERT INTO transactions
               (student_id, kind, category, amount, transaction_date, description)
               VALUES (?, 'income', 'Loan repayment', ?, ?, ?)""",
            (
                session["student_id"],
                loan["amount"],
                date.today().isoformat(),
                f"Returned by {loan['borrower_name']}",
            ),
        )
        db.commit()
        flash(f"Marked {loan['borrower_name']} as returned and recorded the money.", "success")
        return redirect(url_for("loans"))

    @app.route("/loans/<int:loan_id>/delete", methods=["POST"])
    @login_required
    def delete_loan(loan_id: int) -> Any:
        db = get_db()
        loan = db.execute(
            "SELECT id FROM loans WHERE id = ? AND student_id = ?",
            (loan_id, session["student_id"]),
        ).fetchone()
        if loan is None:
            abort(404)
        db.execute("DELETE FROM loans WHERE id = ? AND student_id = ?", (loan_id, session["student_id"]))
        db.commit()
        flash("Loan record removed.", "success")
        return redirect(url_for("loans"))

    @app.route("/reports")
    @login_required
    def reports() -> Any:
        period = request.args.get("period", "monthly")
        if period not in {"daily", "weekly", "monthly"}:
            period = "monthly"
        today = date.today()
        if period == "daily":
            start = today - timedelta(days=6)
            group_format = "%Y-%m-%d"
        elif period == "weekly":
            start = today - timedelta(days=7 * 7 - 1)
            group_format = "%Y-%W"
        else:
            start = (today.replace(day=1) - timedelta(days=155)).replace(day=1)
            group_format = "%Y-%m"
        db = get_db()
        transactions_data = db.execute(
            """SELECT kind, strftime(?, transaction_date) AS period, SUM(amount) AS total
               FROM transactions WHERE student_id = ? AND transaction_date >= ?
               GROUP BY kind, period ORDER BY period""",
            (group_format, session["student_id"], start.isoformat()),
        ).fetchall()
        category_data = db.execute(
            """SELECT category, SUM(amount) AS total FROM transactions
               WHERE student_id = ? AND kind = 'expense' AND transaction_date >= ?
               GROUP BY category ORDER BY total DESC""",
            (session["student_id"], start.isoformat()),
        ).fetchall()
        series: dict[str, dict[str, float]] = {}
        for row in transactions_data:
            series.setdefault(row["period"], {"income": 0, "expense": 0})[row["kind"]] = row["total"]
        income_total = sum(item["income"] for item in series.values())
        expense_total = sum(item["expense"] for item in series.values())
        return render_template(
            "reports.html",
            period=period,
            labels=list(series.keys()),
            income_values=[series[key]["income"] for key in series],
            expense_values=[series[key]["expense"] for key in series],
            category_data=category_data,
            income_total=income_total,
            expense_total=expense_total,
            highest=category_data[0] if category_data else None,
        )

    @app.route("/reports/export.csv")
    @login_required
    def export_csv() -> Response:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Date", "Type", "Category", "Amount", "Description"])
        records = get_db().execute(
            """SELECT transaction_date, kind, category, amount, description
               FROM transactions WHERE student_id = ?
               ORDER BY transaction_date DESC, id DESC""",
            (session["student_id"],),
        )
        writer.writerows(tuple(record) for record in records)
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=spendsmart-transactions.csv"},
        )

    @app.route("/profile", methods=["GET", "POST"])
    @login_required
    def profile() -> Any:
        db = get_db()
        student = db.execute("SELECT * FROM students WHERE id = ?", (session["student_id"],)).fetchone()
        if request.method == "POST":
            if request.form.get("action") == "change_password":
                current_password = request.form.get("current_password", "")
                new_password = request.form.get("new_password", "")
                confirmation = request.form.get("confirm_new_password", "")
                if not check_password_hash(student["password_hash"], current_password):
                    flash("Your current password is incorrect.", "error")
                elif len(new_password) < 8:
                    flash("New password must contain at least 8 characters.", "error")
                elif new_password != confirmation:
                    flash("New passwords do not match.", "error")
                else:
                    db.execute(
                        "UPDATE students SET password_hash = ? WHERE id = ?",
                        (generate_password_hash(new_password), session["student_id"]),
                    )
                    db.commit()
                    flash("Password changed successfully.", "success")
                    return redirect(url_for("profile"))
            else:
                name = request.form.get("full_name", "").strip()
                college = request.form.get("college", "").strip()
                if not 2 <= len(name) <= 80 or not 2 <= len(college) <= 120:
                    flash("Name and college must contain valid information.", "error")
                else:
                    db.execute(
                        "UPDATE students SET full_name = ?, college = ? WHERE id = ?",
                        (name, college, session["student_id"]),
                    )
                    db.commit()
                    flash("Profile updated.", "success")
                    return redirect(url_for("profile"))
        return render_template("profile.html", student=student)

    @app.errorhandler(400)
    def bad_request(error: Any) -> tuple[str, int]:
        return render_template(
            "error.html",
            code=400,
            title="That request didn’t go through",
            message=getattr(error, "description", "Please check your form and try again."),
        ), 400

    @app.errorhandler(404)
    def not_found(_error: Any) -> tuple[str, int]:
        return render_template(
            "error.html", code=404, title="Page not found", message="We couldn’t find that page or record."
        ), 404

    return app


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(current_database())
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def current_database() -> str:
    from flask import current_app

    return current_app.config["DATABASE"]


def get_current_user() -> sqlite3.Row | None:
    student_id = session.get("student_id")
    if not student_id:
        return None
    return get_db().execute("SELECT id, full_name, email FROM students WHERE id = ?", (student_id,)).fetchone()


def init_db() -> None:
    db = get_db()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            college TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
            kind TEXT NOT NULL CHECK (kind IN ('income', 'expense')),
            category TEXT NOT NULL,
            amount REAL NOT NULL CHECK (amount > 0),
            transaction_date TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS budgets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
            month TEXT NOT NULL,
            category TEXT NOT NULL,
            amount REAL NOT NULL CHECK (amount > 0),
            UNIQUE (student_id, month, category)
        );
        CREATE TABLE IF NOT EXISTS savings_goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            target_amount REAL NOT NULL CHECK (target_amount > 0),
            saved_amount REAL NOT NULL DEFAULT 0 CHECK (saved_amount >= 0),
            deadline TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS loans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
            borrower_name TEXT NOT NULL,
            amount REAL NOT NULL CHECK (amount > 0),
            lent_date TEXT NOT NULL,
            due_date TEXT,
            note TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'returned')),
            returned_date TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_transactions_student_date
            ON transactions(student_id, transaction_date);
        """
    )
    db.commit()


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "5000")),
        debug=os.environ.get("FLASK_DEBUG") == "1",
    )
