from logging.config import dictConfig


def setup_logging():
    config = {
        "version": 1,
        "formatters": {
            "default": {"format": "%(asctime)s %(levelname)s [%(name)s] %(message)s"}
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "default",
            }
        },
        "root": {
            "handlers": ["console"],
            "level": "INFO",
        },
    }
    dictConfig(config)
