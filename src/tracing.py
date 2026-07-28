"""Structured JSONL trace logger cho từng lần chạy agent."""

from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_SECRET_KEY_PATTERN = re.compile(
    r"(api[_-]?key|authorization|access[_-]?token|secret|password)",
    re.IGNORECASE,
)
_SECRET_IN_TEXT_PATTERN = re.compile(
    r"(?i)(api[_-]?key|access[_-]?token|token|authorization)=([^&\s]+)"
)


def _redact(value: Any, key: str = "") -> Any:
    """Che secret theo key và query-string trước khi ghi xuống ổ đĩa."""

    if _SECRET_KEY_PATTERN.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): _redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return _SECRET_IN_TEXT_PATTERN.sub(r"\1=[REDACTED]", value)
    return value


class TraceLogger:
    """Ghi mỗi event thành một JSON object trên một dòng."""

    def __init__(self, log_dir: str | Path | None = None):
        project_dir = Path(__file__).resolve().parents[1]
        self.log_dir = Path(log_dir) if log_dir else project_dir / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.run_id = uuid.uuid4().hex[:12]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.path = self.log_dir / f"trace_{timestamp}_{self.run_id}.jsonl"
        self._sequence = 0
        self._lock = threading.Lock()
        self.log("trace_started", data={"trace_file": str(self.path)})

    def log(
        self,
        step: str,
        status: str = "ok",
        data: Any | None = None,
    ) -> None:
        with self._lock:
            self._sequence += 1
            event = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "run_id": self.run_id,
                "sequence": self._sequence,
                "step": step,
                "status": status,
                "data": _redact(data if data is not None else {}),
            }
            with self.path.open("a", encoding="utf-8") as file:
                file.write(json.dumps(event, ensure_ascii=False) + "\n")
