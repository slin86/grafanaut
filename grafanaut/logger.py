import logging

def setup_logger(name: str = "grafanaut", level=logging.INFO) -> logging.Logger:
    formatter = logging.Formatter("[%(levelname)s] %(message)s")

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.addHandler(handler)
    logger.propagate = False

    return logger
