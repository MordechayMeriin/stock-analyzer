"""One error shape for every API failure: ``{"code": ..., "message": ...}`` with a matching status."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from stock_analyzer.config import MissingCredential
from stock_analyzer.errors import AnalyzerError
from stock_analyzer.llm import LLMError

log = logging.getLogger(__name__)

STATUS_BY_CODE: dict[str, int] = {
    "company_not_found": 404,
    "filing_not_found": 404,
    "report_not_found": 404,
    "node_not_found": 404,
    "page_not_found": 404,
    "not_cached": 409,
    "live_disabled": 403,
    "selection_too_large": 413,
    "validation_error": 422,
    "report_selection_failed": 422,
    "currency_mismatch": 422,
    "parse_error": 422,
    "upstream_error": 502,
    "upstream_not_found": 502,
    "upstream_truncated": 502,
    "llm_error": 502,
    "configuration_error": 503,
    "missing_credential": 503,
    "storage_unavailable": 503,
    "internal_error": 500,
}


class ErrorOut(BaseModel):
    code: str
    message: str


def error_response(code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=STATUS_BY_CODE.get(code, 500), content=ErrorOut(code=code, message=message).model_dump()
    )


def to_error(exc: Exception) -> ErrorOut:
    if isinstance(exc, AnalyzerError):
        return ErrorOut(code=exc.code, message=exc.message)
    if isinstance(exc, MissingCredential):
        return ErrorOut(code="missing_credential", message=str(exc))
    if isinstance(exc, LLMError):
        return ErrorOut(code="llm_error", message=str(exc).split("\n--- last raw output ---", 1)[0])
    if isinstance(exc, ValueError):
        return ErrorOut(code="validation_error", message=str(exc))
    return ErrorOut(code="internal_error", message="internal server error")


def install(app: FastAPI) -> None:
    @app.exception_handler(AnalyzerError)
    async def _analyzer(_: Request, exc: AnalyzerError) -> JSONResponse:
        return error_response(exc.code, exc.message)

    @app.exception_handler(MissingCredential)
    async def _credential(_: Request, exc: MissingCredential) -> JSONResponse:
        return error_response("missing_credential", str(exc))

    @app.exception_handler(LLMError)
    async def _llm(_: Request, exc: LLMError) -> JSONResponse:
        err = to_error(exc)
        return error_response(err.code, err.message)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        parts = [f"{'.'.join(str(x) for x in e['loc'] if x != 'body')}: {e['msg']}" for e in exc.errors()]
        return error_response("validation_error", "; ".join(parts) or "invalid request")

    @app.exception_handler(ValueError)
    async def _value(_: Request, exc: ValueError) -> JSONResponse:
        return error_response("validation_error", str(exc))

    @app.exception_handler(Exception)
    async def _internal(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error", exc_info=exc)
        return error_response("internal_error", "internal server error")
