import sys
from logging.config import dictConfig

# Uvicorn-compatible logging configuration
LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "()": "uvicorn.logging.DefaultFormatter",
            "fmt": "%(levelprefix)s %(asctime)s [%(name)s] %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
        "access": {
            "()": "uvicorn.logging.AccessFormatter",
            "fmt": '%(levelprefix)s %(asctime)s [%(name)s] "%(request_line)s" %(status_code)s',
        },
    },
    "handlers": {
        "default": {
            "class": "logging.StreamHandler",
            "formatter": "default",
            "stream": sys.stderr,
            "level": "INFO",
        },
        "access": {
            "class": "logging.StreamHandler",
            "formatter": "access",
            "stream": sys.stdout,
            "level": "INFO",
        },
        # This handler ensures app-specific logs are very visible
        "app": {
            "class": "logging.StreamHandler",
            "formatter": "default",
            "stream": sys.stdout,
            "level": "DEBUG",
        },
    },
    "loggers": {
        "root": {"handlers": ["default"], "level": "INFO", "propagate": False},
        "uvicorn.error": {"handlers": ["default"], "level": "INFO", "propagate": False},
        "uvicorn.access": {"handlers": ["access"], "level": "INFO", "propagate": False},
        # Ensure app-specific loggers are configured
        "app": {"handlers": ["app"], "level": "DEBUG", "propagate": False},
        "app.api": {"handlers": ["app"], "level": "DEBUG", "propagate": False},
        "app.generation_logic": {"handlers": ["app"], "level": "DEBUG", "propagate": False},
        "app.services": {"handlers": ["app"], "level": "DEBUG", "propagate": False},
    },
}


def setup_logging() -> None:
    """Configures application-wide logging using dictConfig."""
    dictConfig(LOGGING_CONFIG)
