"""Chuẩn bị payload UI-ready và cache ảnh sản phẩm ở backend."""

from __future__ import annotations

import hashlib
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import requests

PROJECT_DIR = Path(__file__).resolve().parents[1]
IMAGE_CACHE_DIR = PROJECT_DIR / "logs" / "product_images"
MAX_IMAGE_BYTES = 4 * 1024 * 1024
IMAGE_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
DEFAULT_IMAGE_HOST_SUFFIXES = (
    "gstatic.com",
    "googleusercontent.com",
    "ggpht.com",
)


def _allowed_image_hosts() -> tuple[str, ...]:
    configured = os.getenv("IMAGE_HOSTS", "")
    custom = tuple(
        host.strip().lower().lstrip(".")
        for host in configured.split(",")
        if host.strip()
    )
    return custom or DEFAULT_IMAGE_HOST_SUFFIXES


def _is_allowed_image_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    hostname = parsed.hostname.lower().rstrip(".")
    return any(
        hostname == suffix or hostname.endswith(f".{suffix}")
        for suffix in _allowed_image_hosts()
    )


def _cached_file(digest: str) -> Path | None:
    for extension in IMAGE_CONTENT_TYPES.values():
        candidate = IMAGE_CACHE_DIR / f"{digest}{extension}"
        if candidate.is_file():
            return candidate
    return None


def cache_product_image(url: str | None) -> str | None:
    """Tải ảnh tin cậy về backend và trả URL media nội bộ."""

    if not url or not _is_allowed_image_url(url):
        return None

    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    cached = _cached_file(digest)
    if cached:
        return f"/media/products/{cached.name}"

    try:
        response = requests.get(
            url,
            headers={"User-Agent": "Gifty/1.0 product-image-cache"},
            timeout=12,
            stream=True,
            allow_redirects=False,
        )
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").split(";")[0].lower()
        extension = IMAGE_CONTENT_TYPES.get(content_type)
        if not extension:
            return None

        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > MAX_IMAGE_BYTES:
            return None

        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_IMAGE_BYTES:
                return None
            chunks.append(chunk)
    except (requests.RequestException, ValueError, OSError):
        return None

    IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    destination = IMAGE_CACHE_DIR / f"{digest}{extension}"
    temporary = IMAGE_CACHE_DIR / f"{digest}.{threading.get_ident()}.tmp"
    try:
        temporary.write_bytes(b"".join(chunks))
        temporary.replace(destination)
    except OSError:
        temporary.unlink(missing_ok=True)
        return None
    return f"/media/products/{destination.name}"


def format_vnd(value: float | int | None) -> str:
    if value is None:
        return "Liên hệ"
    return f"{int(round(float(value))):,}".replace(",", ".") + " ₫"


def budget_label(min_price: float | None, max_price: float | None) -> str:
    if min_price is not None and max_price is not None:
        return f"{format_vnd(min_price)} – {format_vnd(max_price)}"
    if max_price is not None:
        return f"Tối đa {format_vnd(max_price)}"
    if min_price is not None:
        return f"Từ {format_vnd(min_price)}"
    return "Không giới hạn giá"


def prepare_chat_response(
    result: dict[str, Any],
    image_resolver: Callable[[str | None], str | None] = cache_product_image,
) -> dict[str, Any]:
    """Biến kết quả agent thành payload cuối cùng mà frontend chỉ việc render."""

    raw_products = list(result.get("recommendations") or [])
    with ThreadPoolExecutor(max_workers=max(1, min(len(raw_products), 5))) as executor:
        local_images = list(
            executor.map(
                lambda product: image_resolver(product.get("image_url")),
                raw_products,
            )
        )

    products = []
    for product, local_image in zip(raw_products, local_images):
        products.append(
            {
                "name": str(product.get("name") or ""),
                "price": product.get("price"),
                "price_label": (
                    str(product.get("price_text"))
                    if product.get("price_text")
                    else format_vnd(product.get("price"))
                ),
                "currency": str(product.get("currency") or "VND"),
                "domain": str(product.get("domain") or ""),
                "reason": str(product.get("reason") or ""),
                "url": str(product.get("url") or ""),
                "source": product.get("source"),
                "image_url": local_image,
            }
        )

    min_price = result.get("min_price")
    max_price = result.get("max_price")
    queries = list(result.get("query") or [])
    return {
        "message": str(result.get("message") or ""),
        "products": products,
        "filters": {
            "query": queries,
            "min_price": min_price,
            "max_price": max_price,
            "budget_label": budget_label(min_price, max_price),
            "search_group_count": len(queries),
        },
        "warnings": list(result.get("warnings") or []),
    }
