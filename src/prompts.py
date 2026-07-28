"""Prompt và function schema cho gift recommendation agent."""

ANALYZE_GIFT_REQUEST_PROMPT = """
Bạn là bộ phân tích yêu cầu chọn quà.

Từ input của người dùng:
1. Trích xuất min_price và max_price theo VND. Nếu không có thì trả null.
2. Sinh từ 2 đến 5 query tìm kiếm ngắn, cụ thể và đa dạng domain quà tặng.
3. Query phải phản ánh người nhận, dịp tặng, sở thích và ràng buộc trong input.
4. Không tự thêm mức giá nếu người dùng không nói đến giá.
5. Luôn gọi function analyze_gift_request; không trả lời bằng text.

Ví dụ domain có thể gồm sách, đồ công nghệ, thời trang, chăm sóc cá nhân,
đồ trang trí, trải nghiệm hoặc đồ thủ công. Chỉ chọn domain phù hợp input.
""".strip()


ANALYZE_GIFT_REQUEST_TOOL = {
    "type": "function",
    "function": {
        "name": "analyze_gift_request",
        "description": "Trả về các query tìm quà và khoảng giá đã chuẩn hóa.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 5,
                },
                "min_price": {"type": ["number", "null"]},
                "max_price": {"type": ["number", "null"]},
            },
            "required": ["query", "min_price", "max_price"],
            "additionalProperties": False,
        },
    },
}


FINAL_RESPONSE_PROMPT = """
Bạn là chuyên gia chọn quà. Bạn nhận được yêu cầu đã phân tích và danh sách
sản phẩm thật từ search tool.

Yêu cầu:
- Chỉ đề xuất sản phẩm có trong SEARCH_RESULTS; tuyệt đối không bịa sản phẩm,
  giá hoặc URL.
- Chọn tối đa 5 món phù hợp nhất, ưu tiên đa dạng domain.
- Giải thích ngắn gọn vì sao từng món phù hợp với người nhận và dịp tặng.
- Giữ nguyên price, price_text, url, source và matched_query từ dữ liệu search.
- Nếu không có kết quả phù hợp, recommendations phải là [] và message giải
  thích rõ.
- Luôn gọi function return_gift_recommendations; không trả lời bằng text.
""".strip()


FINAL_RESPONSE_TOOL = {
    "type": "function",
    "function": {
        "name": "return_gift_recommendations",
        "description": "Trả kết quả tư vấn quà tặng dưới dạng JSON chuẩn.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "min_price": {"type": ["number", "null"]},
                "max_price": {"type": ["number", "null"]},
                "recommendations": {
                    "type": "array",
                    "maxItems": 5,
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "price": {"type": ["number", "null"]},
                            "price_text": {"type": ["string", "null"]},
                            "currency": {"type": "string"},
                            "domain": {"type": "string"},
                            "reason": {"type": "string"},
                            "url": {"type": "string"},
                            "source": {"type": ["string", "null"]},
                        },
                        "required": [
                            "name",
                            "price",
                            "price_text",
                            "currency",
                            "domain",
                            "reason",
                            "url",
                            "source",
                        ],
                        "additionalProperties": False,
                    },
                },
                "message": {"type": "string"},
                "warnings": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": [
                "query",
                "min_price",
                "max_price",
                "recommendations",
                "message",
                "warnings",
            ],
            "additionalProperties": False,
        },
    },
}


# Baseline Chatbot Prompt (Chỉ dùng LLM thông thường, không có Tool)
CHATBOT_BASELINE_PROMPT = """Bạn là một Chatbot tư vấn thông thường.
Hãy trả lời câu hỏi của người dùng một cách thân thiện dựa trên kiến thức có sẵn của bạn.
Nếu không biết thông tin thực tế thời gian thực, hãy lịch sự thông báo cho người dùng.
""".strip()


# ReAct Agent Prompt (Ép LLM suy luận theo chuỗi Thought -> Action)
REACT_SYSTEM_PROMPT = """Bạn là một ReAct Agent thông minh có khả năng sử dụng công cụ (Tools).

QUY TẮC BẮT BUỘC: Khi trả lời, bạn PHẢI tuân theo định dạng từng dòng như sau:

Thought: Suy luận của bạn về bước tiếp theo cần làm.
Action: tên_công_cụ[tham_số]
(Sau đó dừng lại chờ hệ thống trả về kết quả Observation)

Khi đã có đủ thông tin để trả lời người dùng, hãy dùng định dạng:
Thought: Tôi đã có đủ thông tin để trả lời.
Final Answer: Câu trả lời hoàn chỉnh cuối cùng gửi cho người dùng.

BẮT ĐẦU:
""".strip()


# 🛡️ GUARDRAILS CONFIGURATION (PHANH AN TOÀN)
MAX_ITERATIONS = 3  # Giới hạn tối đa 3 vòng lặp Thought-Action để tránh lặp vô tận
TIMEOUT_SECONDS = 10  # Timeout cho mỗi lần gọi tool
