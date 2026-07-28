"""Flask web UI cho gift recommendation chatbot."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_from_directory

from app import GiftRecommendationAgent, _exception_chain
from presentation import IMAGE_CACHE_DIR, prepare_chat_response

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False

LOG_DIR = Path(__file__).resolve().parents[1] / "logs"
RUN_ID_PATTERN = re.compile(r"^[a-f0-9]{12}$")


def _public_backend_error(exc: Exception) -> tuple[str, str, int]:
    chain = _exception_chain(exc)
    messages = " | ".join(item["message"] for item in chain)
    current: BaseException | None = exc
    socket_blocked = False
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if (
            getattr(current, "winerror", None) == 10013
            or getattr(current, "errno", None) == 10013
        ):
            socket_blocked = True
            break
        current = current.__cause__ or current.__context__

    if socket_blocked or "WinError 10013" in messages:
        return (
            "BACKEND_OUTBOUND_BLOCKED",
            (
                "Backend bị Windows/sandbox chặn kết nối ra OpenAI. "
                "Hãy chạy web.py trong PowerShell độc lập có quyền mạng."
            ),
            503,
        )
    if exc.__class__.__name__ == "APIConnectionError":
        return (
            "OPENAI_CONNECTION_ERROR",
            "Backend không kết nối được tới OpenAI API.",
            503,
        )
    return "BACKEND_ERROR", str(exc), 500


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/health")
def health():
    return jsonify({"status": "ok"})


def _recommendation_response(message: str):
    """Chạy toàn bộ backend pipeline và trả response contract cuối."""

    message = message.strip()
    if not message:
        return jsonify({"error": "Vui lòng nhập mô tả món quà bạn cần tìm."}), 400
    if len(message) > 2_000:
        return jsonify({"error": "Nội dung quá dài, tối đa 2.000 ký tự."}), 400

    agent = GiftRecommendationAgent()
    trace_url = f"/api/trace/{agent.tracer.run_id}"
    try:
        result = agent.recommend(message)
        agent.tracer.log(
            "frontend_payload_started",
            data={"product_count": len(result.get("recommendations", []))},
        )
        response_payload = prepare_chat_response(result)
        agent.tracer.log(
            "frontend_payload_completed",
            data={
                "product_count": len(response_payload["products"]),
                "cached_image_count": sum(
                    bool(item["image_url"])
                    for item in response_payload["products"]
                ),
            },
        )
        response = jsonify(
            {
                "ok": True,
                **response_payload,
                "trace_id": agent.tracer.run_id,
                "trace_url": trace_url,
            }
        )
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Trace-Id"] = agent.tracer.run_id
        return response
    except Exception as exc:
        error_code, public_message, status_code = _public_backend_error(exc)
        response = jsonify(
            {
                "ok": False,
                "error_code": error_code,
                "error": public_message,
                "trace_id": agent.tracer.run_id,
                "trace_url": trace_url,
            }
        )
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Trace-Id"] = agent.tracer.run_id
        return response, status_code


@app.get("/api/recommendations")
def recommendations():
    """API chính: frontend gửi GET với query parameter `message`."""

    message = str(request.args.get("message") or "")
    return _recommendation_response(message)


@app.post("/api/chat")
def chat():
    """Endpoint tương thích cho client cũ; frontend mới không dùng route này."""

    payload = request.get_json(silent=True) or {}
    return _recommendation_response(str(payload.get("message") or ""))


@app.get("/api/trace/<run_id>")
def get_trace(run_id: str):
    if not RUN_ID_PATTERN.fullmatch(run_id):
        return jsonify({"error": "Trace ID không hợp lệ."}), 400

    matches = list(LOG_DIR.glob(f"trace_*_{run_id}.jsonl"))
    if len(matches) != 1:
        return jsonify({"error": "Không tìm thấy trace."}), 404

    events = []
    with matches[0].open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                events.append(json.loads(line))
    return jsonify({"run_id": run_id, "events": events})


@app.get("/media/products/<filename>")
def product_image(filename: str):
    if not re.fullmatch(r"[a-f0-9]{64}\.(?:jpg|png|webp|gif)", filename):
        return jsonify({"error": "Tên ảnh không hợp lệ."}), 400
    response = send_from_directory(IMAGE_CACHE_DIR, filename, max_age=86_400)
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def main():
    port = int(os.getenv("PORT", "8000"))
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
