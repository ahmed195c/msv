"""
MSV Load Test — simulates real users browsing the permits system.

Usage:
    locust -f locustfile.py --host=http://127.0.0.1:8000

Then open http://localhost:8089 and set:
  - Number of users : 100
  - Spawn rate      : 10  (adds 10 users/sec until 100 reached)

Set credentials below or pass via env:
  USERNAME=admin PASSWORD=pass locust -f locustfile.py --host=...
"""

import os
import random
import re

from locust import HttpUser, between, task


# ── Credentials ────────────────────────────────────────────────────────────────
USERNAME = os.getenv("MSV_USERNAME", "admin")
PASSWORD = os.getenv("MSV_PASSWORD", "admin")


def _extract_ids(html: str, pattern: str) -> list[int]:
    """Pull integer IDs from href patterns like /permits/pest-control/123/"""
    return [int(m) for m in re.findall(pattern, html)]


def _csrf(html: str) -> str:
    m = re.search(r'csrfmiddlewaretoken.*?value="([^"]+)"', html)
    return m.group(1) if m else ""


# ── Admin / Data-Entry user ─────────────────────────────────────────────────────
class AdminUser(HttpUser):
    """
    Simulates a data-entry or admin staff member:
    checks clearances, browses companies, views permit details.
    """
    weight = 5  # 5 out of every 10 simulated users
    wait_time = between(2, 6)

    # IDs discovered while browsing — shared across tasks within one user session
    _clearance_ids: list[int] = []
    _company_ids:   list[int] = []

    def on_start(self):
        """Log in once at session start."""
        resp = self.client.get("/login/", name="/login/")
        csrf = _csrf(resp.text)
        self.client.post("/login/", data={
            "username": USERNAME,
            "password": PASSWORD,
            "csrfmiddlewaretoken": csrf,
        }, name="/login/ [POST]")

    # ── High-frequency pages ──────────────────────────────────────────────────

    @task(4)
    def clearances(self):
        resp = self.client.get("/clearances/", name="/clearances/")
        ids = _extract_ids(resp.text, r"/permits/pest-control/(\d+)/")
        if ids:
            self._clearance_ids = ids[:20]

    @task(3)
    def clearances_vehicle_tab(self):
        self.client.get("/clearances/?tab=pesticide_transport", name="/clearances/?tab=vehicle")

    @task(2)
    def companies(self):
        resp = self.client.get("/companies/", name="/companies/")
        ids = _extract_ids(resp.text, r"/companies/(\d+)/")
        if ids:
            self._company_ids = ids[:20]

    @task(2)
    def home(self):
        self.client.get("/home/", name="/home/")

    @task(2)
    def field_work_list(self):
        self.client.get("/field-work/", name="/field-work/")

    # ── Detail pages ──────────────────────────────────────────────────────────

    @task(2)
    def clearance_detail(self):
        if not self._clearance_ids:
            self.clearances()
            return
        pk = random.choice(self._clearance_ids)
        self.client.get(f"/permits/pest-control/{pk}/", name="/permits/pest-control/[id]/")

    @task(1)
    def company_detail(self):
        if not self._company_ids:
            self.companies()
            return
        pk = random.choice(self._company_ids)
        self.client.get(f"/companies/{pk}/", name="/companies/[id]/")

    @task(1)
    def companies_page2(self):
        self.client.get("/companies/?page=2", name="/companies/?page=2")

    @task(1)
    def permits_list(self):
        self.client.get("/permits/", name="/permits/")

    @task(1)
    def engineers(self):
        self.client.get("/enginers/", name="/enginers/")


# ── Inspector user ──────────────────────────────────────────────────────────────
class InspectorUser(HttpUser):
    """
    Simulates an inspector: mainly checks pending inspections.
    """
    weight = 3
    wait_time = between(3, 8)

    _clearance_ids: list[int] = []

    def on_start(self):
        resp = self.client.get("/login/", name="/login/")
        csrf = _csrf(resp.text)
        self.client.post("/login/", data={
            "username": USERNAME,
            "password": PASSWORD,
            "csrfmiddlewaretoken": csrf,
        }, name="/login/ [POST]")

    @task(5)
    def clearances_pending(self):
        resp = self.client.get(
            "/clearances/?status=inspection_pending",
            name="/clearances/?status=inspection_pending",
        )
        ids = _extract_ids(resp.text, r"/permits/pest-control/(\d+)/")
        if ids:
            self._clearance_ids = ids[:10]

    @task(3)
    def clearance_detail(self):
        if not self._clearance_ids:
            self.clearances_pending()
            return
        pk = random.choice(self._clearance_ids)
        self.client.get(f"/permits/pest-control/{pk}/", name="/permits/pest-control/[id]/")

    @task(2)
    def clearances_received(self):
        self.client.get(
            "/clearances/?status=inspection_received",
            name="/clearances/?status=inspection_received",
        )

    @task(1)
    def home(self):
        self.client.get("/home/", name="/home/")


# ── Field-work supervisor ───────────────────────────────────────────────────────
class FieldWorkUser(HttpUser):
    """
    Simulates a field-work supervisor: checks assigned orders.
    """
    weight = 2
    wait_time = between(4, 10)

    _fw_ids: list[int] = []

    def on_start(self):
        resp = self.client.get("/login/", name="/login/")
        csrf = _csrf(resp.text)
        self.client.post("/login/", data={
            "username": USERNAME,
            "password": PASSWORD,
            "csrfmiddlewaretoken": csrf,
        }, name="/login/ [POST]")

    @task(4)
    def field_work_list(self):
        resp = self.client.get("/field-work/", name="/field-work/")
        ids = _extract_ids(resp.text, r"/field-work/(\d+)/")
        if ids:
            self._fw_ids = ids[:10]

    @task(3)
    def field_work_detail(self):
        if not self._fw_ids:
            self.field_work_list()
            return
        pk = random.choice(self._fw_ids)
        self.client.get(f"/field-work/{pk}/", name="/field-work/[id]/")

    @task(1)
    def field_work_search(self):
        self.client.get("/field-work/?q=test", name="/field-work/?q=")
