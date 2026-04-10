"""
app/tools.py

HookReel AI tool registry.
Defines the OpenAI-compatible function schemas and the dispatcher
that executes each tool. The AI agent can only call functions
defined here — no arbitrary code execution.
"""

import json
import os

import app.config as config
from app.logger import get_logger
from app.database import get_all_movies, get_movie_by_id, get_movies_by_title
import app.database as database
from app.prowlarr import search_releases
from app.pipeline import request_movie as pipeline_request_movie

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Tool schemas (OpenAI function-calling format)
# ---------------------------------------------------------------------------

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_movie",
            "description": (
                "Search for a movie by title or description. Use this when the user "
                "wants to find a specific movie or is describing a movie they cannot name. "
                "Each result includes a download_url — store it so you can pass it to "
                "request_movie when the user confirms a specific release."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search term — a movie title or descriptive phrase.",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_movie_details",
            "description": (
                "Get full metadata for a movie using its TMDB or OMDb provider ID. "
                "IMPORTANT: provider_id is the numeric ID returned by search_movie "
                "(e.g. '27205'), NOT a torrent filename or release title."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "provider_id": {
                        "type": "string",
                        "description": (
                            "The numeric metadata provider ID returned in the "
                            "'provider_id' field of search_movie results. "
                            "This is a number like '27205', "
                            "NOT a filename or release title."
                        ),
                    }
                },
                "required": ["provider_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_movie",
            "description": (
                "Add a movie to the download queue. Only call this after the user has "
                "confirmed they want the download. When the user confirms a specific "
                "release from search results, pass its download_url so the exact "
                "release is downloaded. If no specific release was chosen, omit "
                "download_url and the pipeline will find the best available release."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Exact movie title.",
                    },
                    "year": {
                        "type": "string",
                        "description": "Release year to disambiguate if needed.",
                    },
                    "download_url": {
                        "type": "string",
                        "description": (
                            "The direct download URL of the specific release the user "
                            "confirmed. Comes from the download_url field in "
                            "search_movie results. Must start with magnet:? or http. "
                            "When provided, the pipeline downloads this exact release "
                            "and skips its internal search."
                        ),
                    },
                    "release_title": {
                        "type": "string",
                        "description": (
                            "The full release title as returned by search_movie "
                            "(e.g. 'Inception.2010.1080p.BluRay.x265-GROUP'). "
                            "Used for logging and torrent tracking."
                        ),
                    },
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_download_status",
            "description": (
                "Check the current download progress of a movie that has been requested."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "movie_id": {
                        "type": "integer",
                        "description": "The database ID returned when the movie was requested.",
                    }
                },
                "required": ["movie_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_library",
            "description": "List all movies currently in the HookReel database and their status.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "suggest_similar",
            "description": (
                "Suggest movies similar to a given title using the metadata provider."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Movie to base suggestions on.",
                    }
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_exists",
            "description": (
                "Check if a movie is already in the HookReel database or download queue. "
                "ALWAYS call this before request_movie. Returns all matching entries "
                "regardless of status, including failed and quarantined downloads."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Movie title to check.",
                    }
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_show",
            "description": (
                "Search for a TV show by name. Use this when the user wants to find "
                "a TV show. Returns top 3 results with provider_id, title, year, "
                "network, and status."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "TV show title or descriptive phrase.",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_show",
            "description": (
                "Download a TV show, season, or specific episode. "
                "ALWAYS call check_show_exists first. "
                "If season and episode are provided, downloads that episode only. "
                "If only season is provided, downloads the full season. "
                "If neither is provided, downloads season 1 — confirm with user first."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "TV show title.",
                    },
                    "season": {
                        "type": "integer",
                        "description": "Season number (optional).",
                    },
                    "episode": {
                        "type": "integer",
                        "description": "Episode number within the season (optional).",
                    },
                    "download_url": {
                        "type": "string",
                        "description": "Direct magnet or torrent URL (optional, skips search).",
                    },
                    "release_title": {
                        "type": "string",
                        "description": "Human-readable release name (optional).",
                    },
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_show_status",
            "description": (
                "Get the download status of all episodes for a tracked TV show. "
                "Use this when the user asks what episodes they have or the "
                "download progress of a show."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "show_id": {
                        "type": "integer",
                        "description": "Database ID of the show (from check_show_exists or list_tracked_shows).",
                    }
                },
                "required": ["show_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_tracked_shows",
            "description": (
                "List all TV shows currently being tracked in HookReel. "
                "Use this when the user asks what TV shows they have or are tracking."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_episode_list",
            "description": (
                "Get the full episode list for a TV show from the metadata provider. "
                "Use this when the user wants to know what episodes exist, air dates, "
                "or episode titles. Requires provider_id from search_show."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "provider_id": {
                        "type": "string",
                        "description": "TVmaze show ID from search_show results.",
                    },
                    "season": {
                        "type": "integer",
                        "description": "Filter to a specific season (optional).",
                    },
                },
                "required": ["provider_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_show_exists",
            "description": (
                "Check if a TV show is already tracked in HookReel. "
                "ALWAYS call this before request_show. Returns tracking status "
                "and episode count if the show exists."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "TV show title to check.",
                    }
                },
                "required": ["title"],
            },
        },
    },
    # --- Watch Mode tools (Phase 6.5) ---
    {
        "type": "function",
        "function": {
            "name": "watch_movie",
            "description": (
                "Watch a movie that has been downloaded. "
                "Generates a Jellyfin play link or HLS stream URL. "
                "ALWAYS call check_exists first to confirm the movie is in the library. "
                "Do not generate a watch link for content that has not been downloaded."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Movie title to watch.",
                    },
                    "movie_id": {
                        "type": "integer",
                        "description": "Database ID of the movie (optional).",
                    },
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "watch_next_episode",
            "description": (
                "Watch the next unwatched episode of a TV show. "
                "Automatically determines which episode to play based on watch history. "
                "ALWAYS confirm with the user which episode you are about to play "
                "before generating the link."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "show_title": {
                        "type": "string",
                        "description": "TV show title.",
                    },
                    "show_id": {
                        "type": "integer",
                        "description": "Database ID of the show (optional).",
                    },
                },
                "required": ["show_title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "watch_episode",
            "description": (
                "Watch a specific TV episode by season and episode number. "
                "ALWAYS call check_show_exists first to confirm the show is in the library."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "show_title": {
                        "type": "string",
                        "description": "TV show title.",
                    },
                    "season": {
                        "type": "integer",
                        "description": "Season number.",
                    },
                    "episode": {
                        "type": "integer",
                        "description": "Episode number.",
                    },
                },
                "required": ["show_title", "season", "episode"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_watch_history",
            "description": (
                "Show recently watched movies and TV episodes. "
                "Use this when the user asks what they have watched recently."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Number of recent entries to return (default 10).",
                    },
                },
                "required": [],
            },
        },
    },
    # --- Stream control tools (Phase 6.5 Amendment) ---
    {
        "type": "function",
        "function": {
            "name": "stop_stream",
            "description": (
                "Stop a currently active HLS stream for a movie or episode. "
                "Only relevant when Jellyfin is disabled and HLS streaming is active."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "media_id": {
                        "type": "integer",
                        "description": "Database ID of the media currently being streamed.",
                    },
                },
                "required": ["media_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_active_streams",
            "description": (
                "List all currently active HLS streams. "
                "Returns media_id, title, and started_at for each active stream."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    # --- File management tools (Phase 6.5 Amendment) ---
    {
        "type": "function",
        "function": {
            "name": "delete_media",
            "description": (
                "Permanently delete a downloaded movie or TV episode from the library. "
                "IMPORTANT: Only available when DELETE_ENABLED=true in settings. "
                "ALWAYS ask the user to confirm before calling this with confirm=true. "
                "NEVER delete multiple files in one operation without confirming each individually."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "media_type": {
                        "type": "string",
                        "description": "Either 'movie' or 'episode'.",
                    },
                    "media_id": {
                        "type": "integer",
                        "description": "Database ID of the item to delete.",
                    },
                    "confirm": {
                        "type": "boolean",
                        "description": (
                            "Must be true to proceed. Only set true after the user "
                            "has explicitly confirmed deletion in this conversation turn."
                        ),
                    },
                },
                "required": ["media_type", "media_id", "confirm"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "move_media",
            "description": (
                "Move a media file to a different folder. "
                "Only available when DELETE_ENABLED=true in settings. "
                "Destination must be within the configured MOVIES_PATH or TV_PATH."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "media_type": {
                        "type": "string",
                        "description": "Either 'movie' or 'episode'.",
                    },
                    "media_id": {
                        "type": "integer",
                        "description": "Database ID of the item to move.",
                    },
                    "destination": {
                        "type": "string",
                        "description": "Target folder path within MOVIES_PATH or TV_PATH.",
                    },
                },
                "required": ["media_type", "media_id", "destination"],
            },
        },
    },
    # --- RTMP streaming tool (Phase 7a) ---
    {
        "type": "function",
        "function": {
            "name": "stream_media",
            "description": (
                "Stream a downloaded movie or TV episode to the user's Telegram "
                "cinema channel via RTMP. "
                "ALWAYS call check_exists (for movies) or check_show_exists (for TV) "
                "first to confirm the file is in the library. "
                "If RTMP is not configured, guide the user through /setupstream. "
                "If a stream is already running, ask the user whether to stop it first."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Title of the movie or episode to stream.",
                    },
                    "media_type": {
                        "type": "string",
                        "description": "Either 'movie' or 'episode'.",
                    },
                    "media_id": {
                        "type": "integer",
                        "description": "Database ID of the movie or episode (optional).",
                    },
                },
                "required": ["title", "media_type"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Tool implementation functions
# ---------------------------------------------------------------------------

def _tool_search_movie(query: str) -> str:
    """Search Prowlarr for movie releases matching the query."""
    logger.info("[HookReel] tool search_movie called: query=%s", query)
    try:
        results = search_releases(query, category=2000)
        if not results:
            return "No results found for that search."
        lines = [f"Found {len(results)} result(s) for '{query}':"]
        for index, release in enumerate(results[:10], start=1):
            title = release.get("title", "Unknown")
            size_bytes = release.get("size", 0)
            size_gb = size_bytes / (1024 ** 3) if size_bytes else 0
            seeders = release.get("seeders", 0)
            download_url = (
                release.get("magnetUrl")
                or release.get("downloadUrl")
                or release.get("download_url", "")
            )
            lines.append(
                f"  {index}. {title} | {size_gb:.2f} GB | {seeders} seeders"
                f" | download_url: {download_url}"
            )
        return "\n".join(lines)
    except Exception as error:
        logger.error("[HookReel] tool search_movie failed: %s", error)
        return f"Search failed: {error}"


def _tool_get_movie_details(provider_id: str) -> str:
    """Fetch full movie details from the configured metadata provider."""
    logger.info("[HookReel] tool get_movie_details called: provider_id=%s", provider_id)
    try:
        provider = _get_metadata_provider()
        details = provider.get_details(provider_id)
        if not details:
            return f"No details found for provider ID: {provider_id}"
        title = details.get("title", "Unknown")
        year = details.get("year", "?")
        overview = details.get("overview", "No overview available.")
        rating = details.get("rating", "N/A")
        genres = ", ".join(details.get("genres", [])) or "N/A"
        runtime = details.get("runtime", "N/A")
        return (
            f"Title: {title} ({year})\n"
            f"Rating: {rating}\n"
            f"Genres: {genres}\n"
            f"Runtime: {runtime} min\n"
            f"Overview: {overview}"
        )
    except Exception as error:
        logger.error("[HookReel] tool get_movie_details failed: %s", error)
        return f"Could not retrieve movie details: {error}"


def _tool_request_movie(
    title: str,
    year: str = None,
    download_url: str = None,
    release_title: str = None,
) -> str:
    """Add a movie to the download queue via the pipeline."""
    logger.info(
        "[HookReel] tool request_movie called: title=%s year=%s "
        "download_url=%s release_title=%s",
        title, year, download_url, release_title,
    )
    try:
        search_title = f"{title} {year}".strip() if year else title
        result = pipeline_request_movie(
            title=search_title,
            download_url=download_url,
            release_title=release_title,
        )
        if result and isinstance(result, dict):
            movie_id = result.get("movie_id", "unknown")
            status = result.get("status", "unknown")
            return (
                f"Download queued for '{title}'. "
                f"Database movie_id: {movie_id} | Status: {status}"
            )
        return f"Download queued for '{title}'. Result: {result}"
    except Exception as error:
        logger.error("[HookReel] tool request_movie failed: %s", error)
        return f"Failed to queue download for '{title}': {error}"


def _tool_get_download_status(movie_id: int) -> str:
    """Check download status for a movie by its database ID."""
    logger.info("[HookReel] tool get_download_status called: movie_id=%s", movie_id)
    try:
        from app.qbittorrent import get_torrent_status, get_torrent_hash_by_name
        movie = get_movie_by_id(movie_id)
        if not movie:
            return f"No movie found with ID {movie_id}."
        title = movie.get("title", "Unknown")
        status = movie.get("status", "unknown")
        torrent_name = movie.get("torrent_name")
        if not torrent_name:
            return (
                f"'{title}' (ID {movie_id}) — status: {status}. "
                "No torrent name recorded yet."
            )
        torrent_hash = get_torrent_hash_by_name(torrent_name)
        if not torrent_hash:
            return (
                f"'{title}' (ID {movie_id}) — status: {status}. "
                "Torrent not found in qBittorrent."
            )
        torrent_info = get_torrent_status(torrent_hash)
        if not torrent_info:
            return f"'{title}' (ID {movie_id}) — status: {status}. No torrent data."
        progress = torrent_info.get("progress", 0) * 100
        eta_seconds = torrent_info.get("eta", 0)
        eta_minutes = int(eta_seconds / 60) if eta_seconds else 0
        filled = int(progress / 10)
        bar = "█" * filled + "░" * (10 - filled)
        eta_text = f"about {eta_minutes} min remaining" if eta_minutes else "calculating..."
        return (
            f"'{title}' (ID {movie_id})\n"
            f"{bar} {progress:.0f}% — {eta_text}\n"
            f"Status: {status}"
        )
    except Exception as error:
        logger.error("[HookReel] tool get_download_status failed: %s", error)
        return f"Could not check download status: {error}"


def _tool_list_library() -> str:
    """Return all movies in the HookReel database."""
    logger.info("[HookReel] tool list_library called")
    try:
        movies = get_all_movies()
        if not movies:
            return "The library is empty. No movies have been requested yet."
        lines = [f"Library — {len(movies)} movie(s):"]
        for movie in movies:
            movie_id = movie.get("id", "?")
            title = movie.get("title", "Unknown")
            status = movie.get("status", "unknown")
            lines.append(f"  [{movie_id}] {title} — {status}")
        return "\n".join(lines)
    except Exception as error:
        logger.error("[HookReel] tool list_library failed: %s", error)
        return f"Could not retrieve library: {error}"


def _tool_suggest_similar(title: str) -> str:
    """Suggest movies similar to the given title using the metadata provider."""
    logger.info("[HookReel] tool suggest_similar called: title=%s", title)
    try:
        provider = _get_metadata_provider()
        suggestions = provider.get_similar(title)
        if not suggestions:
            return f"No similar movies found for '{title}'."
        lines = [f"Movies similar to '{title}':"]
        for index, movie in enumerate(suggestions[:8], start=1):
            suggestion_title = movie.get("title", "Unknown")
            year = movie.get("year", "?")
            lines.append(f"  {index}. {suggestion_title} ({year})")
        return "\n".join(lines)
    except Exception as error:
        logger.error("[HookReel] tool suggest_similar failed: %s", error)
        return f"Could not get similar movies: {error}"


def _tool_check_exists(title: str) -> str:
    """Check if a movie is already in the HookReel database."""
    logger.info("[HookReel] tool check_exists called: title=%s", title)
    try:
        matches = get_movies_by_title(title)
        if not matches:
            return f"'{title}' is not in the HookReel library or queue."
        lines = [f"'{title}' found in library:"]
        for movie in matches:
            movie_id = movie.get("id", "?")
            stored_title = movie.get("title", "Unknown")
            status = movie.get("status", "unknown")
            file_path = movie.get("file_path", "")
            if status == "complete":
                lines.append(
                    f"  [{movie_id}] {stored_title} — status: complete "
                    f"(already in library) | file_path: {file_path}"
                )
            elif status == "downloading":
                lines.append(
                    f"  [{movie_id}] {stored_title} — status: downloading"
                )
            elif status == "failed":
                lines.append(
                    f"  [{movie_id}] {stored_title} — status: failed "
                    f"(previous attempt failed — ask user if they want to retry)"
                )
            elif status == "quarantined":
                lines.append(
                    f"  [{movie_id}] {stored_title} — status: quarantined "
                    f"(malware detected — ask user if they want a different release)"
                )
            else:
                lines.append(f"  [{movie_id}] {stored_title} — status: {status}")
        return "\n".join(lines)
    except Exception as error:
        logger.error("[HookReel] tool check_exists failed: %s", error)
        return f"Could not check library: {error}"


# ---------------------------------------------------------------------------
# Watch Mode tool implementation functions (Phase 6.5)
# ---------------------------------------------------------------------------

def _tool_watch_movie(title: str, movie_id: int = None) -> str:
    """Generate a watch link or HLS stream URL for a downloaded movie."""
    logger.info(
        "[HookReel] tool watch_movie called: title=%s movie_id=%s",
        title, movie_id
    )
    try:
        from app.watch import watch_movie
        result = watch_movie(title=title, movie_id=movie_id)
        if "error" in result:
            return result["error"]
        if result["mode"] == "jellyfin":
            return (
                f"Ready to watch {result['title']}!\n"
                f"Open in browser: {result['web_link']}\n"
                f"Open in Jellyfin app: {result['app_link']}"
            )
        return (
            f"Stream ready for {result['title']}!\n"
            f"Open this in VLC or your browser:\n{result['stream_url']}"
        )
    except Exception as error:
        logger.error("[HookReel] tool watch_movie failed: %s", error)
        return f"Watch movie failed: {error}"


def _tool_watch_next_episode(show_title: str, show_id: int = None) -> str:
    """Find and generate a watch link for the next unwatched episode."""
    logger.info(
        "[HookReel] tool watch_next_episode called: show_title=%s show_id=%s",
        show_title, show_id
    )
    try:
        from app.watch import watch_episode
        result = watch_episode(show_title=show_title, show_id=show_id)
        if "error" in result:
            return result["error"]
        if result["mode"] == "jellyfin":
            return (
                f"Ready to watch {result['title']}!\n"
                f"Open in browser: {result['web_link']}\n"
                f"Open in Jellyfin app: {result['app_link']}"
            )
        return (
            f"Stream ready for {result['title']}!\n"
            f"Open this in VLC or your browser:\n{result['stream_url']}"
        )
    except Exception as error:
        logger.error("[HookReel] tool watch_next_episode failed: %s", error)
        return f"Watch next episode failed: {error}"


def _tool_watch_episode(
    show_title: str,
    season: int,
    episode: int
) -> str:
    """Generate a watch link for a specific TV episode."""
    logger.info(
        "[HookReel] tool watch_episode called: show_title=%s S%02dE%02d",
        show_title, season, episode
    )
    try:
        from app.watch import watch_episode
        result = watch_episode(
            show_title=show_title,
            season=season,
            episode=episode,
        )
        if "error" in result:
            return result["error"]
        if result["mode"] == "jellyfin":
            return (
                f"Ready to watch {result['title']}!\n"
                f"Open in browser: {result['web_link']}\n"
                f"Open in Jellyfin app: {result['app_link']}"
            )
        return (
            f"Stream ready for {result['title']}!\n"
            f"Open this in VLC or your browser:\n{result['stream_url']}"
        )
    except Exception as error:
        logger.error("[HookReel] tool watch_episode failed: %s", error)
        return f"Watch episode failed: {error}"


def _tool_get_watch_history(limit: int = 10) -> str:
    """Return recently watched movies and TV episodes."""
    logger.info("[HookReel] tool get_watch_history called: limit=%s", limit)
    try:
        from app.watch import get_watch_history
        history = get_watch_history(limit=limit)
        if not history:
            return "No watch history yet."
        lines = [f"Recently watched ({len(history)} item(s)):"]
        for entry in history:
            media_type = entry.get("media_type", "?")
            title = entry.get("title", "Unknown")
            watched_at = entry.get("watched_at", "?")[:10]
            completed = "✓" if entry.get("completed") else "…"
            lines.append(
                f"  {completed} [{media_type}] {title} — {watched_at}"
            )
        return "\n".join(lines)
    except Exception as error:
        logger.error("[HookReel] tool get_watch_history failed: %s", error)
        return f"Get watch history failed: {error}"


# ---------------------------------------------------------------------------
# Stream control tool implementation functions (Phase 6.5 Amendment)
# ---------------------------------------------------------------------------

def _tool_stop_stream(media_id: int) -> str:
    """Stop an active HLS stream by media database ID."""
    logger.info("[HookReel] tool stop_stream called: media_id=%s", media_id)
    try:
        from app.hls_streamer import hls_streamer
        stopped = hls_streamer.stop_stream(media_id)
        if stopped:
            return f"Stream for media_id={media_id} has been stopped."
        return f"No active stream found for media_id={media_id}."
    except Exception as error:
        logger.error("[HookReel] tool stop_stream failed: %s", error)
        return f"Stop stream failed: {error}"


def _tool_get_active_streams() -> str:
    """List all currently active HLS streams."""
    logger.info("[HookReel] tool get_active_streams called")
    try:
        from app.hls_streamer import hls_streamer
        streams = hls_streamer.get_active_streams()
        if not streams:
            return "No active streams."
        lines = [f"Active streams ({len(streams)}):"]
        for stream in streams:
            lines.append(
                f"  media_id={stream['media_id']} "
                f"started={stream['started_at'][:16]} "
                f"url={stream['stream_url']}"
            )
        return "\n".join(lines)
    except Exception as error:
        logger.error("[HookReel] tool get_active_streams failed: %s", error)
        return f"Get active streams failed: {error}"


# ---------------------------------------------------------------------------
# File management tool implementation functions (Phase 6.5 Amendment)
# ---------------------------------------------------------------------------

def _validate_path(file_path: str) -> bool:
    """Validate that a file path is within the configured media directories."""
    allowed_roots = [
        os.path.realpath(config.MOVIES_PATH),
        os.path.realpath(config.TV_PATH),
    ]
    real_path = os.path.realpath(file_path)
    for root in allowed_roots:
        if real_path.startswith(root + os.sep) or real_path == root:
            return True
    logger.warning(
        "[HookReel] _validate_path: rejected path outside allowed roots: %s",
        file_path
    )
    return False


def _tool_delete_media(
    media_type: str,
    media_id: int,
    confirm: bool
) -> str:
    """Permanently delete a media file and its database record."""
    logger.info(
        "[HookReel] tool delete_media called: media_type=%s media_id=%s confirm=%s",
        media_type, media_id, confirm
    )

    if not config.DELETE_ENABLED:
        return (
            "Deletion is disabled. Enable it in Settings → File Management "
            "to allow the agent to delete files."
        )

    if not confirm:
        return (
            "Deletion requires explicit confirmation. "
            "Please confirm you want to permanently delete this item."
        )

    try:
        file_path = None
        title = "Unknown"

        if media_type == "movie":
            record = database.get_movie_by_id(media_id)
            if not record:
                return f"No movie found with ID {media_id}."
            title = record.get("title", "Unknown")
            file_path = record.get("file_path")
        elif media_type == "episode":
            connection = database.get_connection()
            cursor = connection.cursor()
            cursor.execute("SELECT * FROM episodes WHERE id = ?", (media_id,))
            row = cursor.fetchone()
            connection.close()
            if not row:
                return f"No episode found with ID {media_id}."
            record = dict(row)
            title = record.get("title", f"Episode {media_id}")
            file_path = record.get("file_path")
        else:
            return f"Unknown media_type '{media_type}'. Use 'movie' or 'episode'."

        if not file_path:
            return (
                f"'{title}' has no file path recorded — "
                "nothing to delete from disk."
            )

        if not _validate_path(file_path):
            return (
                f"Deletion rejected: path '{file_path}' is outside the "
                "configured media directories. Operation blocked for safety."
            )

        file_size_mb = 0.0
        if os.path.isfile(file_path):
            file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
            os.remove(file_path)
            logger.info(
                "[HookReel] delete_media: deleted file %s (%.1f MB) "
                "media_type=%s media_id=%d",
                file_path, file_size_mb, media_type, media_id
            )
        else:
            logger.warning(
                "[HookReel] delete_media: file not found on disk: %s", file_path
            )

        connection = database.get_connection()
        cursor = connection.cursor()
        if media_type == "movie":
            cursor.execute("DELETE FROM movies WHERE id = ?", (media_id,))
        else:
            cursor.execute("DELETE FROM episodes WHERE id = ?", (media_id,))
        connection.commit()
        connection.close()

        from app.jellyfin import refresh_jellyfin_library
        refresh_jellyfin_library()

        return (
            f"'{title}' has been permanently deleted "
            f"(file: {file_path}, size: {file_size_mb:.1f} MB). "
            "Jellyfin library refresh triggered."
        )

    except Exception as error:
        logger.error("[HookReel] tool delete_media failed: %s", error)
        return f"Delete media failed: {error}"


def _tool_move_media(
    media_type: str,
    media_id: int,
    destination: str
) -> str:
    """Move a media file to a different folder within the allowed media paths."""
    logger.info(
        "[HookReel] tool move_media called: media_type=%s media_id=%s "
        "destination=%s",
        media_type, media_id, destination
    )

    if not config.DELETE_ENABLED:
        return (
            "File move is disabled. Enable it in Settings → File Management "
            "to allow the agent to move files."
        )

    try:
        file_path = None
        title = "Unknown"

        if media_type == "movie":
            record = database.get_movie_by_id(media_id)
            if not record:
                return f"No movie found with ID {media_id}."
            title = record.get("title", "Unknown")
            file_path = record.get("file_path")
        elif media_type == "episode":
            connection = database.get_connection()
            cursor = connection.cursor()
            cursor.execute("SELECT * FROM episodes WHERE id = ?", (media_id,))
            row = cursor.fetchone()
            connection.close()
            if not row:
                return f"No episode found with ID {media_id}."
            record = dict(row)
            title = record.get("title", f"Episode {media_id}")
            file_path = record.get("file_path")
        else:
            return f"Unknown media_type '{media_type}'. Use 'movie' or 'episode'."

        if not file_path:
            return f"'{title}' has no file path recorded — nothing to move."

        if not _validate_path(file_path):
            return (
                f"Move rejected: source path '{file_path}' is outside the "
                "configured media directories."
            )

        if not _validate_path(destination):
            return (
                f"Move rejected: destination '{destination}' is outside the "
                "configured media directories. Operation blocked for safety."
            )

        filename = os.path.basename(file_path)
        new_path = os.path.join(destination, filename)

        os.makedirs(destination, exist_ok=True)
        os.rename(file_path, new_path)

        connection = database.get_connection()
        cursor = connection.cursor()
        now = __import__("datetime").datetime.utcnow().isoformat()
        if media_type == "movie":
            cursor.execute(
                "UPDATE movies SET file_path = ?, updated_date = ? WHERE id = ?",
                (new_path, now, media_id)
            )
        else:
            cursor.execute(
                "UPDATE episodes SET file_path = ?, updated_date = ? WHERE id = ?",
                (new_path, now, media_id)
            )
        connection.commit()
        connection.close()

        logger.info(
            "[HookReel] move_media: moved '%s' from %s to %s",
            title, file_path, new_path
        )

        from app.jellyfin import refresh_jellyfin_library
        refresh_jellyfin_library()

        return (
            f"'{title}' has been moved to {new_path}. "
            "Jellyfin library refresh triggered."
        )

    except Exception as error:
        logger.error("[HookReel] tool move_media failed: %s", error)
        return f"Move media failed: {error}"


# ---------------------------------------------------------------------------
# RTMP streaming tool implementation (Phase 7a)
# ---------------------------------------------------------------------------

def _tool_stream_media(
    title: str,
    media_type: str,
    media_id: int = None,
) -> str:
    """
    Stream a downloaded movie or TV episode to the Telegram cinema channel.

    Looks up the file path from the database, checks RTMP credentials
    are configured, checks nothing is already streaming, then starts
    the FFmpeg RTMP push via app.streaming.
    """
    logger.info(
        "[HookReel] tool stream_media called: title=%s media_type=%s media_id=%s",
        title, media_type, media_id
    )

    # Check RTMP is configured.
    import os
    # Read RTMP credentials directly from .env at call time
    # so key rotations via /setupstream take effect immediately
    # without needing a container restart.
    _rtmp_env = {}
    try:
        with open("/config/.env") as _f:
            for _line in _f:
                _line = _line.strip()
                if _line.startswith("TELEGRAM_RTMP_URL="):
                    _rtmp_env["url"] = _line.split("=", 1)[1]
                elif _line.startswith("TELEGRAM_RTMP_KEY="):
                    _rtmp_env["key"] = _line.split("=", 1)[1]
    except Exception:
        pass
    rtmp_url = _rtmp_env.get("url", os.environ.get("TELEGRAM_RTMP_URL", ""))
    rtmp_key = _rtmp_env.get("key", os.environ.get("TELEGRAM_RTMP_KEY", ""))
    if not rtmp_url or not rtmp_key:
        return (
            "RTMP streaming is not set up yet.\n\n"
            "To set it up, send /setupstream in this chat and follow the instructions. "
            "It only takes 2 minutes and you only need to do it once."
        )

    # Check nothing is already streaming.
    import app.streaming as streaming
    if streaming.is_streaming():
        info = streaming.current_stream_info()
        current = info["title"] if info else "unknown"
        return (
            f"Already streaming: {current}\n\n"
            f"Send /stopstream to stop it, then ask me to stream {title} again."
        )

    # Resolve file path from database.
    file_path = None

    try:
        if media_type == "movie":
            if media_id:
                record = database.get_movie_by_id(media_id)
            else:
                matches = database.get_movies_by_title(title)
                record = next(
                    (m for m in matches if m.get("status") == "complete"), None
                ) if matches else None

            if not record:
                return (
                    f"'{title}' was not found in the library. "
                    "Make sure it has been downloaded first."
                )
            if record.get("status") != "complete":
                return (
                    f"'{title}' is not fully downloaded yet "
                    f"(status: {record.get('status')}). "
                    "Wait for the download to complete before streaming."
                )
            file_path = record.get("file_path")

        elif media_type == "episode":
            if media_id:
                connection = database.get_connection()
                cursor = connection.cursor()
                cursor.execute("SELECT * FROM episodes WHERE id = ?", (media_id,))
                row = cursor.fetchone()
                connection.close()
                record = dict(row) if row else None
            else:
                return (
                    "To stream a TV episode, please provide the episode ID. "
                    "Use get_show_status to find the episode ID."
                )

            if not record:
                return f"Episode ID {media_id} was not found in the database."
            file_path = record.get("file_path")

        else:
            return f"Unknown media_type '{media_type}'. Use 'movie' or 'episode'."

    except Exception as error:
        logger.error("[HookReel] stream_media DB lookup failed: %s", error)
        return f"Could not look up '{title}' in the database: {error}"

    if not file_path:
        return (
            f"'{title}' has no file path recorded in the database. "
            "The file may not have been post-processed yet."
        )

    if not os.path.exists(file_path):
        return (
            f"File not found on disk: {file_path}\n"
            "The database record exists but the file is missing."
        )

    # Start the stream.
    result = streaming.start_stream(
        file_path=file_path,
        rtmp_url=rtmp_url,
        rtmp_key=rtmp_key,
        title=title,
    )

    if result["success"]:
        return (
            f"Streaming {title} to your Telegram cinema channel now!\n\n"
            f"Open your HookReel Cinema group in Telegram to watch.\n"
            f"Send /stopstream when you're done."
        )
    return f"Failed to start stream: {result['message']}"


# ---------------------------------------------------------------------------
# Metadata provider helper
# ---------------------------------------------------------------------------

def _get_metadata_provider():
    """Instantiate and return the configured metadata provider."""
    provider_name = config.METADATA_PROVIDER.lower()
    api_key = config.METADATA_API_KEY
    if provider_name == "tmdb":
        from app.metadata.tmdb import TmdbProvider
        return TmdbProvider(api_key)
    elif provider_name == "omdb":
        from app.metadata.omdb import OmdbProvider
        return OmdbProvider(api_key)
    else:
        raise ValueError(f"Unknown metadata provider: {provider_name}")


# ---------------------------------------------------------------------------
# Tool dispatcher
# ---------------------------------------------------------------------------

_TOOL_DISPATCH = {
    "search_movie": lambda args: _tool_search_movie(**args),
    "get_movie_details": lambda args: _tool_get_movie_details(**args),
    "request_movie": lambda args: _tool_request_movie(**args),
    "get_download_status": lambda args: _tool_get_download_status(**args),
    "list_library": lambda args: _tool_list_library(),
    "suggest_similar": lambda args: _tool_suggest_similar(**args),
    "check_exists": lambda args: _tool_check_exists(**args),
    "search_show": lambda args: _tool_search_show(**args),
    "request_show": lambda args: _tool_request_show(**args),
    "get_show_status": lambda args: _tool_get_show_status(**args),
    "list_tracked_shows": lambda args: _tool_list_tracked_shows(),
    "get_episode_list": lambda args: _tool_get_episode_list(**args),
    "check_show_exists": lambda args: _tool_check_show_exists(**args),
    # Watch Mode (Phase 6.5)
    "watch_movie": lambda args: _tool_watch_movie(**args),
    "watch_next_episode": lambda args: _tool_watch_next_episode(**args),
    "watch_episode": lambda args: _tool_watch_episode(**args),
    "get_watch_history": lambda args: _tool_get_watch_history(**args),
    # Stream control (Phase 6.5 Amendment)
    "stop_stream": lambda args: _tool_stop_stream(**args),
    "get_active_streams": lambda args: _tool_get_active_streams(),
    # File management (Phase 6.5 Amendment)
    "delete_media": lambda args: _tool_delete_media(**args),
    "move_media": lambda args: _tool_move_media(**args),
    # RTMP streaming (Phase 7a)
    "stream_media": lambda args: _tool_stream_media(**args),
    # Library scan (Phase 8)
    "scan_library": lambda args: _tool_scan_library(),
    # Persona tools (Phase 8)
    "get_agent_info": lambda args: _tool_get_agent_info(),
    "update_agent_name": lambda args: _tool_update_agent_name(**args),
    "update_personality": lambda args: _tool_update_personality(**args),

}

# ---------------------------------------------------------------------------
# Persona tools (Phase 8)
# ---------------------------------------------------------------------------

TOOL_SCHEMAS.append({
    "type": "function",
    "function": {
        "name": "get_agent_info",
        "description": (
            "Get the agent's current name, version, and personality style."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
})

TOOL_SCHEMAS.append({
    "type": "function",
    "function": {
        "name": "update_agent_name",
        "description": (
            "Change the agent's name. The agent will use this name in all "
            "future responses. Use when the user asks to rename the agent."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "new_name": {
                    "type": "string",
                    "description": "The new name for the agent.",
                }
            },
            "required": ["new_name"],
        },
    },
})

TOOL_SCHEMAS.append({
    "type": "function",
    "function": {
        "name": "update_personality",
        "description": (
            "Change the agent's personality style. Use when the user asks "
            "to change how the agent speaks."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "style": {
                    "type": "string",
                    "description": (
                        "Personality style: pirate, professional, or friendly."
                    ),
                }
            },
            "required": ["style"],
        },
    },
})


def _tool_get_agent_info() -> str:
    """Return current agent name, version, and personality."""
    try:
        from app.persona import load_persona
        persona = load_persona()
        return (
            "Agent name: {name}\n"
            "Version: {version} {version_name}\n"
            "Personality: {personality}"
        ).format(**persona)
    except Exception as exc:
        return "Could not load agent info: {}".format(exc)


def _tool_update_agent_name(new_name: str) -> str:
    """Update the agent name in persona.json."""
    try:
        from app.persona import update_name
        success = update_name(new_name)
        if success:
            return "Done. My name has been updated to {}.".format(new_name)
        return (
            "Could not update name. Names must be letters, spaces, or "
            "hyphens only, and no longer than 30 characters."
        )
    except Exception as exc:
        return "Name update failed: {}".format(exc)


def _tool_update_personality(style: str) -> str:
    """Update the personality style in persona.json."""
    try:
        from app.persona import update_personality
        success = update_personality(style)
        if success:
            return "Personality updated to: {}.".format(style)
        return (
            "Invalid style '{}'. Choose from: pirate, professional, friendly.".format(
                style
            )
        )
    except Exception as exc:
        return "Personality update failed: {}".format(exc)


def execute_tool(name: str, arguments: dict) -> str:
    """
    Dispatch a tool call by name and return the result as a string.

    Arguments are passed as a dict parsed from the model's JSON output.
    Always returns a string — never raises to the AI layer.
    """
    logger.info("[HookReel] execute_tool: name=%s args=%s", name, arguments)
    handler = _TOOL_DISPATCH.get(name)
    if not handler:
        error_message = f"Unknown tool: {name}"
        logger.warning("[HookReel] %s", error_message)
        return error_message
    try:
        result = handler(arguments)
        logger.info("[HookReel] tool %s result: %s", name, str(result)[:200])
        return str(result)
    except Exception as error:
        logger.error(
            "[HookReel] execute_tool unexpected error: tool=%s error=%s", name, error
        )
        return f"Tool '{name}' failed unexpectedly: {error}"


# ---------------------------------------------------------------------------
# TV tool implementation functions
# ---------------------------------------------------------------------------

def _tool_search_show(query: str) -> str:
    """Search TVmaze for TV shows matching the query."""
    logger.info("[HookReel] tool search_show called: query=%s", query)
    try:
        from app.tv_metadata import get_show_info
        results = get_show_info(query)
        if not results:
            return f"No TV shows found for '{query}'."
        lines = [f"Found {len(results)} result(s) for '{query}':"]
        for index, show in enumerate(results[:3], start=1):
            lines.append(
                f"  {index}. {show['title']} ({show['year']}) "
                f"| {show['status']} | {show['network']} "
                f"| provider_id: {show['provider_id']}"
            )
        return "\n".join(lines)
    except Exception as error:
        logger.error("[HookReel] tool search_show failed: %s", error)
        return f"TV show search failed: {error}"


def _tool_request_show(
    title: str,
    season: int = None,
    episode: int = None,
    download_url: str = None,
    release_title: str = None
) -> str:
    """Request a TV show, season, or specific episode for download."""
    logger.info(
        "[HookReel] tool request_show: title=%s season=%s episode=%s",
        title, season, episode
    )
    try:
        from app.tv_pipeline import request_show
        result = request_show(
            title=title,
            season=season,
            episode=episode,
            download_url=download_url,
            release_title=release_title
        )
        return result.get("message", str(result))
    except Exception as error:
        logger.error("[HookReel] tool request_show failed: %s", error)
        return f"TV show request failed: {error}"


def _tool_get_show_status(show_id: int) -> str:
    """Get download status for all episodes of a tracked show."""
    logger.info(
        "[HookReel] tool get_show_status called: show_id=%s", show_id
    )
    try:
        from app.tv_pipeline import get_show_download_progress
        progress = get_show_download_progress(int(show_id))
        if "error" in progress:
            return progress["error"]
        lines = [
            f"{progress['title']} ({progress['year']}) — "
            f"{progress['episode_count']} episode(s) tracked"
        ]
        for ep in progress["episodes"]:
            lines.append(
                f"  S{ep['season']:02d}E{ep['episode']:02d} "
                f"— {ep.get('title', 'Unknown')} [{ep['status']}]"
            )
        return "\n".join(lines)
    except Exception as error:
        logger.error("[HookReel] tool get_show_status failed: %s", error)
        return f"Get show status failed: {error}"


def _tool_list_tracked_shows() -> str:
    """List all TV shows currently being tracked in the database."""
    logger.info("[HookReel] tool list_tracked_shows called")
    try:
        shows = database.get_all_shows()
        if not shows:
            return "No TV shows are currently being tracked."
        lines = [f"Found {len(shows)} TV show(s) being tracked:"]
        for show in shows:
            episodes = database.get_episodes_for_show(show["id"])
            complete = sum(
                1 for e in episodes if e["status"] == "complete"
            )
            lines.append(
                f"  {show['title']} ({show['year']}) "
                f"| {complete}/{len(episodes)} episodes complete "
                f"| status: {show['status']} "
                f"| id: {show['id']}"
            )
        return "\n".join(lines)
    except Exception as error:
        logger.error("[HookReel] tool list_tracked_shows failed: %s", error)
        return f"List tracked shows failed: {error}"


def _tool_get_episode_list(provider_id: str, season: int = None) -> str:
    """Get the episode list for a show from the metadata provider."""
    logger.info(
        "[HookReel] tool get_episode_list: provider_id=%s season=%s",
        provider_id, season
    )
    try:
        from app.tv_metadata import get_episode_list
        episodes = get_episode_list(
            provider_id,
            season=int(season) if season is not None else None
        )
        if not episodes:
            return f"No episodes found for provider_id={provider_id}."
        lines = [f"Found {len(episodes)} episode(s):"]
        for ep in episodes:
            lines.append(
                f"  S{ep['season']:02d}E{ep['episode']:02d} "
                f"- {ep.get('title', 'Unknown')} "
                f"(aired: {ep.get('air_date', 'TBA')})"
            )
        return "\n".join(lines)
    except Exception as error:
        logger.error("[HookReel] tool get_episode_list failed: %s", error)
        return f"Get episode list failed: {error}"


def _tool_check_show_exists(title: str) -> str:
    """Check whether a TV show is already tracked in the database."""
    logger.info(
        "[HookReel] tool check_show_exists called: title=%s", title
    )
    try:
        matches = database.get_show_by_title(title)
        if not matches:
            return f"'{title}' is not currently tracked. Safe to request."
        lines = []
        for show in matches:
            episodes = database.get_episodes_for_show(show["id"])
            complete = sum(
                1 for e in episodes if e["status"] == "complete"
            )
            lines.append(
                f"'{show['title']}' is already tracked "
                f"(status: {show['status']}, "
                f"id: {show['id']}, "
                f"{complete}/{len(episodes)} episodes complete)."
            )
        return "\n".join(lines)
    except Exception as error:
        logger.error("[HookReel] tool check_show_exists failed: %s", error)
        return f"Check show exists failed: {error}"

# ---------------------------------------------------------------------------
# Library scan tool (Phase 8)
# ---------------------------------------------------------------------------

TOOL_SCHEMAS.append({
    "type": "function",
    "function": {
        "name": "scan_library",
        "description": (
            "Scan all media folders for new content added manually and add "
            "it to the HookReel library. Use this when the user says they "
            "have copied new files to their media folders, added a portable "
            "drive, or ripped a disc."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
})


def _tool_scan_library() -> str:
    """Run import_library.py --all-sources inside the container."""
    import subprocess
    logger.info("[HookReel] tool scan_library called")
    try:
        result = subprocess.run(
            ["python", "/hookreel/import_library.py", "--all-sources", "--enrich"],
            capture_output=True,
            text=True,
            timeout=300,
        )
        output = result.stdout.strip()
        if result.returncode != 0:
            logger.warning(
                "[HookReel] scan_library exited %d: %s",
                result.returncode, result.stderr
            )
        # Extract summary line from output
        for line in reversed(output.splitlines()):
            if "Movies added:" in line or "Done" in line:
                return "Library scan complete. {}".format(line)
        return "Library scan complete.\n{}".format(output[-500:] if len(output) > 500 else output)
    except subprocess.TimeoutExpired:
        return "Library scan timed out after 5 minutes. It may still be running."
    except Exception as exc:
        logger.error("[HookReel] _tool_scan_library error: %s", exc)
        return "Library scan failed: {}".format(exc)
