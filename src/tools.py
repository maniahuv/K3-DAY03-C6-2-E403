"""Các tool bên ngoài dùng bởi gift recommendation agent."""

from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from dotenv import load_dotenv

load_dotenv()


class SearchToolError(RuntimeError):
    """Lỗi có thể hiển thị khi search provider không hoạt động."""


def _api_price(value: float) -> int | float:
    """SerpAPI từ chối price có phần thập phân .0."""

    return int(value) if float(value).is_integer() else value


def _safe_serpapi_error(exc: Exception) -> str:
    """Lấy message từ response nhưng không làm lộ API key trong URL."""

    response = getattr(exc, "response", None)
    if response is not None:
        try:
            payload = response.json()
            if isinstance(payload, dict) and payload.get("error"):
                return str(payload["error"])
        except (ValueError, TypeError):
            pass
        status_code = getattr(response, "status_code", None)
        if status_code:
            return f"HTTP {status_code}"
    return exc.__class__.__name__


def _to_number(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None

    text = value.lower().strip()
    match = re.search(r"\d[\d.,\s]*", text)
    if not match:
        return None

    digits = re.sub(r"[^\d]", "", match.group(0))
    if not digits:
        return None

    number = float(digits)
    if "triệu" in text or "trieu" in text:
        number *= 1_000_000
    elif re.search(r"\d\s*k\b", text):
        number *= 1_000
    return number


def _normalize_result(raw: dict[str, Any], matched_query: str) -> dict[str, Any]:
    price = _to_number(
        raw.get("extracted_price")
        or raw.get("price")
        or raw.get("price_from")
    )
    return {
        "title": str(raw.get("title") or raw.get("name") or "").strip(),
        "price": price,
        "price_text": str(raw.get("price") or "").strip() or None,
        "currency": "VND",
        "url": raw.get("product_link") or raw.get("link") or raw.get("url"),
        "source": raw.get("source") or raw.get("merchant") or raw.get("displayed_link"),
        "thumbnail": raw.get("thumbnail"),
        "rating": raw.get("rating"),
        "matched_query": matched_query,
    }


def search_products(
    query: str,
    min_price: float | None = None,
    max_price: float | None = None,
    limit: int = 6,
) -> list[dict[str, Any]]:
    """Tìm sản phẩm bằng SerpAPI Google Shopping và lọc lại theo giá VND."""

    api_key = os.getenv("Search_API") or os.getenv("SEARCH_API_KEY")
    if not api_key:
        raise SearchToolError("Thiếu Search_API trong file .env")

    params: dict[str, Any] = {
        "engine": "google_shopping",
        "q": query,
        "hl": "vi",
        "gl": "vn",
        "sort_by": 1,
    }
    if min_price is not None:
        params["min_price"] = _api_price(min_price)
    if max_price is not None:
        params["max_price"] = _api_price(max_price)

    try:
        import serpapi

        client = serpapi.Client(api_key=api_key)
        payload = client.search(params)
    except Exception as exc:
        detail = _safe_serpapi_error(exc)
        raise SearchToolError(f"SerpAPI trả về lỗi: {detail}") from exc

    if payload.get("error"):
        message = str(payload["error"])
        if "hasn't returned any results" in message.lower():
            return []
        raise SearchToolError(message)

    raw_results = (
        payload.get("shopping_results")
        or payload.get("items")
        or payload.get("organic_results")
        or []
    )

    results: list[dict[str, Any]] = []
    for raw in raw_results:
        item = _normalize_result(raw, query)
        if not item["title"] or not item["url"]:
            continue

        price = item["price"]
        # Khi có budget, bỏ kết quả không có giá vì không thể xác minh.
        if (min_price is not None or max_price is not None) and price is None:
            continue
        if min_price is not None and price is not None and price < min_price:
            continue
        if max_price is not None and price is not None and price > max_price:
            continue

        results.append(item)
        if len(results) >= limit:
            break
    return results


def search_gifts(
    queries: list[str],
    min_price: float | None = None,
    max_price: float | None = None,
    limit_per_query: int = 6,
    trace: Callable[..., None] | None = None,
) -> dict[str, Any]:
    """Chạy nhiều query, gom kết quả và loại URL trùng nhau."""

    items: list[dict[str, Any]] = []
    warnings: list[str] = []
    seen_urls: set[str] = set()

    def run_one(query: str) -> tuple[str, list[dict[str, Any]], str | None]:
        if trace:
            trace(
                "search_query_started",
                data={
                    "query": query,
                    "min_price": min_price,
                    "max_price": max_price,
                },
            )
        try:
            found = search_products(query, min_price, max_price, limit_per_query)
        except SearchToolError as exc:
            if trace:
                trace(
                    "search_query_completed",
                    status="error",
                    data={"query": query, "error": str(exc)},
                )
            return query, [], str(exc)
        if trace:
            trace(
                "search_query_completed",
                data={
                    "query": query,
                    "result_count": len(found),
                    "results": found,
                },
            )
        return query, found, None

    if trace:
        trace(
            "search_batch_started",
            data={
                "query_count": len(queries),
                "queries": queries,
                "min_price": min_price,
                "max_price": max_price,
            },
        )
    worker_count = max(1, min(len(queries), 5))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        query_results = executor.map(run_one, queries)

    # executor.map giữ nguyên thứ tự query để output có tính ổn định.
    for query, found, error in query_results:
        if error:
            warnings.append(f"{query}: {error}")
            continue
        for item in found:
            url = str(item["url"])
            if url in seen_urls:
                continue
            seen_urls.add(url)
            items.append(item)

    output = {"items": items, "warnings": warnings}
    if trace:
        trace(
            "search_batch_completed",
            status="warning" if warnings else "ok",
            data={
                "result_count": len(items),
                "warning_count": len(warnings),
                "results": items,
                "warnings": warnings,
            },
        )
    return output


AVAILABLE_TOOLS = {"search_gifts": search_gifts}
