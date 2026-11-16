import unittest
from unittest.mock import patch

import psycopg
from fastapi.testclient import TestClient

from app.main import app


class DatabaseFailureTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.connection = patch(
            "app.main.connect",
            side_effect=psycopg.OperationalError("sensitive connection details"),
        ).start()
        self.addCleanup(patch.stopall)

    def test_liveness_does_not_need_database(self):
        response = self.client.get("/health/live")
        self.assertEqual(response.status_code, 200)
        self.connection.assert_not_called()

    def test_readiness_fails_without_exposing_driver_error(self):
        response = self.client.get("/health/ready")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "Catalogue unavailable"})

    def test_catalogue_fails_without_exposing_driver_error(self):
        response = self.client.get("/items")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "Catalogue unavailable"})

    def test_release_still_available_without_database(self):
        response = self.client.get("/version")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"release": "demo-v1"})
        self.connection.assert_not_called()


if __name__ == "__main__":
    unittest.main()
