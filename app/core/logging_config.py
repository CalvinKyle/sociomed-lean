import logging
import logging.config
import os
import sys

class CorrelationIdFilter(logging.Filter):
    def filter(self, record):
        if not hasattr(record, "correlation_id"):
            record.correlation_id = "-"
        return True


LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "correlation_id": {
            "()": CorrelationIdFilter,
        },
    },
    "formatters": {
        "standard": {
            "format": "%(asctime)s %(levelname)s %(name)s [corr=%(correlation_id)s] %(message)s",
        },
    },
    "handlers": {
        "audit_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": "logs/audit_trail.log",
            "maxBytes": 10485760,
            "backupCount": 5,
            "formatter": "standard",
            "filters": ["correlation_id"],
        },
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
            "filters": ["correlation_id"],
            "level": "INFO",
            "stream": "ext://sys.stdout",
        },
    },
    "loggers": {
        "": {
            "handlers": ["audit_file", "console"],
            "level": "INFO",
        },
    },
}

def setup_logging(correlation_id: str = "startup"):
    os.makedirs("logs", exist_ok=True)
    logging.config.dictConfig(LOGGING_CONFIG)
    logger = logging.getLogger(__name__)
    logger.info("Logging setup done", extra={"correlation_id": correlation_id})
