"""
tmdb.py — TMDB (The Movie Database) metadata provider for HookReel.

TMDB API reference: https://developer.themoviedb.org/docs
Library:            tmdbsimple (already installed in the container)
Authentication:     tmdb.API_KEY module attribute

Get a TMDB API key at: https://www.themoviedb.org/settings/api
Set in .env:  METADATA_PROVIDER=tmdb
              METADATA_API_KEY=your_key_here
"""

from typing import Optional

import tmdbsimple as tmdb

from app.metadata.base import MetadataProvider

_POSTER_BASE_URL = "https://image.tmdb.org/t/p/w500"


class TmdbProvider(MetadataProvider):
    """
    MetadataProvider implementation backed by the TMDB API.

    Uses the tmdbsimple library.  Sets tmdb.API_KEY at instantiation
    time so every subsequent call uses the correct key.
    """

    def __init__(self, api_key: str) -> None:
        super().__init__(api_key)
        # The tmdbsimple library reads this module-level attribute before
        # every API call, so setting it once here is sufficient.
        tmdb.API_KEY = api_key

    # ── Internal helpers ──────────────────────────────────────────────────

    def _poster_url(self, poster_path: Optional[str]) -> Optional[str]:
        """
        Build a full TMDB poster URL from a relative path.

        Parameters:
            poster_path: Relative path like '/abc123.jpg', or None.

        Returns:
            A full URL string, or None.
        """
        if poster_path:
            return f"{_POSTER_BASE_URL}{poster_path}"
        return None

    def _normalise_search_item(self, item: dict, media_type: str = "movie") -> dict:
        """
        Convert a single TMDB search result into the standard shape.

        Handles both movie and TV show result formats — TMDB uses
        'title' for movies and 'name' for shows.

        Parameters:
            item:       A single dict from a TMDB search results array.
            media_type: 'movie' or 'tv' — controls which title/date
                        fields are read.

        Returns:
            A normalised metadata dict.
        """
        if media_type == "tv":
            title = item.get("name", item.get("original_name", "Unknown"))
            date_field = item.get("first_air_date", "")
        else:
            title = item.get("title", item.get("original_title", "Unknown"))
            date_field = item.get("release_date", "")

        return {
            "provider_id": str(item.get("id", "")),
            "title": title,
            "year": self._safe_year(date_field),
            "overview": item.get("overview", ""),
            "poster_url": self._poster_url(item.get("poster_path")),
            "rating": self._safe_float(item.get("vote_average", 0)),
        }

    # ── Public API (MetadataProvider interface) ───────────────────────────

    def search_movie(self, query: str) -> list:
        """
        Search TMDB for movies matching the given query string.

        Parameters:
            query: Plain-text movie title.

        Returns:
            A list of normalised movie dicts.
            Returns an empty list if nothing is found or on error.
        """
        from app.logger import logger
        logger.info("TMDB: searching movies for '%s'.", query)

        try:
            search = tmdb.Search()
            response = search.movie(query=query)
            items = response.get("results", [])

            results = [self._normalise_search_item(item, "movie") for item in items]
            logger.info(
                "TMDB search for '%s' returned %d result(s).", query, len(results)
            )
            return results

        except Exception as exc:
            from app.logger import logger
            logger.error("TMDB search_movie failed for '%s': %s", query, exc)
            return []

    def get_movie_details(self, provider_id: str) -> Optional[dict]:
        """
        Fetch full details for a movie by its TMDB numeric ID.

        Parameters:
            provider_id: TMDB movie ID as a string, e.g. '157336'.

        Returns:
            A normalised movie dict including genres and runtime,
            or None if not found or on error.
        """
        from app.logger import logger
        logger.info("TMDB: fetching movie details for id='%s'.", provider_id)

        try:
            movie = tmdb.Movies(int(provider_id))
            data = movie.info()

            genres = [g.get("name", "") for g in data.get("genres", [])]

            result = {
                "provider_id": str(data.get("id", "")),
                "title": data.get("title", "Unknown"),
                "year": self._safe_year(data.get("release_date", "")),
                "overview": data.get("overview", ""),
                "poster_url": self._poster_url(data.get("poster_path")),
                "rating": self._safe_float(data.get("vote_average", 0)),
                "genres": genres,
                "runtime": self._safe_int(data.get("runtime")),
            }

            logger.info(
                "TMDB details fetched: '%s' (%s).", result["title"], result["year"]
            )
            return result

        except Exception as exc:
            from app.logger import logger
            logger.error(
                "TMDB get_movie_details failed for id='%s': %s", provider_id, exc
            )
            return None

    def search_show(self, query: str) -> list:
        """
        Search TMDB for TV shows matching the given query string.

        Parameters:
            query: Plain-text show title.

        Returns:
            A list of normalised show dicts.
            Returns an empty list if nothing is found or on error.
        """
        from app.logger import logger
        logger.info("TMDB: searching TV shows for '%s'.", query)

        try:
            search = tmdb.Search()
            response = search.tv(query=query)
            items = response.get("results", [])

            results = [self._normalise_search_item(item, "tv") for item in items]
            logger.info(
                "TMDB TV search for '%s' returned %d result(s).", query, len(results)
            )
            return results

        except Exception as exc:
            from app.logger import logger
            logger.error("TMDB search_show failed for '%s': %s", query, exc)
            return []

    def search(self, query: str) -> list:
        """
        Alias for search_movie() — used by the web UI and agent tools.

        Parameters:
            query: Plain-text movie title.

        Returns:
            A list of normalised movie dicts.
        """
        return self.search_movie(query)

    def get_details(self, provider_id: str) -> dict:
        """
        Alias for get_movie_details() — used by the web UI and agent tools.

        Parameters:
            provider_id: TMDB movie ID as a string.

        Returns:
            A normalised movie dict with genres and runtime, or None.
        """
        return self.get_movie_details(provider_id)

    def get_similar(self, provider_id: str) -> list:
        """
        Fetch movies similar to the given TMDB movie ID.

        Parameters:
            provider_id: TMDB movie ID as a string, e.g. '157336'.

        Returns:
            A list of normalised movie dicts.
            Returns an empty list if none found or on error.
        """
        from app.logger import get_logger
        logger = get_logger(__name__)
        logger.info("[HookReel] TMDB: fetching similar movies for id='%s'.", provider_id)

        try:
            movie = tmdb.Movies(int(provider_id))
            response = movie.similar_movies()
            items = response.get("results", [])

            results = [self._normalise_search_item(item, "movie") for item in items]
            logger.info(
                "[HookReel] TMDB similar movies for id='%s' returned %d result(s).",
                provider_id, len(results)
            )
            return results

        except Exception as exc:
            logger.error(
                "[HookReel] TMDB get_similar failed for id='%s': %s", provider_id, exc
            )
            return []
