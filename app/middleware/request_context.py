"""Request ID propagation and structured API errors (Steps 4.5.3–4.5.4)."""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ):
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response


def _error_body(
    request: Request, *, error: str, code: str, status_code: int
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    return JSONResponse(
        status_code=status_code,
        content={"error": error, "code": code, "request_id": request_id},
        headers={REQUEST_ID_HEADER: request_id},
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        code = f"HTTP_{exc.status_code}"
        detail = exc.detail
        if isinstance(detail, dict):
            error = str(detail.get("message") or detail.get("error") or detail)
        else:
            error = str(detail)
        if exc.status_code == 401:
            code = "UNAUTHORIZED"
        elif exc.status_code == 404:
            code = "NOT_FOUND"
        elif exc.status_code == 429:
            code = "RATE_LIMITED"
        return _error_body(request, error=error, code=code, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ):
        return _error_body(
            request,
            error="Validation failed",
            code="VALIDATION_ERROR",
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        logger.error(
            "unhandled_exception request_id=%s %s",
            request_id,
            exc,
            exc_info=True,
        )
        return _error_body(
            request,
            error="Internal server error",
            code="INTERNAL_ERROR",
            status_code=500,
        )
