# HookReel Metadata Provider System
#
# Supported providers:
#   omdb    — OMDb API (omdbapi.com)
#             Free tier: 1000 req/day
#             API key: required (free registration)
#             Terms: no restrictions for personal use
#
#   tmdb    — The Movie Database (themoviedb.org)
#             Free tier: generous rate limits
#             API key: required (free registration)
#             Terms: users must comply with TMDB ToS
#
#   tvmaze  — TVmaze (tvmaze.com)
#             Free tier: unlimited
#             API key: not required
#             Terms: no restrictions
#             Note: best for TV shows, limited movie data
#
# To add a new provider:
#   1. Create app/metadata/yourprovider.py
#   2. Subclass MetadataProvider and implement all abstract methods
#   3. Add an entry to _PROVIDER_REGISTRY in this file
#   4. Add the value to _VALID_PROVIDERS in app/config.py
#   5. Document in README

"""
app/metadata/__init__.py — Metadata provider factory for HookReel.

This is the only import any other module needs:

    from app.metadata import get_provider

    metadata = get_provider()
    results  = metadata.search_movie("Interstellar")

The provider is chosen by METADATA_PROVIDER in config/.env.
The API key is taken from METADATA_API_KEY.

Supported values for METADATA_PROVIDER:
    omdb    — OMDb / IMDb  (movies + TV, free key required)
    tmdb    — TMDB         (movies + TV, free key required)
    tvmaze  — TVmaze       (TV only, no key required)

The factory is intentionally lightweight — it imports only the
provider module that is actually needed, so unused providers add
zero overhead.
"""

from typing import TYPE_CHECKING

import app.config as config
from app.logger import logger
from app.metadata.base import MetadataProvider

if TYPE_CHECKING:
    pass

# Map the METADATA_PROVIDER string to a (module_path, class_name) tuple.
# Adding a new provider only requires adding one line here plus a new file.
_PROVIDER_REGISTRY: dict[str, tuple[str, str]] = {
    "omdb":   ("app.metadata.omdb",   "OmdbProvider"),
    "tmdb":   ("app.metadata.tmdb",   "TmdbProvider"),
    "tvmaze": ("app.metadata.tvmaze", "TvmazeProvider"),
}

# Module-level cache — instantiated once, reused on every call.
_provider_instance: MetadataProvider | None = None


def get_provider() -> MetadataProvider:
    """
    Return the configured metadata provider as a ready-to-use instance.

    The provider is instantiated once and cached for the lifetime of the
    process.  Subsequent calls return the same instance.

    The provider name is read from METADATA_PROVIDER and the API key
    from METADATA_API_KEY in config/.env.

    Returns:
        An instance of the appropriate MetadataProvider subclass.

    Raises:
        ValueError: If METADATA_PROVIDER is set to an unrecognised value.
        ImportError: If the provider module cannot be loaded (should not
                     happen with the bundled providers).
    """
    global _provider_instance

    if _provider_instance is not None:
        return _provider_instance

    provider_name = config.METADATA_PROVIDER.lower().strip()

    if provider_name not in _PROVIDER_REGISTRY:
        supported = ", ".join(sorted(_PROVIDER_REGISTRY.keys()))
        raise ValueError(
            f"[HookReel] Unknown metadata provider '{provider_name}'. "
            f"Set METADATA_PROVIDER in config/.env to one of: {supported}"
        )

    module_path, class_name = _PROVIDER_REGISTRY[provider_name]

    # Dynamic import — only load the module we actually need.
    import importlib
    try:
        module = importlib.import_module(module_path)
        provider_class = getattr(module, class_name)
    except (ImportError, AttributeError) as exc:
        raise ImportError(
            f"[HookReel] Could not load metadata provider '{provider_name}' "
            f"from '{module_path}': {exc}"
        ) from exc

    _provider_instance = provider_class(api_key=config.METADATA_API_KEY)

    logger.info(
        "Metadata provider initialised: %s (key=****%s)",
        provider_name.upper(),
        config.METADATA_API_KEY[-4:] if len(config.METADATA_API_KEY) >= 4 else "****",
    )
    return _provider_instance


def reset_provider() -> None:
    """
    Clear the cached provider instance.

    This is used exclusively by the test suite to swap providers between
    tests without restarting the process.  Do not call this in production.
    """
    global _provider_instance
    _provider_instance = None
