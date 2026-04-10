"""
tvmaze.py — TVmaze metadata provider for HookReel.

TVmaze API reference: https://www.tvmaze.com/api
Authentication:     None required for the free public API.
                    METADATA_API_KEY is accepted but ignored.
Search endpoint:    GET https://api.tvmaze.com/search/shows?q=QUERY
Detail endpoint:    GET https://api.tvmaze.com/shows/ID

TVmaze is primarily a TV show database.  search_movie and
get_movie_details are implemented but will always return empty / None
because TVmaze has no movie data.  This is intentional — it makes the
provider safe to drop in without breaking the movie pipeline (it just
won't find anything for movie queries).

Set in .env:  METADATA_PROVIDER=tvmaze
              METADATA_API_KEY=unused   (any non-empty value is fine)
"""

from typing import Optional

import requests
from bs4 import BeautifulSoup

from app.metadata.base import MetadataProvider

_BASE_URL = "https://api.tvmaze.com"
_REQUEST_TIMEOUT = 15


class TvmazeProvider(MetadataProvider):
    """
    MetadataProvider implementation backed by the TVmaze public API.

    TVmaze does not require an API key.  The api_key attribute is
    stored but never sent to the API.

    This provider is optimised for TV show lookups.  Movie methods
    return empty results because TVmaze has no movie catalogue.
    """

    # ── Internal helpers ──────────────────────────────────────────────────

    def _get(self, path: str, params: Optional[dict] = None) -> Optional[object]:
        """
        Make a GET request to the TVmaze API and return parsed JSON.

        Parameters:
            path:   API path, e.g. '/search/shows'.
            params: Optional query string parameters.

        Returns:
            Parsed JSON (list or dict), or None on failure.
        """
        url = f"{_BASE_URL}{path}"
        try:
            response = requests.get(url, params=params, timeout=_REQUEST_TIMEOUT)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.Timeout:
            from app.logger import logger
            logger.error("TVmaze request timed out for path '%s'.", path)
            return None
        except requests.exceptions.ConnectionError as exc:
            from app.logger import logger
            logger.error("TVmaze connection error: %s", exc)
            return None
        except Exception as exc:
            from app.logger import logger
            logger.error("TVmaze unexpected error: %s", exc)
            return None

    def _normalise_show(self, show: dict) -> dict:
        """
        Convert a TVmaze show object into the standard metadata shape.

        TVmaze nests show data one level deep inside a 'show' key when
        returned from the search endpoint, but returns it flat from the
        detail endpoint.  This method handles either format.

        Parameters:
            show: A TVmaze show dict (flat, not wrapped in 'show' key).

        Returns:
            A normalised metadata dict.
        """
        # Image: TVmaze provides 'original' and 'medium' sizes.
        image = show.get("image") or {}
        poster_url = image.get("original") or image.get("medium") or None

        # Genres come as a list of strings already — no parsing needed.
        genres = show.get("genres") or []

        # Rating is nested: {"average": 8.5} or {"average": null}
        rating_obj = show.get("rating") or {}
        rating = self._safe_float(rating_obj.get("average") or 0)

        # Premiered is a date string like '2013-09-29'.
        premiered = show.get("premiered") or show.get("first_air_date") or ""

        # Runtime: TVmaze calls it 'runtime' (int minutes) or
        # 'averageRuntime' for shows with variable episode lengths.
        runtime = self._safe_int(
            show.get("runtime") or show.get("averageRuntime")
        )

        # Summary is HTML — strip tags for a plain-text overview.
        raw_summary = show.get("summary") or ""
        overview = _strip_html(raw_summary)

        return {
            "provider_id": str(show.get("id", "")),
            "title": show.get("name", "Unknown"),
            "year": self._safe_year(premiered),
            "overview": overview,
            "poster_url": poster_url,
            "rating": rating,
            "genres": genres,
            "runtime": runtime,
        }

    # ── Public API (MetadataProvider interface) ───────────────────────────

    def search_movie(self, query: str) -> list:
        """
        TVmaze does not have a movie catalogue.

        This method always returns an empty list so the movie pipeline
        degrades gracefully when TVmaze is selected as the provider
        (rather than crashing).

        Parameters:
            query: Ignored.

        Returns:
            Always an empty list.
        """
        from app.logger import logger
        logger.warning(
            "TVmaze does not support movie searches. "
            "Set METADATA_PROVIDER=omdb or tmdb for movie support."
        )
        return []

    def get_movie_details(self, provider_id: str) -> None:
        """
        TVmaze does not have a movie catalogue.

        Parameters:
            provider_id: Ignored.

        Returns:
            Always None.
        """
        from app.logger import logger
        logger.warning(
            "TVmaze does not support movie detail lookups. "
            "Set METADATA_PROVIDER=omdb or tmdb for movie support."
        )
        return None

    def search_show(self, query: str) -> list:
        """
        Search TVmaze for TV shows matching the given query string.

        Parameters:
            query: Plain-text show title, e.g. 'Breaking Bad'.

        Returns:
            A list of normalised show dicts.
            Each item has: provider_id, title, year, overview,
            poster_url, rating.
            Returns an empty list if nothing is found or on error.
        """
        from app.logger import logger
        logger.info("TVmaze: searching shows for '%s'.", query)

        data = self._get("/search/shows", params={"q": query})

        if not data:
            return []

        # TVmaze search wraps each result: {"score": 1.0, "show": {...}}
        results = []
        for item in data:
            show_data = item.get("show")
            if show_data:
                results.append(self._normalise_show(show_data))

        logger.info(
            "TVmaze search for '%s' returned %d result(s).", query, len(results)
        )
        return results

    def get_show_details(self, provider_id: str) -> Optional[dict]:
        """
        Fetch full details for a TV show by its TVmaze numeric ID.

        This is a TVmaze-specific bonus method (not in the base class
        interface) because TV show detail lookups will be used by the
        TV pipeline in Phase 6.

        Parameters:
            provider_id: TVmaze show ID as a string, e.g. '169'.

        Returns:
            A normalised show dict including genres and runtime,
            or None if not found or on error.
        """
        from app.logger import logger
        logger.info("TVmaze: fetching show details for id='%s'.", provider_id)

        data = self._get(f"/shows/{provider_id}")

        if not data:
            return None

        result = self._normalise_show(data)
        logger.info(
            "TVmaze details fetched: '%s' (%s).", result["title"], result["year"]
        )
        return result


# ── Module-level helper ───────────────────────────────────────────────────────

def _strip_html(text: str) -> str:
    """
    Remove HTML tags from a string using BeautifulSoup.

    TVmaze returns summaries wrapped in <p> and <b> tags.
    BeautifulSoup handles edge cases (unclosed tags, nested elements,
    HTML entities) far more reliably than a manual character scanner.

    Parameters:
        text: A string that may contain HTML tags.

    Returns:
        The string with all HTML tags removed and leading/trailing
        whitespace stripped.
    """
    if not text:
        return ""
    return BeautifulSoup(text, "html.parser").get_text().strip()
