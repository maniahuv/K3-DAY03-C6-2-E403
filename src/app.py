"""CLI và orchestration cho gift recommendation agent."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any

from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from prompts import (  # noqa: E402
    ANALYZE_GIFT_REQUEST_PROMPT,
    ANALYZE_GIFT_REQUEST_TOOL,
    FINAL_RESPONSE_PROMPT,
    FINAL_RESPONSE_TOOL,
)
from providers import OpenAIProvider  # noqa: E402
from tools import search_gifts  # noqa: E402
from tracing import TraceLogger  # noqa: E402

load_dotenv()


def _exception_chain(exc: BaseException) -> list[dict[str, str]]:
    """Thu thập nguyên nhân lồng nhau để trace không mất lỗi socket/TLS."""

    chain: list[dict[str, str]] = []
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen and len(chain) < 10:
        seen.add(id(current))
        chain.append(
            {
                "type": current.__class__.__name__,
                "module": current.__class__.__module__,
                "message": str(current),
            }
        )
        current = current.__cause__ or current.__context__
    return chain


class GiftRecommendationAgent:
    """Pipeline: analyze -> search tool -> LLM structured response."""

    def __init__(
        self,
        provider: OpenAIProvider | None = None,
        tracer: TraceLogger | None = None,
    ):
        self.provider = provider or OpenAIProvider()
        self.tracer = tracer or TraceLogger()

    @staticmethod
    def _validate_request(data: dict[str, Any]) -> dict[str, Any]:
        queries = data.get("query")
        if not isinstance(queries, list):
            queries = [queries] if isinstance(queries, str) else []
        queries = [
            str(query).strip()
            for query in queries
            if str(query).strip()
        ][:5]
        if not queries:
            raise ValueError("LLM không sinh được query tìm kiếm hợp lệ")

        min_price = data.get("min_price")
        max_price = data.get("max_price")
        if min_price is not None:
            min_price = max(0, float(min_price))
        if max_price is not None:
            max_price = max(0, float(max_price))
        if (
            min_price is not None
            and max_price is not None
            and min_price > max_price
        ):
            min_price, max_price = max_price, min_price

        return {
            "query": queries,
            "min_price": min_price,
            "max_price": max_price,
        }

    @staticmethod
    def _build_final_result(
        llm_result: dict[str, Any],
        request_data: dict[str, Any],
        search_output: dict[str, Any],
    ) -> dict[str, Any]:
        """Giữ JSON đúng schema và chặn sản phẩm/giá/URL do LLM tự tạo."""

        items_by_url = {
            str(item["url"]): item
            for item in search_output["items"]
            if item.get("url")
        }
        recommendations: list[dict[str, Any]] = []

        raw_recommendations = llm_result.get("recommendations", [])
        if not isinstance(raw_recommendations, list):
            raw_recommendations = []

        for raw in raw_recommendations:
            if not isinstance(raw, dict):
                continue
            source_item = items_by_url.get(str(raw.get("url", "")))
            if source_item is None:
                continue
            recommendations.append(
                {
                    "name": source_item["title"],
                    "price": source_item["price"],
                    "price_text": source_item["price_text"],
                    "currency": source_item["currency"],
                    "domain": source_item["matched_query"],
                    "reason": str(raw.get("reason") or "").strip(),
                    "url": source_item["url"],
                    "source": source_item["source"],
                    "image_url": source_item.get("thumbnail"),
                }
            )
            if len(recommendations) >= 5:
                break

        message = str(llm_result.get("message") or "").strip()
        if not message:
            message = (
                "Đã tìm được các món quà phù hợp."
                if recommendations
                else "Không tìm thấy sản phẩm phù hợp với yêu cầu."
            )

        return {
            "query": request_data["query"],
            "min_price": request_data["min_price"],
            "max_price": request_data["max_price"],
            "recommendations": recommendations,
            "message": message,
            "warnings": search_output["warnings"],
        }

    def recommend(self, user_input: str) -> dict[str, Any]:
        try:
            if not user_input.strip():
                raise ValueError("Input không được để trống")

            self.tracer.log(
                "input_received",
                data={
                    "user_input": user_input,
                    "model": self.provider.model_name,
                },
            )
            self.tracer.log("analyze_request_started")
            parsed = self.provider.call_function(
                user_input,
                ANALYZE_GIFT_REQUEST_PROMPT,
                ANALYZE_GIFT_REQUEST_TOOL,
            )
            self.tracer.log(
                "analyze_request_tool_result",
                data={"raw_arguments": parsed},
            )
            request_data = self._validate_request(parsed)
            self.tracer.log(
                "analyze_request_completed",
                data={"parsed_request": request_data},
            )

            search_output = search_gifts(
                request_data["query"],
                request_data["min_price"],
                request_data["max_price"],
                trace=self.tracer.log,
            )

            llm_payload = {
                "USER_INPUT": user_input,
                "PARSED_REQUEST": request_data,
                "SEARCH_RESULTS": search_output["items"],
                "SEARCH_WARNINGS": search_output["warnings"],
            }
            self.tracer.log(
                "final_response_started",
                data={
                    "search_result_count": len(search_output["items"]),
                    "search_warning_count": len(search_output["warnings"]),
                },
            )
            result = self.provider.call_function(
                json.dumps(llm_payload, ensure_ascii=False),
                FINAL_RESPONSE_PROMPT,
                FINAL_RESPONSE_TOOL,
            )
            self.tracer.log(
                "final_response_tool_result",
                data={"raw_arguments": result},
            )
            final_result = self._build_final_result(
                result, request_data, search_output
            )
            self.tracer.log(
                "run_completed",
                data={"final_result": final_result},
            )
            return final_result
        except Exception as exc:
            self.tracer.log(
                "run_failed",
                status="error",
                data={
                    "error_type": exc.__class__.__name__,
                    "error": str(exc),
                    "cause_chain": _exception_chain(exc),
                },
            )
            raise


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Tìm và đề xuất quà tặng bằng OpenAI + SerpAPI."
    )
    parser.add_argument(
        "query",
        nargs="*",
        help="Mô tả người nhận, dịp tặng, sở thích và khoảng giá.",
    )
    args = parser.parse_args()
    user_input = " ".join(args.query).strip()
    if not user_input:
        user_input = input("Bạn đang muốn chọn quà cho ai? ").strip()

    agent = GiftRecommendationAgent()
    print(f"Trace log: {agent.tracer.path}", file=sys.stderr)
    try:
        result = agent.recommend(user_input)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {"error": str(exc)},
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
