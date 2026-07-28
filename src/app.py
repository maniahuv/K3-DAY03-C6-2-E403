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
    CHATBOT_BASELINE_PROMPT,
    REACT_SYSTEM_PROMPT,
    MAX_ITERATIONS,
)
from providers import OpenAIProvider, get_llm_provider  # noqa: E402
from tools import AVAILABLE_TOOLS, search_gifts, get_weather, search_flights  # noqa: E402
from tracing import TraceLogger  # noqa: E402

load_dotenv()


def load_test_cases():
    """Đọc bộ test cases từ config/test_cases.json của Role 1"""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(base_dir, "config", "test_cases.json")
    if not os.path.exists(config_path):
        config_path = "test_cases.json"
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


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
                },
            )
            raise


def run_baseline_chatbot(user_query: str, provider):
    """
    Dựng Chatbot gốc (Baseline) không có công cụ.
    """
    print(f"\n💬 [CHATBOT BASELINE] Câu hỏi: {user_query}")
    print(f"⚙️ System Prompt: {CHATBOT_BASELINE_PROMPT.strip()}")
    
    # Gọi LLM Provider thực hiện sinh câu trả lời
    response = provider.generate(user_query, system_prompt=CHATBOT_BASELINE_PROMPT)
    print(f"🤖 Chatbot trả lời:\n{response}")
    return response


def parse_react_action(llm_output: str):
    """
    Trích xuất tên tool và tham số từ chuỗi 'Action: tool_name[arg]' hoặc 'Action: tool_name[arg1, arg2]'
    """
    pattern = r"Action:\s*([a_zA_Z0_9_]+)\s*[\[\(](.*?)[\]\)]"
    match = re.search(pattern, llm_output, re.DOTALL | re.IGNORECASE)
    if not match:
        return None, None
    
    tool_name = match.group(1).strip()
    raw_args = match.group(2).strip()
    
    args = []
    if raw_args:
        parts = raw_args.split(",")
        for part in parts:
            clean_part = part.strip().strip("'\"")
            if clean_part:
                args.append(clean_part)
                
    return tool_name, args


def execute_tool(tool_name: str, args: list):
    """Thực thi tool an toàn từ AVAILABLE_TOOLS"""
    if tool_name not in AVAILABLE_TOOLS:
        return f"LỖI: Công cụ '{tool_name}' không tồn tại trong danh sách AVAILABLE_TOOLS."
    
    func = AVAILABLE_TOOLS[tool_name]
    try:
        if not args:
            return str(func())
        elif len(args) == 1:
            return str(func(args[0]))
        else:
            return str(func(*args))
    except Exception as e:
        return f"LỖI THỰC THI TOOL '{tool_name}': {str(e)}"


def run_react_agent(user_query: str, provider):
    """
    [Role 4 - Mốc 3] Dựng vòng lặp ReAct Agent (Thought -> Action -> Observation) hoàn chỉnh có Guardrails (MAX_ITERATIONS).
    """
    print(f"\n🤖 [REACT AGENT] Câu hỏi: {user_query}")
    step = 0
    conversation_history = f"Câu hỏi của người dùng: {user_query}\n"
    
    while step < MAX_ITERATIONS:
        step += 1
        print(f"\n--- 🔄 Vòng lặp ReAct (Step {step}/{MAX_ITERATIONS}) ---")
        
        # 1. Gọi LLM sinh suy luận (Thought) & hành động (Action)
        response = provider.generate(conversation_history, system_prompt=REACT_SYSTEM_PROMPT)
        print(f"🤖 Agent Output:\n{response}")
        
        # 2. Kiểm tra câu trả lời cuối cùng (Final Answer)
        if "Final Answer:" in response:
            final_ans = response.split("Final Answer:")[-1].strip()
            print(f"\n🏁 FINAL ANSWER:\n{final_ans}")
            return response
            
        # 3. Phân tích Action để thực thi Tool
        tool_name, args = parse_react_action(response)
        if tool_name:
            print(f"🛠️ Action parsed: {tool_name}{args}")
            obs = execute_tool(tool_name, args)
            print(f"👁️ Observation: {obs}")
            
            # Cập nhật context cho bước tiếp theo
            conversation_history += f"\n{response}\nObservation: {obs}\n"
        else:
            # Nếu không tìm thấy Action và cũng không có Final Answer
            print(f"\n🏁 FINAL ANSWER (Kết thúc suy luận):\n{response}")
            return response

    if step >= MAX_ITERATIONS:
        print(f"\n🛡️ GUARDRAIL TRIGGERED: Đã đạt giới hạn tối đa {MAX_ITERATIONS} bước. Ngắt lặp an toàn!")


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


def get_test_question(test: dict) -> str:
    """Lấy nội dung câu hỏi/input hỗ trợ cả 2 định dạng schema ('question' hoặc 'input')"""
    return test.get("question") or test.get("input") or ""


def get_test_category(test: dict) -> str:
    """Lấy danh mục/phân loại hỗ trợ cả 2 định dạng schema ('category' hoặc 'level'/'type')"""
    if "category" in test:
        return test["category"]
    level = test.get("level", "")
    t_type = test.get("type", "")
    return f"{level} - {t_type}".strip(" -")


def run_all_baseline_test_cases(tests, provider):
    """
    [Role 4 - Mốc 2] Chạy khảo sát Chatbot Baseline trên tất cả các Test Cases từ config/test_cases.json
    """
    print("\n==================================================")
    print("📋 [MỐC 2 - ROLE 4] CHẠY CHATBOT BASELINE TRÊN BỘ TEST CASES")
    print("==================================================")
    for test in tests:
        q = get_test_question(test)
        cat = get_test_category(test)
        print(f"\n--------------------------------------------------")
        print(f"📌 Test Case #{test['id']} ({cat}): {q}")
        run_baseline_chatbot(q, provider)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        raise SystemExit(main())
    else:
        print("==================================================")
        print("🏫 ĐẠI HỌC VINUNI - BÀI LAB 3: CHATBOT VS REACT AGENT")
        print("==================================================")
        
        # Khởi tạo Multi-Provider LLM Adapter (Đọc từ biến môi trường LLM_PROVIDER)
        provider = get_llm_provider()
        model_name = getattr(provider, "model_name", "Offline Mock Mode")
        print(f"🔌 LLM Provider đang hoạt động: {provider.__class__.__name__} (Model: {model_name})")
        
        tests = load_test_cases()
        print(f"✅ Đã tải thành công {len(tests)} Test Cases từ config/test_cases.json\n")
        
        # Chạy thử câu test số 3 (Demo Mốc 2 & Mốc 3)
        sample_query = get_test_question(tests[2])
        
        print("--- DEMO 1: CHẠY TRÊN CHATBOT BASELINE ---")
        run_baseline_chatbot(sample_query, provider)
        
        print("\n--- DEMO 2: CHẠY TRÊN REACT AGENT ---")
        run_react_agent(sample_query, provider)

        # [Role 4 - Mốc 2] Khảo sát phản hồi của Chatbot Baseline trên bộ Test Cases
        run_all_baseline_test_cases(tests, provider)
