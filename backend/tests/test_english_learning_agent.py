import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from assistants import english_assistant, english_learning_agent
from app import app


class EnglishLearningAgentTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.profile_file = os.path.join(self.temp_dir.name, "english_profile.json")
        self.state_file = os.path.join(self.temp_dir.name, "english_learning_state.json")
        self.session_file = os.path.join(self.temp_dir.name, "english_sessions.json")
        self.memory_file = os.path.join(self.temp_dir.name, "english_memory.json")
        self.today_file = os.path.join(self.temp_dir.name, "english_today.json")
        self.patches = [
            patch.object(english_learning_agent, "PROFILE_FILE", self.profile_file),
            patch.object(english_learning_agent, "STATE_FILE", self.state_file),
            patch.object(english_learning_agent, "SESSIONS_FILE", self.session_file),
            patch.object(english_assistant, "MEMORY_FILE", self.memory_file),
            patch.object(english_assistant, "TODAY_FILE", self.today_file),
        ]
        for file_patch in self.patches:
            file_patch.start()
        self.client = app.test_client()

    def tearDown(self):
        for file_patch in reversed(self.patches):
            file_patch.stop()
        self.temp_dir.cleanup()

    def test_profile_is_normalized_and_persisted(self):
        profile = english_learning_agent.save_profile({
            "goals": [" AI 技术面试 ", "日常交流"],
            "level": "B2",
            "daily_minutes": 200,
            "interests": ["人工智能", "旅行"],
        })

        self.assertEqual(profile["goals"], ["AI 技术面试", "日常交流"])
        self.assertEqual(profile["level"], "B2")
        self.assertEqual(profile["daily_minutes"], 60)
        with open(self.profile_file, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["interests"], ["人工智能", "旅行"])

    def test_wrong_answer_reduces_mastery_and_schedules_immediate_review(self):
        now = datetime(2026, 7, 22, 9, 0, tzinfo=timezone.utc)
        english_learning_agent.record_attempts(
            day=3,
            attempts=[{
                "expression": "That makes sense",
                "correct": True,
                "exercise_type": "multiple_choice",
            }],
            now=now,
        )
        result = english_learning_agent.record_attempts(
            day=3,
            attempts=[{
                "expression": "That makes sense",
                "correct": False,
                "exercise_type": "scenario_choice",
                "error_type": "context",
            }],
            now=now,
        )

        item = result["items"]["that makes sense"]
        self.assertEqual(item["streak"], 0)
        self.assertEqual(item["wrong_count"], 1)
        self.assertEqual(item["error_counts"]["context"], 1)
        self.assertEqual(item["next_review_at"], "2026-07-22")
        self.assertLess(item["mastery"], 0.5)

    def test_daily_plan_increases_review_load_after_low_accuracy(self):
        english_learning_agent.save_profile({
            "goals": ["AI 技术面试"],
            "level": "B1",
            "daily_minutes": 20,
            "interests": ["大模型"],
        })
        with open(self.session_file, "w", encoding="utf-8") as handle:
            json.dump([
                {"accuracy": 0.4, "completed_at": "2026-07-21T09:00:00+00:00"},
                {"accuracy": 0.5, "completed_at": "2026-07-20T09:00:00+00:00"},
            ], handle)
        with open(self.state_file, "w", encoding="utf-8") as handle:
            json.dump({
                "items": {},
                "error_totals": {"context": 4, "recall": 1},
            }, handle)

        plan = english_learning_agent.build_daily_plan(
            today=datetime(2026, 7, 22, tzinfo=timezone.utc)
        )

        self.assertEqual(plan["theme"], "AI 技术面试")
        self.assertEqual(plan["new_expression_count"], 4)
        self.assertGreater(plan["review_expression_count"], plan["new_expression_count"])
        self.assertEqual(plan["exercise_focus"], "场景选择与角色扮演")
        self.assertEqual(plan["exercise_mix"]["scenario_choice"], 5)
        self.assertEqual(sum(plan["exercise_mix"].values()), 10)
        self.assertIn("近期正确率", plan["reason"])

    def test_due_reviews_prioritize_overdue_low_mastery_items(self):
        with open(self.state_file, "w", encoding="utf-8") as handle:
            json.dump({
                "items": {
                    "high risk": {
                        "expression": "High risk",
                        "meaning": "高风险",
                        "mastery": 0.2,
                        "next_review_at": "2026-07-20",
                    },
                    "known": {
                        "expression": "Known",
                        "meaning": "已掌握",
                        "mastery": 0.9,
                        "next_review_at": "2026-07-21",
                    },
                    "future": {
                        "expression": "Future",
                        "meaning": "未来",
                        "mastery": 0.1,
                        "next_review_at": "2026-07-30",
                    },
                },
                "error_totals": {},
            }, handle)

        reviews = english_learning_agent.get_due_reviews(
            count=2,
            today=datetime(2026, 7, 22, tzinfo=timezone.utc),
        )

        self.assertEqual([item["expression"] for item in reviews], ["High risk", "Known"])

    def test_attempt_api_returns_updated_dashboard(self):
        response = self.client.post("/api/english/attempts", json={
            "day": 1,
            "attempts": [{
                "expression": "I am with you",
                "meaning": "我同意",
                "correct": True,
                "exercise_type": "fill_blank",
            }],
        })

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["session"]["correct_count"], 1)
        self.assertIn("plan", payload["dashboard"])

    def test_dashboard_endpoint_returns_json_contract(self):
        response = self.client.get("/api/english/dashboard")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.is_json)
        self.assertIn("plan", response.get_json())

    def test_attempt_api_rejects_unbounded_batches(self):
        response = self.client.post("/api/english/attempts", json={
            "day": 1,
            "attempts": [
                {"expression": f"Expression {index}", "correct": True}
                for index in range(101)
            ],
        })

        self.assertEqual(response.status_code, 400)
        self.assertIn("最多", response.get_json()["error"])

    def test_daily_generation_uses_agent_plan_and_dynamic_new_item_count(self):
        plan = {
            "theme": "AI 技术面试",
            "level": "B2",
            "context_hint": "大模型",
            "new_expression_count": 4,
            "review_expression_count": 8,
            "exercise_focus": "场景选择与角色扮演",
            "reason": "近期正确率较低",
        }
        expression_texts = ["Count me in", "Take your time", "Sounds good", "I doubt it"]
        expressions = [
            {
                "expression": expression_text,
                "meaning": f"含义 {index}",
                "scene": "面试",
                "example": "Example",
                "example_cn": "例句",
            }
            for index, expression_text in enumerate(expression_texts)
        ]
        with patch.object(english_assistant, "build_daily_plan", return_value=plan), patch.object(
            english_assistant,
            "_generate_batch",
            return_value=(expressions, {"scenario": "面试", "task": "回答"}, "复习"),
        ) as generate_batch:
            result = english_assistant.get_today_expression()

        self.assertEqual(len(result["expressions"]), 4)
        self.assertEqual(result["learning_plan"], plan)
        self.assertEqual(generate_batch.call_args.args[:2], (4, 1))
        self.assertEqual(generate_batch.call_args.kwargs["plan"], plan)

    def test_review_selection_prefers_items_due_by_mastery_scheduler(self):
        due = [{
            "expression": "That makes sense",
            "meaning": "有道理",
            "next_review_at": "2026-07-22",
        }]
        with patch.object(english_assistant, "get_due_reviews", return_value=due):
            reviews = english_assistant._get_review_expressions(day_number=5, count=1)

        self.assertEqual(reviews[0]["expression"], "That makes sense")
        self.assertEqual(reviews[0]["source"], "adaptive_scheduler")

    def test_practice_prompt_applies_agent_exercise_mix(self):
        plan = {
            "exercise_focus": "填空与主动回忆",
            "exercise_mix": {
                "multiple_choice": 2,
                "fill_blank": 5,
                "matching": 1,
                "scenario_choice": 2,
            },
        }

        prompt = english_assistant._build_practice_prompt(2, "today", "review", plan=plan)

        self.assertIn("填空题（fill_blank）5题", prompt)
        self.assertIn("重点训练方向是“填空与主动回忆”", prompt)

    def test_expression_dedup_removes_duplicates_inside_same_batch(self):
        expressions = [
            {"expression": "That makes sense"},
            {"expression": "That makes sense!"},
        ]

        valid, duplicate_count = english_assistant._dedup(expressions, history=[])

        self.assertEqual(len(valid), 1)
        self.assertEqual(duplicate_count, 1)

    def test_generation_stops_after_five_failed_fill_attempts(self):
        plan = {
            "theme": "日常交流",
            "level": "B1",
            "context_hint": "生活",
            "new_expression_count": 4,
            "review_expression_count": 6,
            "exercise_focus": "场景选择与角色扮演",
        }
        duplicate = [{
            "expression": "Same expression",
            "meaning": "相同表达",
            "scene": "生活",
            "example": "Example",
            "example_cn": "例句",
        }] * 4
        with patch.object(english_assistant, "build_daily_plan", return_value=plan), patch.object(
            english_assistant,
            "_generate_batch",
            side_effect=[(duplicate, {}, "复习")] + [duplicate] * 5,
        ) as generate_batch:
            with self.assertRaisesRegex(RuntimeError, "补位失败"):
                english_assistant.get_today_expression()

        self.assertEqual(generate_batch.call_count, 6)


if __name__ == "__main__":
    unittest.main()
