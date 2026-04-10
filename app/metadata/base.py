"""
base.py — Abstract base class for all HookReel metadata providers.

Every metadata provider (TMDB, OMDb, TVmaze, etc.) MUST subclass
MetadataProvider and implement all abstract methods.  This guarantees
that the rest of HookReel only ever sees one consistent dict shape,
regardless of which provider the user has configured.

Field contracts
───────────────
search_movie / search_show results — each item MUST contain:
    provider_id  (str)            — Unique ID in this provider's system
    title        (str)            — Movie or show title
    year         (str | None)     — Four-digit year string, or None
    overview     (str)            — Short plot description (may be empty)
    poster_url   (str | None)     — Absolute URL to poster image, or None
    rating       (float)          — Audience rating 0.0–10.0 (0.0 if unknown)

get_movie_details result — all of the above PLUS:
    genres       (list[str])      — Genre name strings (may be empty list)
    runtime      (int | None)     — Runtime in minutes, or None

Any provider-specific field names MUST be normalised inside the
provider module before being returned.  No caller outside app/metadata/
should ever reference a provider-specific key.
"""

from abc import ABC, abstractmethod


class MetadataProvider(ABC):
    """
    Abstract base class that defines the interface every metadata
    provider must satisfy.

    Subclass this and implement all three abstract methods.  The
    constructor receives the API key as its only argument so that
    the factory in __init__.py can instantiate any provider uniformly.

    Parameters:
        api_key: The user's API key for this provider, taken from
                 METADATA_API_KEY in config/.env.
    """

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    # ── Abstract methods every provider must implement ────────────────────

    @abstractmethod
    def search_movie(self, query: str) -> list:
        """
        Search for movies matching the given query string.

        Parameters:
            query: Plain-text movie title, e.g. 'The Dark Knight'.

        Returns:
            A list of normalised movie dicts (see field contract above).
            Returns an empty list if nothing is found or on error.
            Never raises — swallow exceptions and return [].
        """

    @abstractmethod
    def get_movie_details(self, provider_id: str) -> dict:
        """
        Fetch full details for a single movie by its provider-specific ID.

        Parameters:
            provider_id: The identifier string returned in provider_id
                         by search_movie, e.g. 'tt0468569' for OMDb.

        Returns:
            A normalised movie dict including genres and runtime
            (see field contract above), or None if not found or on error.
        """

    @abstractmethod
    def search_show(self, query: str) -> list:
        """
        Search for TV shows matching the given query string.

        Parameters:
            query: Plain-text show title, e.g. 'Breaking Bad'.

        Returns:
            A list of normalised show dicts (same shape as search_movie).
            Returns an empty list if nothing is found or on error.
            Never raises — swallow exceptions and return [].
        """

    # ── Shared helpers available to all subclasses ────────────────────────

    @staticmethod
    def _safe_year(raw: str) -> str | None:
        """
        Extract a four-digit year from any date-like string.

        Parameters:
            raw: Any string that may start with a year, e.g. '2008',
                 '2008-07-18', '2008–2012', or empty / None.

        Returns:
            A four-character year string, or None if extraction fails.
        """
        if not raw:
            return None
        raw = str(raw).strip()
        if len(raw) >= 4 and raw[:4].isdigit():
            return raw[:4]
        return None

    @staticmethod
    def _safe_float(raw) -> float:
        """
        Coerce a value to a float, returning 0.0 on failure.

        Parameters:
            raw: Anything — string, int, float, None, 'N/A'.

        Returns:
            A float value, or 0.0 if conversion fails.
        """
        try:
            return float(raw)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _safe_int(raw) -> int | None:
        """
        Coerce a value to an int, returning None on failure.

        Parameters:
            raw: Anything — string, int, None, 'N/A', '142 min'.

        Returns:
            An integer, or None if conversion fails.
        """
        if raw is None:
            return None
        # Strip common suffixes like ' min' before parsing.
        cleaned = str(raw).split()[0].replace(",", "")
        try:
            return int(cleaned)
        except (TypeError, ValueError):
            return None
