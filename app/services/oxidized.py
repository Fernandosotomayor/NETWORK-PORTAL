import logging
import httpx
from typing import Any
from app.core.config import settings

LOGGER = logging.getLogger(__name__)

async def get_oxidized_nodes() -> list[dict[str, Any]]:
    """
    Fetch the list of nodes from the Oxidized REST API.
    Returns:
        List of dicts representing the nodes, or an empty list if there's an error.
    """
    url = f"{settings.OXIDIZED_URL.rstrip('/')}/nodes.json"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            LOGGER.debug(f"Requesting Oxidized status from {url}")
            response = await client.get(url)
            if response.status_code == 200:
                return response.json()
            else:
                LOGGER.error(f"Oxidized API returned status code {response.status_code}")
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.HTTPError) as e:
        LOGGER.warning(f"Could not connect to Oxidized API at {url}: {str(e)}")
    except Exception as e:
        LOGGER.exception(f"Unexpected error when calling Oxidized API at {url}: {str(e)}")
    return []
