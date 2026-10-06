"""
Catches anything not already handled as an HTTPException. Logs the full
exception (with traceback) server-side, but returns only a generic
message to the client — never a stack trace, file path, or exception
class name, which can leak implementation details useful to an attacker.
"""

import logging
from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("unhandled_errors")


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Something went wrong on our end. Please try again."},
    )
