"""
Structured JSON Logger with module namespacing and request_id correlation.

Provides:
- setup_structured_logging(): Initialize logging configuration
- get_logger(name): Get a logger with module field set
"""

import logging
import sys
import json
from typing import Any
from datetime import datetime


class StructuredFormatter(logging.Formatter):
    """
    JSON formatter for structured logging.
    
    Output format:
    {
        "ts": "2024-01-15T10:30:00Z",
        "level": "INFO",
        "module": "core",
        "message": "Module started",
        "request_id": "abc123def456",
        "extra_field": "value"
    }
    """
    
    def __init__(self, include_locals: bool = False):
        super().__init__()
        self.include_locals = include_locals
    
    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "ts": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "module": getattr(record, "module", "unknown"),
            "message": record.getMessage(),
        }
        
        # Add request_id if present
        request_id = getattr(record, "request_id", None)
        if request_id:
            log_entry["request_id"] = request_id
        
        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        
        # Add extra fields (those not in standard LogRecord)
        standard_attrs = {
            'name', 'msg', 'args', 'created', 'filename', 'funcName',
            'levelname', 'levelno', 'lineno', 'module', 'msecs',
            'pathname', 'process', 'processName', 'relativeCreated',
            'stack_info', 'exc_info', 'exc_text', 'thread', 'threadName',
            'message', 'asctime', 'module', 'request_id'
        }
        
        for key, value in record.__dict__.items():
            if key not in standard_attrs:
                log_entry[key] = value
        
        return json.dumps(log_entry, default=str)


class ModuleLoggerAdapter(logging.LoggerAdapter):
    """
    Logger adapter that injects module name and optional request_id.
    """
    
    def process(self, msg: str, kwargs: dict) -> tuple[str, dict]:
        extra = kwargs.get('extra', {})
        extra.update(self.extra)
        kwargs['extra'] = extra
        return msg, kwargs


def setup_structured_logging(
    level: int = logging.INFO,
    include_locals: bool = False,
) -> None:
    """
    Configure root logger with structured JSON formatter.
    
    Args:
        level: Logging level (default INFO)
        include_locals: Include local variables in error logs (default False)
    
    Usage:
        Call once at application startup before any logging.
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    
    # Remove existing handlers
    root_logger.handlers.clear()
    
    # Create console handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(StructuredFormatter(include_locals=include_locals))
    
    root_logger.addHandler(handler)
    
    # Reduce noise from third-party libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def get_logger(name: str) -> ModuleLoggerAdapter:
    """
    Get a logger with module namespacing.
    
    Args:
        name: Module name (e.g., 'core', 'db', 'auth')
    
    Returns:
        ModuleLoggerAdapter with module field set
    
    Usage:
        logger = core.get_logger('my_module')
        logger.info("Starting up", extra={"custom_field": "value"})
    """
    logger = logging.getLogger(f"cmms.{name}")
    
    # Set module-specific level if needed
    if not logger.handlers:
        logger.propagate = True
    
    adapter = ModuleLoggerAdapter(logger, {"module": name})
    return adapter


class RequestLoggerFilter(logging.Filter):
    """
    Filter that injects request_id into log records.
    
    Attach to handlers that should include request correlation.
    """
    
    def __init__(self, request_id: str):
        super().__init__()
        self.request_id = request_id
    
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = self.request_id
        return True


def with_request_context(
    logger: ModuleLoggerAdapter,
    request_id: str,
) -> ModuleLoggerAdapter:
    """
    Create a logger adapter with request_id context.
    
    Args:
        logger: Base logger from get_logger()
        request_id: Request correlation ID
    
    Returns:
        New adapter that includes request_id in all logs
    
    Usage:
        base_logger = core.get_logger('api')
        req_logger = core.with_request_context(base_logger, request_id)
        req_logger.info("Request received")  # Includes request_id
    """
    adapter = ModuleLoggerAdapter(
        logger.logger,
        {"module": logger.extra.get("module", "unknown"), "request_id": request_id}
    )
    return adapter
