"""
prowlarr_mgmt.py — Prowlarr management functions for HookReel web UI.

Provides full indexer management: list, add, edit, delete, test indexers,
view stats, and manage Prowlarr host configuration.

All functions talk directly to the Prowlarr REST API using credentials
from app.config. These are used by the /indexers web UI page.
"""

import requests
import app.config as config
from app.logger import get_logger

logger = get_logger(__name__)

# Base URL and headers built once from config
_BASE_URL = "http://{}:{}".format(config.PROWLARR_HOST, config.PROWLARR_PORT)
_HEADERS = {
    "X-Api-Key": config.PROWLARR_API_KEY,
    "Content-Type": "application/json",
}
_TIMEOUT = 15


def get_indexers() -> list:
    """
    Fetch all configured indexers from Prowlarr.

    Returns:
        A list of indexer dicts as returned by the Prowlarr API.
        Returns an empty list on error.
    """
    try:
        response = requests.get(
            "{}/api/v1/indexer".format(_BASE_URL),
            headers=_HEADERS,
            timeout=_TIMEOUT,
        )
        response.raise_for_status()
        logger.info("[HookReel] prowlarr_mgmt: fetched %d indexer(s)", len(response.json()))
        return response.json()
    except Exception as exc:
        logger.error("[HookReel] prowlarr_mgmt get_indexers error: %s", exc)
        return []


def toggle_indexer(indexer_id: int, enabled: bool) -> bool:
    """
    Enable or disable a single indexer by its Prowlarr ID.

    Fetches the current indexer config, updates the enabled field,
    and sends it back via PUT.

    Parameters:
        indexer_id: The Prowlarr numeric ID of the indexer.
        enabled:    True to enable, False to disable.

    Returns:
        True if the update succeeded, False on error.
    """
    try:
        response = requests.get(
            "{}/api/v1/indexer/{}".format(_BASE_URL, indexer_id),
            headers=_HEADERS,
            timeout=_TIMEOUT,
        )
        response.raise_for_status()
        indexer = response.json()
        indexer["enable"] = enabled

        put_response = requests.put(
            "{}/api/v1/indexer/{}".format(_BASE_URL, indexer_id),
            headers=_HEADERS,
            json=indexer,
            timeout=_TIMEOUT,
        )
        put_response.raise_for_status()
        logger.info(
            "[HookReel] prowlarr_mgmt: indexer id=%d enabled=%s", indexer_id, enabled
        )
        return True
    except Exception as exc:
        logger.error("[HookReel] prowlarr_mgmt toggle_indexer error: %s", exc)
        return False


def test_all_indexers() -> dict:
    """
    Trigger a test of all configured indexers in Prowlarr.

    Returns:
        The API response dict, or an error dict on failure.
    """
    try:
        response = requests.post(
            "{}/api/v1/indexer/testall".format(_BASE_URL),
            headers=_HEADERS,
            timeout=60,
        )
        response.raise_for_status()
        logger.info("[HookReel] prowlarr_mgmt: test all indexers triggered")
        return response.json() if response.text else {"success": True}
    except Exception as exc:
        logger.error("[HookReel] prowlarr_mgmt test_all_indexers error: %s", exc)
        return {"success": False, "error": str(exc)}


def test_indexer(indexer_id: int) -> dict:
    """
    Test a single indexer by its Prowlarr ID.

    Parameters:
        indexer_id: The Prowlarr numeric ID of the indexer.

    Returns:
        A dict with success status and any error message.
    """
    try:
        response = requests.post(
            "{}/api/v1/indexer/{}/test".format(_BASE_URL, indexer_id),
            headers=_HEADERS,
            timeout=30,
        )
        response.raise_for_status()
        logger.info("[HookReel] prowlarr_mgmt: tested indexer id=%d", indexer_id)
        return {"success": True}
    except Exception as exc:
        logger.error("[HookReel] prowlarr_mgmt test_indexer error: %s", exc)
        return {"success": False, "error": str(exc)}


def add_indexer(indexer_config: dict) -> bool:
    """
    Add a new indexer to Prowlarr.

    Parameters:
        indexer_config: Full indexer configuration dict matching
                        the Prowlarr API schema.

    Returns:
        True if created successfully, False on error.
    """
    try:
        response = requests.post(
            "{}/api/v1/indexer".format(_BASE_URL),
            headers=_HEADERS,
            json=indexer_config,
            timeout=_TIMEOUT,
        )
        response.raise_for_status()
        logger.info("[HookReel] prowlarr_mgmt: added new indexer")
        return True
    except Exception as exc:
        logger.error("[HookReel] prowlarr_mgmt add_indexer error: %s", exc)
        return False


def update_indexer(indexer_id: int, indexer_config: dict) -> bool:
    """
    Update an existing indexer in Prowlarr.

    Parameters:
        indexer_id:     The Prowlarr numeric ID of the indexer.
        indexer_config: Full updated indexer configuration dict.

    Returns:
        True if updated successfully, False on error.
    """
    try:
        response = requests.put(
            "{}/api/v1/indexer/{}".format(_BASE_URL, indexer_id),
            headers=_HEADERS,
            json=indexer_config,
            timeout=_TIMEOUT,
        )
        response.raise_for_status()
        logger.info("[HookReel] prowlarr_mgmt: updated indexer id=%d", indexer_id)
        return True
    except Exception as exc:
        logger.error("[HookReel] prowlarr_mgmt update_indexer error: %s", exc)
        return False


def delete_indexer(indexer_id: int) -> bool:
    """
    Delete an indexer from Prowlarr by its ID.

    Parameters:
        indexer_id: The Prowlarr numeric ID of the indexer.

    Returns:
        True if deleted successfully, False on error.
    """
    try:
        response = requests.delete(
            "{}/api/v1/indexer/{}".format(_BASE_URL, indexer_id),
            headers=_HEADERS,
            timeout=_TIMEOUT,
        )
        response.raise_for_status()
        logger.info("[HookReel] prowlarr_mgmt: deleted indexer id=%d", indexer_id)
        return True
    except Exception as exc:
        logger.error("[HookReel] prowlarr_mgmt delete_indexer error: %s", exc)
        return False


def get_indexer_stats() -> dict:
    """
    Fetch per-indexer statistics from Prowlarr.

    Returns:
        A dict containing indexer stats (response times, search counts,
        success rates). Returns an empty dict on error.
    """
    try:
        response = requests.get(
            "{}/api/v1/indexerstats".format(_BASE_URL),
            headers=_HEADERS,
            timeout=_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        logger.error("[HookReel] prowlarr_mgmt get_indexer_stats error: %s", exc)
        return {}


def get_prowlarr_config() -> dict:
    """
    Fetch Prowlarr host configuration (authentication, URL base, etc.).

    Returns:
        A dict with host config fields, or empty dict on error.
    """
    try:
        response = requests.get(
            "{}/api/v1/config/host".format(_BASE_URL),
            headers=_HEADERS,
            timeout=_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        logger.error("[HookReel] prowlarr_mgmt get_prowlarr_config error: %s", exc)
        return {}


def update_prowlarr_config(updated_config: dict) -> bool:
    """
    Update Prowlarr host configuration.

    Parameters:
        updated_config: Dict of config fields to update.

    Returns:
        True if updated successfully, False on error.
    """
    try:
        response = requests.put(
            "{}/api/v1/config/host".format(_BASE_URL),
            headers=_HEADERS,
            json=updated_config,
            timeout=_TIMEOUT,
        )
        response.raise_for_status()
        logger.info("[HookReel] prowlarr_mgmt: Prowlarr host config updated")
        return True
    except Exception as exc:
        logger.error("[HookReel] prowlarr_mgmt update_prowlarr_config error: %s", exc)
        return False
