"""Smoke tests for the backend's public system routes."""

import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.app.backend.api.routers.system import router


class HealthEndpointTests(unittest.TestCase):
    def test_health_reports_service_is_ready(self) -> None:
        app = FastAPI()
        app.include_router(router)

        response = TestClient(app).get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})


if __name__ == "__main__":
    unittest.main()
