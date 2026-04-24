"""UW Demo Logging — structured logging with correlation IDs.

Independent logging module for the UW Demo application.
Same pattern as Verity and EDMS but no cross-app imports.

Usage (application startup):
    from uw_demo.app.utils.logging import setup_logging
    setup_logging(service_name="uw_demo")

Usage (getting a logger — standard Python, module-level):
    import logging
    logger = logging.getLogger(__name__)
    logger.info("Pipeline started", extra={"submission_id": "SUB-001"})
"""

import logging
import logging.config
import logging.handlers
import os
from contextvars import ContextVar
from pathlib import Path
from uuid import uuid4


# ══════════════════════════════════════════════════════════════
# CONTEXT VARIABLES — async-safe, auto-propagate through await
# ══════════════════════════════════════════════════════════════

correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")
workflow_run_id_var: ContextVar[str] = ContextVar("workflow_run_id", default="")
step_name_var: ContextVar[str] = ContextVar("step_name", default="")
submission_id_var: ContextVar[str] = ContextVar("submission_id", default="")
service_name_var: ContextVar[str] = ContextVar("service_name", default="unknown")


def generate_correlation_id() -> str:
    """Generate a short, unique correlation ID (12 hex chars)."""
    return uuid4().hex[:12]


# ══════════════════════════════════════════════════════════════
# CONTEXT FILTER — attaches context vars to every log record
# ══════════════════════════════════════════════════════════════

class ContextFilter(logging.Filter):
    """Logging filter that adds context variables to log records."""

    def filter(self, record):
        record.correlation_id = correlation_id_var.get("")
        record.workflow_run_id = workflow_run_id_var.get("")
        record.step_name = step_name_var.get("")
        record.submission_id = submission_id_var.get("")
        record.service = service_name_var.get("unknown")
        return True


# ══════════════════════════════════════════════════════════════
# CONSOLE FORMATTER
# ══════════════════════════════════════════════════════════════

CONSOLE_FORMAT = (
    "%(asctime)s %(levelname)-5s %(name)s"
    " [%(correlation_id)s]"
    " %(message)s"
)

CONSOLE_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"


# ══════════════════════════════════════════════════════════════
# SETUP
# ══════════════════════════════════════════════════════════════

def setup_logging(
    service_name: str,
    log_level: str = None,
    log_format: str = None,
    log_file_enabled: bool = None,
    log_dir: str = None,
):
    """Configure logging for the application.

    Call once at startup, before creating the FastAPI app.
    Reads from environment variables if arguments are not provided.
    """
    level = (log_level or os.getenv("LOG_LEVEL", "INFO")).upper()
    fmt = log_format or os.getenv("LOG_FORMAT", "json")
    file_enabled = log_file_enabled if log_file_enabled is not None else (
        os.getenv("LOG_FILE_ENABLED", "false").lower() == "true"
    )
    directory = log_dir or os.getenv("LOG_DIR", "./logs")

    service_name_var.set(service_name)

    config = _build_config(
        service_name=service_name,
        level=level,
        fmt=fmt,
        file_enabled=file_enabled,
        log_dir=directory,
    )

    logging.config.dictConfig(config)

    logger = logging.getLogger(service_name)
    logger.info(
        "Logging configured: service=%s level=%s format=%s file=%s",
        service_name, level, fmt, file_enabled,
    )


def _build_config(service_name, level, fmt, file_enabled, log_dir):
    """Build a logging.config.dictConfig dictionary."""

    if fmt == "json":
        try:
            import pythonjsonlogger  # noqa: F401
            formatter_config = {
                "()": "pythonjsonlogger.json.JsonFormatter",
                "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
                "rename_fields": {"asctime": "timestamp", "levelname": "level", "name": "logger"},
                "static_fields": {"service": service_name},
            }
        except ImportError:
            fmt = "console"
            formatter_config = None

    if fmt == "console":
        formatter_config = {
            "format": CONSOLE_FORMAT,
            "datefmt": CONSOLE_DATE_FORMAT,
        }

    config = {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {"context": {"()": ContextFilter}},
        "formatters": {"default": formatter_config},
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "formatter": "default",
                "filters": ["context"],
            },
        },
        "root": {"level": level, "handlers": ["console"]},
    }

    if file_enabled:
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        config["handlers"]["file"] = {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(log_path / f"{service_name}.log"),
            "maxBytes": 50_000_000,
            "backupCount": 5,
            "formatter": "default",
            "filters": ["context"],
        }
        config["root"]["handlers"].append("file")

    return config


# ══════════════════════════════════════════════════════════════
# FASTAPI MIDDLEWARE — correlation ID generation/propagation
# ══════════════════════════════════════════════════════════════

class CorrelationMiddleware:
    """ASGI middleware that generates/propagates correlation IDs."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        corr_id = headers.get(b"x-correlation-id", b"").decode() or generate_correlation_id()
        correlation_id_var.set(corr_id)

        async def send_with_correlation(message):
            if message["type"] == "http.response.start":
                h = list(message.get("headers", []))
                h.append((b"x-correlation-id", corr_id.encode()))
                message["headers"] = h
            await send(message)

        await self.app(scope, receive, send_with_correlation)
