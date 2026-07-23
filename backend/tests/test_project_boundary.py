import unittest

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


if __name__ == "__main__":
    unittest.main()
