import re
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

from app import create_app


class SpendSmartTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "test.db"
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-key",
                "DATABASE": str(self.database),
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def csrf(self, client=None):
        client = client or self.client
        response = client.get("/login")
        match = re.search(rb'name="csrf_token" value="([^"]+)"', response.data)
        if match:
            return match.group(1).decode()
        with client.session_transaction() as browser_session:
            return browser_session["_csrf_token"]

    def register(self, client=None, name="Aanya Sharma", email="aanya@example.edu"):
        client = client or self.client
        token = self.csrf(client)
        return client.post(
            "/register",
            data={
                "csrf_token": token,
                "full_name": name,
                "email": email,
                "college": "North Campus University",
                "password": "secure-pass-123",
                "confirm_password": "secure-pass-123",
            },
            follow_redirects=True,
        )

    def test_registration_login_and_private_dashboard(self):
        response = self.register()
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Good ", response.data)
        connection = sqlite3.connect(self.database)
        try:
            password_hash = connection.execute(
                "SELECT password_hash FROM students WHERE email = ?",
                ("aanya@example.edu",),
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertNotEqual(password_hash, "secure-pass-123")

        logout_token = self.csrf()
        self.client.post("/logout", data={"csrf_token": logout_token}, follow_redirects=True)
        token = self.csrf()
        response = self.client.post(
            "/login",
            data={"csrf_token": token, "email": "aanya@example.edu", "password": "wrong-pass"},
        )
        self.assertIn(b"Email or password is incorrect.", response.data)
        response = self.client.post(
            "/login",
            data={"csrf_token": self.csrf(), "email": "aanya@example.edu", "password": "secure-pass-123"},
            follow_redirects=True,
        )
        self.assertIn(b"Good ", response.data)

    def test_finance_flows_reports_and_export(self):
        self.register()
        token = self.csrf()
        response = self.client.post(
            "/transactions/new",
            data={
                "csrf_token": token,
                "kind": "income",
                "category": "Pocket money",
                "amount": "12000",
                "transaction_date": "2026-11-05",
                "description": "Monthly allowance",
            },
            follow_redirects=True,
        )
        self.assertIn(b"Monthly allowance", response.data)
        response = self.client.post(
            "/transactions/new",
            data={
                "csrf_token": self.csrf(),
                "kind": "expense",
                "category": "Food",
                "amount": "750",
                "transaction_date": "2026-11-06",
                "description": "Lunch",
            },
            follow_redirects=True,
        )
        self.assertIn(b"Lunch", response.data)
        response = self.client.post(
            "/budgets",
            data={"csrf_token": self.csrf(), "month": "2026-11", "category": "Food", "amount": "800"},
            follow_redirects=True,
        )
        self.assertIn(b"Food", response.data)
        dashboard = self.client.get("/dashboard")
        self.assertIn(b"budget nearly reached", dashboard.data)
        self.assertIn(b"Your month, in a nutshell", dashboard.data)
        self.assertIn(b"Spend on yourself", dashboard.data)
        response = self.client.post(
            "/savings",
            data={
                "csrf_token": self.csrf(),
                "name": "New laptop",
                "target_amount": "50000",
                "saved_amount": "0",
                "deadline": "",
            },
            follow_redirects=True,
        )
        self.assertIn(b"New laptop", response.data)
        connection = sqlite3.connect(self.database)
        try:
            goal_id = connection.execute("SELECT id FROM savings_goals").fetchone()[0]
        finally:
            connection.close()
        response = self.client.post(
            f"/savings/{goal_id}/update",
            data={"csrf_token": self.csrf(), "saved_amount": "3000"},
            follow_redirects=True,
        )
        self.assertIn(b"\xe2\x82\xb93,000.00", response.data)
        response = self.client.post(
            f"/savings/{goal_id}/update",
            data={"csrf_token": self.csrf(), "saved_amount": "50000"},
            follow_redirects=True,
        )
        self.assertIn(b"Achievement unlocked", response.data)
        self.assertEqual(self.client.get("/reports?period=monthly").status_code, 200)
        csv_response = self.client.get("/reports/export.csv")
        self.assertEqual(csv_response.mimetype, "text/csv")
        self.assertIn(b"Monthly allowance", csv_response.data)
        self.assertIn(b"Lunch", self.client.get("/transactions?q=Lunch").data)
        self.assertNotIn(b"Monthly allowance", self.client.get("/transactions?kind=expense").data)

    def test_student_data_isolation_and_csrf(self):
        self.register()
        response = self.client.post("/transactions/new", data={"kind": "expense"})
        self.assertEqual(response.status_code, 400)
        response = self.client.post(
            "/transactions/new",
            data={
                "csrf_token": self.csrf(),
                "kind": "expense",
                "category": "Food",
                "amount": "25",
                "transaction_date": "2026-11-06",
                "description": "Private lunch",
            },
        )
        self.assertEqual(response.status_code, 302)
        connection = sqlite3.connect(self.database)
        try:
            transaction_id = connection.execute("SELECT id FROM transactions").fetchone()[0]
        finally:
            connection.close()

        second_client = self.app.test_client()
        self.register(second_client, name="Ravi Kumar", email="ravi@example.edu")
        self.assertNotIn(b"Private lunch", second_client.get("/transactions").data)
        response = second_client.get(f"/transactions/{transaction_id}/edit")
        self.assertEqual(response.status_code, 404)

    def test_income_shortcut_and_personal_loan_reminders(self):
        self.register()
        income_form = self.client.get("/transactions/new?kind=income")
        self.assertIn(b'value="income" checked', income_form.data)
        self.assertIn(b"Aanya Sharma", self.client.get("/dashboard").data)
        response = self.client.post(
            "/loans",
            data={
                "csrf_token": self.csrf(),
                "borrower_name": "Ravi",
                "amount": "1200",
                "lent_date": date.today().isoformat(),
                "due_date": date.today().isoformat(),
                "note": "Festival tickets",
            },
            follow_redirects=True,
        )
        self.assertIn(b"Ravi", response.data)
        self.assertIn(b"Festival tickets", response.data)
        dashboard = self.client.get("/dashboard")
        self.assertIn(b"Ravi", dashboard.data)
        self.assertIn(b"Due today", dashboard.data)
        connection = sqlite3.connect(self.database)
        try:
            loan_id = connection.execute("SELECT id FROM loans").fetchone()[0]
        finally:
            connection.close()

        other_client = self.app.test_client()
        self.register(other_client, name="Meera Shah", email="meera@example.edu")
        self.assertNotIn(b"Ravi", other_client.get("/loans").data)
        self.assertEqual(
            other_client.post(
                f"/loans/{loan_id}/returned",
                data={"csrf_token": self.csrf(other_client)},
            ).status_code,
            404,
        )

        response = self.client.post(
            f"/loans/{loan_id}/returned",
            data={"csrf_token": self.csrf()},
            follow_redirects=True,
        )
        self.assertIn(b"Marked Ravi as returned", response.data)
        self.assertIn(b"Loan repayment", self.client.get("/transactions?kind=income").data)

    def test_signed_in_pages_render_and_profile_updates(self):
        self.register()
        for path in ("/dashboard", "/transactions", "/budgets", "/savings", "/reports", "/profile"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)
        response = self.client.post(
            "/profile",
            data={
                "csrf_token": self.csrf(),
                "full_name": "Aanya Updated",
                "college": "North Campus University",
            },
            follow_redirects=True,
        )
        self.assertIn(b"Aanya Updated", response.data)
        response = self.client.post(
            "/profile",
            data={
                "csrf_token": self.csrf(),
                "action": "change_password",
                "current_password": "secure-pass-123",
                "new_password": "new-secure-pass-456",
                "confirm_new_password": "new-secure-pass-456",
            },
            follow_redirects=True,
        )
        self.assertIn(b"Password changed successfully.", response.data)


if __name__ == "__main__":
    unittest.main()
