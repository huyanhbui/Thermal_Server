"""Khuôn dạng lỗi API thống nhất (docs/03 §1)."""
from __future__ import annotations

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str,
                 detail=None, retry_after_s: float | None = None):
        self.status = status
        self.code = code
        self.message = message
        self.detail = detail
        self.retry_after_s = retry_after_s
        super().__init__(message)

    def body(self) -> dict:
        err = {"code": self.code, "message": self.message}
        if self.detail is not None:
            err["detail"] = self.detail
        if self.retry_after_s is not None:
            err["retry_after_s"] = self.retry_after_s
        return {"error": err}


def error_response(exc: ApiError) -> JSONResponse:
    headers = {}
    if exc.retry_after_s is not None:
        headers["Retry-After"] = str(int(exc.retry_after_s))
    return JSONResponse(exc.body(), status_code=exc.status, headers=headers)


async def api_error_handler(_request: Request, exc: ApiError):
    return error_response(exc)


async def validation_error_handler(_request: Request, exc: RequestValidationError):
    # Keep HTTP 422 — matches FastAPI/Pydantic convention and existing tests.
    # Pydantic v2 có thể giữ ValueError gốc trong ctx.error. JSONResponse
    # không serialize exception đó, khiến chính đường trả lỗi thành 500.
    detail = []
    for item in exc.errors():
        safe = dict(item)
        if isinstance(safe.get("ctx"), dict):
            safe["ctx"] = {
                str(key): str(value)
                for key, value in safe["ctx"].items()
            }
        detail.append(safe)
    return JSONResponse(
        {"error": {
            "code": "BAD_REQUEST",
            "message": "Yêu cầu không hợp lệ.",
            "detail": detail,
        }},
        status_code=422)
