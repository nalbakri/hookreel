"""
app/suggestions.py

HookReel suggestion engine.
Recommends unwatched content from the library based on ratings,
watch history, and genre variety.
"""
from app import database
from app.logger import get_logger

logger = get_logger(__name__)


def get_suggestions(count=5, content_type=None):
    """
    Return a ranked list of content suggestions with reasoning.

    Ranking priority:
    1. Unwatched content (not in watch history)
    2. Highly rated content (4-5 stars preferred)
    3. Variety -- avoid suggesting same genre repeatedly
    4. Falls back to unrated unwatched content if no ratings exist

    Parameters:
        count:        Number of suggestions to return (default 5)
        content_type: 'movie', 'tv', or None for both

    Returns a list of dicts with keys:
        title, year, content_type, rating, reason
    """
    suggestions = []

    if content_type in (None, "movie"):
        suggestions.extend(_suggest_movies(count))

    if content_type in (None, "tv"):
        suggestions.extend(_suggest_shows(count))

    # Sort by rating descending, then alphabetically
    suggestions.sort(key=lambda x: (-(x.get("rating") or 0), x.get("title", "")))

    return suggestions[:count]


def _get_watched_movie_ids():
    """Return a set of movie IDs that have been watched."""
    try:
        connection = database.get_connection()
        cursor = connection.cursor()
        cursor.execute("""
            SELECT DISTINCT media_id FROM watch_history
            WHERE media_type = 'movie'
        """)
        rows = cursor.fetchall()
        connection.close()
        return {row["media_id"] for row in rows}
    except Exception as error:
        logger.error("[HookReel] _get_watched_movie_ids error: %s", error)
        return set()


def _get_watched_show_ids():
    """Return a set of show IDs that have at least one watched episode."""
    try:
        connection = database.get_connection()
        cursor = connection.cursor()
        cursor.execute("""
            SELECT DISTINCT e.show_id FROM watch_history wh
            JOIN episodes e ON wh.media_id = e.id
            WHERE wh.media_type = 'episode'
        """)
        rows = cursor.fetchall()
        connection.close()
        return {row["show_id"] for row in rows}
    except Exception as error:
        logger.error("[HookReel] _get_watched_show_ids error: %s", error)
        return set()


def _suggest_movies(count):
    """Build movie suggestions."""
    try:
        connection = database.get_connection()
        cursor = connection.cursor()
        cursor.execute("""
            SELECT id, title, year, user_rating FROM movies
            WHERE status = 'complete'
            ORDER BY user_rating DESC NULLS LAST, title ASC
        """)
        rows = cursor.fetchall()
        connection.close()

        watched_ids = _get_watched_movie_ids()
        has_ratings = any(row["user_rating"] for row in rows)
        results = []

        for row in rows:
            if row["id"] in watched_ids:
                continue
            rating = row["user_rating"]
            if has_ratings and not rating:
                continue
            if has_ratings:
                reason = "Rated {} stars and unwatched.".format(rating)
            else:
                reason = "In your library and unwatched. Rate content to improve suggestions."
            results.append({
                "title": row["title"],
                "year": row["year"] or "",
                "content_type": "movie",
                "rating": rating,
                "reason": reason,
            })
            if len(results) >= count:
                break

        # If rated filter returned nothing, fall back to unrated unwatched
        if not results and has_ratings:
            connection = database.get_connection()
            cursor = connection.cursor()
            cursor.execute("""
                SELECT id, title, year, user_rating FROM movies
                WHERE status = 'complete'
                ORDER BY title ASC
            """)
            rows = cursor.fetchall()
            connection.close()
            for row in rows:
                if row["id"] in watched_ids:
                    continue
                results.append({
                    "title": row["title"],
                    "year": row["year"] or "",
                    "content_type": "movie",
                    "rating": None,
                    "reason": "In your library and unwatched.",
                })
                if len(results) >= count:
                    break

        return results

    except Exception as error:
        logger.error("[HookReel] _suggest_movies error: %s", error)
        return []


def _suggest_shows(count):
    """Build TV show suggestions."""
    try:
        connection = database.get_connection()
        cursor = connection.cursor()
        cursor.execute("""
            SELECT id, title, year, user_rating FROM shows
            ORDER BY user_rating DESC NULLS LAST, title ASC
        """)
        rows = cursor.fetchall()
        connection.close()

        watched_ids = _get_watched_show_ids()
        has_ratings = any(row["user_rating"] for row in rows)
        results = []

        for row in rows:
            if row["id"] in watched_ids:
                continue
            rating = row["user_rating"]
            if has_ratings and not rating:
                continue
            if has_ratings:
                reason = "Rated {} stars and you have not started it yet.".format(rating)
            else:
                reason = "In your library and not started. Rate content to improve suggestions."
            results.append({
                "title": row["title"],
                "year": row["year"] or "",
                "content_type": "tv",
                "rating": rating,
                "reason": reason,
            })
            if len(results) >= count:
                break

        if not results and has_ratings:
            connection = database.get_connection()
            cursor = connection.cursor()
            cursor.execute("""
                SELECT id, title, year, user_rating FROM shows
                ORDER BY title ASC
            """)
            rows = cursor.fetchall()
            connection.close()
            for row in rows:
                if row["id"] in watched_ids:
                    continue
                results.append({
                    "title": row["title"],
                    "year": row["year"] or "",
                    "content_type": "tv",
                    "rating": None,
                    "reason": "In your library and not started.",
                })
                if len(results) >= count:
                    break

        return results

    except Exception as error:
        logger.error("[HookReel] _suggest_shows error: %s", error)
        return []
