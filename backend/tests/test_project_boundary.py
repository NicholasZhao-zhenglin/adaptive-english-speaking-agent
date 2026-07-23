import unittest
from unittest.mock import patch

from app import app


class ProjectBoundaryTestCase(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_health_endpoint_identifies_standalone_service(self):
        response = self.client.get("/api/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {"service": "adaptive-english-speaking-agent", "status": "healthy"},
        )

    def test_unrelated_personal_assistant_routes_are_not_exposed(self):
        for path in ("/api/idea/list", "/api/todo/list", "/api/diary/list"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)

    def test_dashboard_internal_failure_keeps_json_error_contract(self):
        with patch("app.get_dashboard", side_effect=OSError("private path")):
            response = self.client.get("/api/english/dashboard")

        self.assertEqual(response.status_code, 500)
        self.assertTrue(response.is_json)
        self.assertEqual(response.get_json(), {"error": "学习计划读取失败"})
        self.assertNotIn("private path", response.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
