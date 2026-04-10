"""
omdb.py — OMDb (Open Movie Database) metadata provider for HookReel.

OMDb API reference: https://www.omdbapi.com/
Authentication:     apikey= query parameter
Search endpoint:    ?s=QUERY&type=movie   (returns up to 10 results)
Detail endpoint:    ?i=IMDB_ID&plot=full  (returns full record)

OMDb uses IMDb IDs (e.g. 'tt0468569') as its primary identifier, so
provider_id in all returned dicts is the IMDb ID string.

Get a free OMDb API key at: https://www.omdbapi.com/apikey.aspx
Set in .env:  METADATA_PROVIDER=omdb
              METADATA_API_KEY=your_key_here
"""

from typing import Optional

import requests

from app.metadata.base import MetadataProvider

_BASE_URL = "http://www.omdbapi.com/"
_REQUEST_TIMEOUT = 15


class OmdbProvider(MetadataProvider):
    """
    MetadataProvider implementation backed by the OMDb API.

    Normalises all OMDb-specific field names into the standard
    HookReel metadata dict shape before returning results.
    """

    # ── Internal helpers ──────────────────────────────────────────────────

    def _get(self, params: dict) -> Optional[dict]:
        """
        Make a GET request to the OMDb API and return the parsed JSON.

        Always injects the API key into params.  Returns None on any
        network or HTTP error.

        Parameters:
            params: Query string parameters (without apikey).

        Returns:
            Parsed JSON dict, or None on failure.
        """
        params["apikey"] = self.api_key
        try:
            response = requests.get(
                _BASE_URL, params=params, timeout=_REQUEST_TIMEOUT
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.Timeout:
            from app.logger import logger
            logger.error("OMDb request timed out.")
            return None
        except requests.exceptions.ConnectionError as exc:
            from app.logger import logger
            logger.error("OMDb connection error: %s", exc)
            return None
        except Exception as exc:
            from app.logger import logger
            logger.error("OMDb unexpected error: %s", exc)
            return None

    def _normalise_search_item(self, item: dict) -> dict:
        """
        Convert a single OMDb search result item into the standard shape.

        OMDb search results are sparse — overview, rating, and poster
        may be missing.  We fill sensible defaults.

        Parameters:
            item: A single dict from the OMDb 'Search' array.

        Returns:
            A normalised metadata dict.
        """
        return {
            "provider_id": item.get("imdbID", ""),
            "title": item.get("Title", "Unknown"),
            "year": self._safe_year(item.get("Year", "")),
            "overview": "",          # not included in search results
            "poster_url": item.get("Poster") if item.get("Poster") != "N/A" else None,
            "rating": 0.0,           # not included in search results
        }

    def _normalise_detail(self, data: dict) -> dict:
        """
        Convert a full OMDb detail record into the standard shape.

        Parameters:
            data: The full JSON dict returned by the OMDb ?i= endpoint.

        Returns:
            A normalised metadata dict including genres and runtime.
        """
        # OMDb returns genres as a comma-separated string.
        raw_genres = data.get("Genre", "")
        genres = (
            [g.strip() for g in raw_genres.split(",") if g.strip()]
            if raw_genres and raw_genres != "N/A"
            else []
        )

        # OMDb returns runtime as e.g. "152 min".
        runtime = self._safe_int(data.get("Runtime", ""))

        # OMDb has several rating sources; prefer imdbRating.
        raw_rating = data.get("imdbRating", "0")
        rating = self._safe_float(raw_rating if raw_rating != "N/A" else "0")

        poster = data.get("Poster")
        poster_url = poster if poster and poster != "N/A" else None

        return {
            "provider_id": data.get("imdbID", ""),
            "title": data.get("Title", "Unknown"),
            "year": self._safe_year(data.get("Year", "")),
            "overview": data.get("Plot", "") if data.get("Plot") != "N/A" else "",
            "poster_url": poster_url,
            "rating": rating,
            "genres": genres,
            "runtime": runtime,
        }

    # ── Public API (MetadataProvider interface) ───────────────────────────

    def search_movie(self, query: str) -> list:
        """
        Search OMDb for movies matching the given query string.

        Parameters:
            query: Plain-text movie title.

        Returns:
            A list of normalised movie dicts.
            Each item has: provider_id, title, year, overview,
            poster_url, rating.
            Returns an empty list if nothing is found or on error.
        """
        from app.logger import logger
        logger.info("OMDb: searching movies for '%s'.", query)

        data = self._get({"s": query, "type": "movie"})

        if data is None:
            return []

        if data.get("Response") == "False":
            logger.info(
                "OMDb returned no results for '%s': %s",
                query,
                data.get("Error", "unknown reason"),
            )
            return []

        items = data.get("Search", [])
        results = [self._normalise_search_item(item) for item in items]

        logger.info("OMDb search for '%s' returned %d result(s).", query, len(results))
        return results

    def get_movie_details(self, provider_id: str) -> Optional[dict]:
        """
        Fetch full details for a movie by its IMDb ID.

        Parameters:
            provider_id: IMDb ID string, e.g. 'tt0468569'.

        Returns:
            A normalised movie dict including genres and runtime,
            or None if not found or on error.
        """
        from app.logger import logger
        logger.info("OMDb: fetching details for id='%s'.", provider_id)

        data = self._get({"i": provider_id, "plot": "full"})

        if data is None:
            return None

        if data.get("Response") == "False":
            logger.warning(
                "OMDb detail lookup failed for id='%s': %s",
                provider_id,
                data.get("Error", "unknown reason"),
            )
            return None

        result = self._normalise_detail(data)
        logger.info(
            "OMDb details fetched: '%s' (%s).", result["title"], result["year"]
        )
        return result

    def search_show(self, query: str) -> list:
        """
        Search OMDb for TV series matching the given query string.

        Parameters:
            query: Plain-text show title.

        Returns:
            A list of normalised show dicts.
            Returns an empty list if nothing is found or on error.
        """
        from app.logger import logger
        logger.info("OMDb: searching TV series for '%s'.", query)

        data = self._get({"s": query, "type": "series"})

        if data is None:
            return []

        if data.get("Response") == "False":
            logger.info(
                "OMDb TV search returned no results for '%s': %s",
                query,
                data.get("Error", "unknown reason"),
            )
            return []

        items = data.get("Search", [])
        results = [self._normalise_search_item(item) for item in items]

        logger.info(
            "OMDb TV search for '%s' returned %d result(s).", query, len(results)
        )
        return results
