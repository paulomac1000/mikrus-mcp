"""Configuration loader."""

import logging
import os

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


def load_config() -> dict[str, str]:
    """Load and validate configuration from environment variables."""
    api_key = os.getenv("MIKRUS_API_KEY")
    server_name = os.getenv("MIKRUS_SERVER_NAME")
    base_url = os.getenv("MIKRUS_API_URL", "https://api.mikr.us")

    if not api_key:
        raise RuntimeError("Missing required environment variable: MIKRUS_API_KEY")

    if not server_name:
        raise RuntimeError("Missing required environment variable: MIKRUS_SERVER_NAME")

    logger.debug("Configuration loaded successfully for server: %s", server_name)

    return {
        "base_url": base_url,
        "api_key": api_key,
        "server_name": server_name,
    }
