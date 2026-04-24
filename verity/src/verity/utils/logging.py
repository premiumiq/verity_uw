"""Verity Logging — structured logging with correlation IDs.

Provides:
- setup_logging(): configure handlers, formatters, and log level
- ContextVars for correlation_id, workflow_run_id, step_name, etc.
- ContextFilter that attaches context vars to every log record
- CorrelationMiddleware for FastAPI (generates/propagates correlation IDs)

Usage (application startup):
    from verity.utils.logging import setup_logging
    setup_logging(service_name="verity", log_level="INFO")

Usage (getting a logger — standard Python, module-level):
    import logging
    logger = logging.getLogger(__name__)
    logger.info("Pipeline started", extra={"submission_id": "SUB-001"})

SDK safety:
    Verity never calls logging.basicConfig() or attaches handlers to the
    root logger. When used as a library (pip install verity), the consuming
    app controls all logging configuration. Verity only adds a NullHandler
    to its package root logger (in __init__.py) to suppress "no handler"
    warnings.
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
    """Logging filter that adds context variables to log records.

    Attached to handlers so all formatters can access:
    - record.correlation_id
    - record.workflow_run_id
    - record.step_name
    - record.submission_id
    - record.service
    """

    def filter(self, record):
        record.correlation_id = correlation_id_var.get("")
        record.workflow_run_id = workflow_run_id_var.get("")
        record.step_name = step_name_var.get("")
        record.submission_id = submission_id_var.get("")
        record.service = service_name_var.get("unknown")
        return True


# ══════════════════════════════════════════════════════════════
# CONSOLE FORMATTER — human-readable for development
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
    """Configure logging for a Verity service.

    Call once at application startup, before creating the FastAPI app.
    Reads from environment variables if arguments are not provided.

    Args:
        service_name: "verity", "uw_demo", or "edms"
        log_level: DEBUG, INFO, WARNING, ERROR, CRITICAL
        log_format: "json" or "console"
        log_file_enabled: whether to write rotating log files
        log_dir: directory for log files (relative to working dir)
    """
    # Read from env vars with sensible defaults
    level = (log_level or os.getenv("LOG_LEVEL", "INFO")).upper()
    fmt = log_format or os.getenv("LOG_FORMAT", "json")
    file_enabled = log_file_enabled if log_file_enabled is not None else (
        os.getenv("LOG_FILE_ENABLED", "false").lower() == "true"
    )
    directory = log_dir or os.getenv("LOG_DIR", "./logs")

    # Set service name in context var
    service_name_var.set(service_name)

    # Build config dict
    config = _build_config(
        service_name=service_name,
        level=level,
        fmt=fmt,
        file_enabled=file_enabled,
        log_dir=directory,
    )

    logging.config.dictConfig(config)

    logger = logging.getLogger(service_name.replace("_", ".") if "." not in service_name else service_name)
    logger.info(
        "Logging configured: service=%s level=%s format=%s file=%s",
        service_name, level, fmt, file_enabled,
    )


def _build_config(
    service_name: str,
    level: str,
    fmt: str,
    file_enabled: bool,
    log_dir: str,
) -> dict:
    """Build a logging.config.dictConfig dictionary."""

    # Determine formatter
    if fmt == "json":
        try:
            # Check if python-json-logger is available
            import pythonjsonlogger  # noqa: F401
            formatter_class = "pythonjsonlogger.json.JsonFormatter"
            formatter_config = {
                "()": formatter_class,
                "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
                "rename_fields": {
                    "asctime": "timestamp",
                    "levelname": "level",
                    "name": "logger",
                },
                "static_fields": {
                    "service": service_name,
                },
            }
        except ImportError:
            # Fallback to console format if json logger not installed
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
        "filters": {
            "context": {
                "()": ContextFilter,
            },
        },
        "formatters": {
            "default": formatter_config,
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "formatter": "default",
                "filters": ["context"],
            },
        },
        "root": {
            "level": level,
            "handlers": ["console"],
        },
    }

    # Add rotating file handler if enabled
    if file_enabled:
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        config["handlers"]["file"] = {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(log_path / f"{service_name}.log"),
            "maxBytes": 50_000_000,   # 50 MB
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
    """ASGI middleware that generates/propagates correlation IDs.

    - Checks X-Correlation-ID header on incoming requests
    - Generates a new ID if not present
    - Sets correlation_id_var for all downstream logging
    - Adds X-Correlation-ID to response headers

    Usage:
        app.add_middleware(CorrelationMiddleware)
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        # Extract or generate correlation ID
        headers = dict(scope.get("headers", []))
        corr_id = headers.get(b"x-correlation-id", b"").decode() or generate_correlation_id()
        correlation_id_var.set(corr_id)

        # Wrap send to add correlation ID to response headers
        async def send_with_correlation(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-correlation-id", corr_id.encode()))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_correlation)
