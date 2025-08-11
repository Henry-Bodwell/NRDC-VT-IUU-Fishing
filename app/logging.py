import logging
import sys
from datetime import datetime


def setup_logging():
    import os

    os.makedirs("logs", exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            # File handler
            logging.FileHandler(
                f"logs/fishlog_{datetime.now().strftime('%Y%m%d')}.log"
            ),
            # Console handler (so you can see logs in terminal too)
            logging.StreamHandler(sys.stdout),
        ],
    )


setup_logging()
