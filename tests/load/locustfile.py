"""Locust load test for NexusAI (Phase 5.2).

Run (API must be listening):
  locust -f tests/load/locustfile.py --host=http://localhost:8000 --users 100 --spawn-rate 10

Record results manually from the Locust UI or CSV export.
"""
from __future__ import annotations

from locust import HttpUser, between, task


class NexusAIUser(HttpUser):
    wait_time = between(1, 3)
    token: str | None = None

    def on_start(self):
        suffix = id(self)
        email = f"loadtest_{suffix}@test.com"
        self.client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": "loadtest123456",
                "full_name": "Load Test",
            },
        )
        resp = self.client.post(
            "/api/v1/auth/login",
            data={"username": email, "password": "loadtest123456"},
        )
        if resp.status_code == 200:
            self.token = resp.json().get("access_token")

    def headers(self):
        if not self.token:
            return {}
        return {"Authorization": f"Bearer {self.token}"}

    @task(5)
    def submit_task(self):
        self.client.post(
            "/api/v1/tasks/",
            json={"goal": "Write a hello world function in Python for load testing"},
            headers=self.headers(),
        )

    @task(10)
    def list_tasks(self):
        self.client.get("/api/v1/tasks/", headers=self.headers())

    @task(3)
    def get_metrics(self):
        self.client.get("/metrics")

    @task(2)
    def search_memory(self):
        self.client.post(
            "/api/v1/memory/search",
            json={"query": "python function", "collection": "tasks"},
            headers=self.headers(),
        )
