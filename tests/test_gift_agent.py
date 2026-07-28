import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from app import GiftRecommendationAgent
from tools import _api_price, _to_number
from tracing import TraceLogger


class GiftAgentTests(unittest.TestCase):
    def test_price_helpers(self):
        self.assertEqual(_to_number("1.500.000 ₫"), 1_500_000)
        self.assertEqual(_api_price(200_000.0), 200_000)

    def test_request_validation_normalizes_query_and_budget(self):
        result = GiftRecommendationAgent._validate_request(
            {
                "query": [" sách hay ", ""],
                "min_price": 500_000,
                "max_price": 200_000,
            }
        )
        self.assertEqual(result["query"], ["sách hay"])
        self.assertEqual(result["min_price"], 200_000)
        self.assertEqual(result["max_price"], 500_000)

    def test_final_result_drops_hallucinated_product(self):
        request_data = {
            "query": ["tai nghe bluetooth"],
            "min_price": 200_000.0,
            "max_price": 500_000.0,
        }
        search_output = {
            "items": [
                {
                    "title": "Tai nghe thật",
                    "price": 300_000.0,
                    "price_text": "300.000 ₫",
                    "currency": "VND",
                    "url": "https://example.com/real",
                    "source": "Cửa hàng",
                    "matched_query": "tai nghe bluetooth",
                }
            ],
            "warnings": [],
        }
        llm_result = {
            "recommendations": [
                {
                    "url": "https://example.com/fake",
                    "reason": "Sản phẩm bịa.",
                },
                {
                    "url": "https://example.com/real",
                    "reason": "Phù hợp sở thích nghe nhạc.",
                },
            ],
            "message": "Có một gợi ý.",
        }

        result = GiftRecommendationAgent._build_final_result(
            llm_result, request_data, search_output
        )
        self.assertEqual(len(result["recommendations"]), 1)
        self.assertEqual(result["recommendations"][0]["name"], "Tai nghe thật")
        self.assertEqual(
            result["recommendations"][0]["price"], 300_000.0
        )

    def test_trace_logger_writes_jsonl_and_redacts_secrets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            tracer = TraceLogger(temp_dir)
            tracer.log(
                "api_test",
                data={
                    "api_key": "must-not-appear",
                    "error": (
                        "https://example.com/search?"
                        "api_key=must-not-appear&q=gift"
                    ),
                },
            )
            events = [
                json.loads(line)
                for line in tracer.path.read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(events[0]["step"], "trace_started")
        self.assertEqual(events[1]["step"], "api_test")
        self.assertEqual(events[1]["data"]["api_key"], "[REDACTED]")
        serialized = json.dumps(events)
        self.assertNotIn("must-not-appear", serialized)

    def test_recommend_pipeline_records_major_trace_steps(self):
        class FakeProvider:
            model_name = "gpt-4o-mini"

            def call_function(self, user_content, system_prompt, tool):
                if tool["function"]["name"] == "analyze_gift_request":
                    return {
                        "query": ["tai nghe bluetooth"],
                        "min_price": 200_000,
                        "max_price": 500_000,
                    }
                return {
                    "query": ["tai nghe bluetooth"],
                    "min_price": 200_000,
                    "max_price": 500_000,
                    "recommendations": [
                        {
                            "name": "Tên từ LLM",
                            "price": 1,
                            "price_text": "1 ₫",
                            "currency": "VND",
                            "domain": "domain",
                            "reason": "Phù hợp nghe nhạc.",
                            "url": "https://example.com/real",
                            "source": "Nguồn",
                        }
                    ],
                    "message": "Có một gợi ý.",
                    "warnings": [],
                }

        def fake_search(
            queries,
            min_price=None,
            max_price=None,
            limit_per_query=6,
            trace=None,
        ):
            if trace:
                trace("search_batch_started", data={"queries": queries})
            output = {
                "items": [
                    {
                        "title": "Tai nghe thật",
                        "price": 300_000.0,
                        "price_text": "300.000 ₫",
                        "currency": "VND",
                        "url": "https://example.com/real",
                        "source": "Cửa hàng",
                        "matched_query": queries[0],
                    }
                ],
                "warnings": [],
            }
            if trace:
                trace("search_batch_completed", data=output)
            return output

        with tempfile.TemporaryDirectory() as temp_dir:
            tracer = TraceLogger(temp_dir)
            agent = GiftRecommendationAgent(FakeProvider(), tracer)
            with patch("app.search_gifts", side_effect=fake_search):
                result = agent.recommend("Quà cho người thích nghe nhạc")
            events = [
                json.loads(line)
                for line in tracer.path.read_text(encoding="utf-8").splitlines()
            ]

        steps = [event["step"] for event in events]
        self.assertIn("input_received", steps)
        self.assertIn("analyze_request_completed", steps)
        self.assertIn("search_batch_completed", steps)
        self.assertIn("final_response_tool_result", steps)
        self.assertEqual(steps[-1], "run_completed")
        self.assertEqual(result["recommendations"][0]["name"], "Tai nghe thật")


if __name__ == "__main__":
    unittest.main()
