from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from uuid import uuid4


class QuantError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def decimal(value: Any) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise QuantError("INVALID_NUMBER", f"非法数值：{value!r}") from exc
    if not result.is_finite():
        raise QuantError("INVALID_NUMBER", "金额/数量不能是 NaN 或无穷大")
    return result


def utc(value: str | datetime) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if result.tzinfo is None:
        raise QuantError("MISSING_TIMEZONE", f"时间必须带时区：{value}")
    return result.astimezone(timezone.utc)


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      default=lambda v: str(v) if isinstance(v, (Decimal, Path)) else v.isoformat(),
                      allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-" + uuid4().hex)
    try:
        temporary.write_text(canonical(value) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def finite_float(value: Any) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise QuantError("INVALID_NUMBER", "配置数值必须有限")
    return result
