"""
HookReel TV pipeline.
Handles searching, requesting, and tracking TV show downloads.
Mirrors the movie pipeline structure for consistency.
"""
import app.database as database
import app.tv_metadata as tv_metadata
from app.prowlarr import search_releases
from app.qbittorrent import add_torrent
from app.pipeline import _validate_download_url, sanitise_title
from app.logger import get_logger
from app import config

logger = get_logger(__name__)


def search_tv_releases(
    query: str,
    season: int = None,
    episode: int = None
) -> list:
    """
    Search Prowlarr for TV releases using category 5000.
    Builds a smart query string based on season/episode provided.
    Parameters:
        query:   Show title to search for.
        season:  Season number (optional).
        episode: Episode number (optional, requires season).
    Returns:
        List of release dicts from Prowlarr.
    """
    if season is not None and episode is not None:
        season_str = f"S{season:02d}E{episode:02d}"
        search_query = f"{query} {season_str}"
    elif season is not None:
        season_str = f"S{season:02d}"
        search_query = f"{query} {season_str}"
    else:
        search_query = query

    logger.info(
        "[HookReel] TV Prowlarr search query=%s category=5000", search_query
    )
    try:
        releases = search_releases(search_query, category=5000)
        logger.info(
            "[HookReel] TV Prowlarr returned %d results", len(releases)
        )
        return releases
    except Exception as error:
        logger.error("[HookReel] search_tv_releases error: %s", error)
        return []


def pick_best_tv_release(
    releases: list,
    preferred_resolution: str = None,
    max_size_gb: float = None,
    is_season_pack: bool = False
) -> dict:
    """
    Pick the best TV release from a list of Prowlarr results.
    For season packs the size limit is higher (default 40 GB).
    For single episodes normal movie size limits apply.
    Prefers: correct resolution → higher seeders.
    Parameters:
        releases:            List of release dicts from Prowlarr.
        preferred_resolution: e.g. '1080p', '720p' (optional).
        max_size_gb:         Maximum size in GB (optional).
        is_season_pack:      True if downloading a full season.
    Returns:
        Best release dict, or None if no suitable release found.
    """
    if not releases:
        return None

    if preferred_resolution is None:
        preferred_resolution = getattr(config, "PREFERRED_RESOLUTION", "1080p")

    if max_size_gb is None:
        if is_season_pack:
            max_size_gb = 40.0
        else:
            max_size_gb = float(getattr(config, "MAX_TORRENT_SIZE_GB", 10))

    max_size_bytes = max_size_gb * 1024 ** 3

    candidates = []
    for release in releases:
        size = release.get("size") or 0
        if size > max_size_bytes:
            continue
        candidates.append(release)

    if not candidates:
        logger.warning(
            "[HookReel] pick_best_tv_release: no releases under %.1f GB",
            max_size_gb
        )
        return None

    resolution_matches = [
        r for r in candidates
        if preferred_resolution.lower() in (r.get("title") or "").lower()
    ]
    pool = resolution_matches if resolution_matches else candidates

    best = max(pool, key=lambda r: r.get("seeders") or 0)
    logger.info(
        "[HookReel] pick_best_tv_release selected: %s seeders=%s",
        best.get("title"), best.get("seeders")
    )
    return best


def request_show(
    title: str,
    season: int = None,
    episode: int = None,
    download_url: str = None,
    release_title: str = None
) -> dict:
    """
    Main entry point for TV show download requests.
    Behaviour:
      - If season and episode given: download that specific episode.
      - If season only: download full season pack.
      - If neither: default to season 1 (agent should confirm first).
    Fast path: if download_url is provided, skip Prowlarr search.
    Parameters:
        title:         Show title to search for.
        season:        Season number (optional).
        episode:       Episode number (optional).
        download_url:  Direct magnet or torrent URL (optional).
        release_title: Human-readable release name (optional).
    Returns:
        Dict with keys: success (bool), message (str),
        show_id (int), episode_ids (list).
    """
    title = sanitise_title(title)
    is_season_pack = (season is not None and episode is None)
    is_specific_episode = (season is not None and episode is not None)

    # --- Step 1: Look up show metadata ---
    logger.info(
        "[HookReel] request_show title=%s season=%s episode=%s",
        title, season, episode
    )
    shows = tv_metadata.get_show_info(title)
    if not shows:
        return {
            "success": False,
            "message": f"Could not find TV show '{title}' in metadata provider.",
            "show_id": None,
            "episode_ids": []
        }
    best_show = shows[0]
    provider_id = best_show["provider_id"]
    show_title = best_show["title"]
    show_year = best_show["year"]

    # --- Step 2: Add show to database if new ---
    existing = database.get_show_by_title(show_title)
    if existing:
        show_id = existing[0]["id"]
        logger.info(
            "[HookReel] Show already tracked: id=%d title=%s",
            show_id, show_title
        )
    else:
        show_id = database.add_show(provider_id, show_title, show_year)
        if show_id == -1:
            return {
                "success": False,
                "message": "Database error while adding show.",
                "show_id": None,
                "episode_ids": []
            }
        logger.info(
            "[HookReel] New show added: id=%d title=%s", show_id, show_title
        )

    # --- Step 3: Determine which episodes to add ---
    target_season = season if season is not None else 1
    episode_ids = []

    if is_specific_episode:
        if not database.episode_exists(show_id, target_season, episode):
            ep_list = tv_metadata.get_episode_list(
                provider_id, season=target_season
            )
            ep_data = next(
                (e for e in ep_list if e["episode"] == episode), None
            )
            ep_title = ep_data["title"] if ep_data else None
            air_date = ep_data["air_date"] if ep_data else None
            ep_id = database.add_episode(
                show_id, target_season, episode, ep_title, air_date
            )
            if ep_id != -1:
                episode_ids.append(ep_id)
        else:
            existing_ep = database.get_episode(
                show_id, target_season, episode
            )
            episode_ids.append(existing_ep["id"])
    else:
        ep_list = tv_metadata.get_episode_list(
            provider_id, season=target_season
        )
        for ep_data in ep_list:
            ep_num = ep_data["episode"]
            if not database.episode_exists(
                show_id, target_season, ep_num
            ):
                ep_id = database.add_episode(
                    show_id,
                    target_season,
                    ep_num,
                    ep_data["title"],
                    ep_data["air_date"]
                )
                if ep_id != -1:
                    episode_ids.append(ep_id)
            else:
                existing_ep = database.get_episode(
                    show_id, target_season, ep_num
                )
                episode_ids.append(existing_ep["id"])

    # --- Step 4: Resolve download URL ---
    if download_url:
        if not _validate_download_url(download_url):
            return {
                "success": False,
                "message": "Invalid download URL format.",
                "show_id": show_id,
                "episode_ids": episode_ids
            }
        torrent_url = download_url
        chosen_title = release_title or title
        logger.info(
            "[HookReel] Using provided download_url for %s", chosen_title
        )
    else:
        # --- Step 5: Search Prowlarr ---
        releases = search_tv_releases(title, season=target_season,
                                      episode=episode)
        best_release = pick_best_tv_release(
            releases,
            is_season_pack=is_season_pack
        )
        if not best_release:
            for ep_id in episode_ids:
                database.update_episode_status(ep_id, "failed")
            return {
                "success": False,
                "message": (
                    f"No suitable release found for '{title}' "
                    f"S{target_season:02d}"
                    + (f"E{episode:02d}" if episode else "")
                    + ". Try providing a direct download URL."
                ),
                "show_id": show_id,
                "episode_ids": episode_ids
            }
        torrent_url = best_release.get("downloadUrl") or best_release.get(
            "magnetUrl"
        )
        chosen_title = best_release.get("title", title)

    # --- Step 6: Add to qBittorrent ---
    logger.info(
        "[HookReel] Adding to qBittorrent: %s", chosen_title
    )
    torrent_hash = add_torrent(torrent_url, save_path=config.DOWNLOADS_PATH)

    # --- Step 7: Update episode statuses ---
    new_status = "downloading" if torrent_hash else "searching"
    for ep_id in episode_ids:
        database.update_episode_status(
            ep_id,
            new_status,
            torrent_hash=torrent_hash or "",
            download_url=torrent_url
        )

    season_label = f"S{target_season:02d}"
    if episode:
        season_label += f"E{episode:02d}"

    return {
        "success": True,
        "message": (
            f"Requested '{show_title}' {season_label}. "
            f"Status: {new_status}."
        ),
        "show_id": show_id,
        "episode_ids": episode_ids
    }


def get_show_download_progress(
    show_id: int,
    season: int = None
) -> dict:
    """
    Return download progress for all episodes in a show or season.
    Parameters:
        show_id: Database show ID.
        season:  If provided, filter to this season only.
    Returns:
        Dict with show info and list of episode status dicts.
    """
    show = database.get_show(show_id)
    if not show:
        return {"error": f"Show id={show_id} not found"}

    all_episodes = database.get_episodes_for_show(show_id)
    if season is not None:
        all_episodes = [e for e in all_episodes if e["season"] == season]

    status_counts = {}
    for ep in all_episodes:
        st = ep["status"]
        status_counts[st] = status_counts.get(st, 0) + 1

    return {
        "show_id": show_id,
        "title": show["title"],
        "year": show["year"],
        "show_status": show["status"],
        "season_filter": season,
        "episode_count": len(all_episodes),
        "status_counts": status_counts,
        "episodes": all_episodes
    }
