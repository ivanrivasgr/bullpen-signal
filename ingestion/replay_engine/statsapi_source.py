"""Pull game-level metadata from MLB StatsAPI.

StatsAPI gives us: official lineups, pitching changes with wall-clock times,
substitutions, scoring plays. We use it to enrich the Statcast stream with
game-state events that Statcast does not carry.

This module is a thin wrapper with graceful degradation: if StatsAPI is
unreachable or a game is not yet final, we return an empty list rather than
raising, so the replay engine can still run on Statcast alone.
"""

from __future__ import annotations

import structlog

log = structlog.get_logger(__name__)


def load_pitching_changes(game_pk: int) -> list[dict]:
    """Return pitching-change events for `game_pk`.

    Each dict has: `inning`, `inning_topbot`, `incoming_pitcher_id`,
    `outgoing_pitcher_id`, `about_time` (ISO-8601 string).
    """
    try:
        import statsapi
    except ImportError:
        log.warning("statsapi not installed; skipping pitching changes")
        return []

    try:
        data = statsapi.get("game_playByPlay", {"gamePk": game_pk})
    except Exception as exc:
        log.warning("statsapi fetch failed", game_pk=game_pk, error=str(exc))
        return []

    changes: list[dict] = []
    all_plays = data.get("allPlays", [])
    for play in all_plays:
        for event in play.get("playEvents", []):
            details = event.get("details", {})
            if details.get("eventType") == "pitching_substitution":
                changes.append(
                    {
                        "inning": play.get("about", {}).get("inning"),
                        "inning_topbot": play.get("about", {}).get("halfInning", "").capitalize(),
                        "about_time": event.get("startTime"),
                        "incoming_pitcher_id": details.get("replacementPlayerId"),
                        "outgoing_pitcher_id": details.get("playerId"),
                    }
                )
    log.info("pitching changes loaded", game_pk=game_pk, count=len(changes))
    return changes


def load_lineups(game_pk: int) -> dict:
    """Return home and away batting orders as a dict of lists of player IDs."""
    try:
        import statsapi
    except ImportError:
        return {"home": [], "away": []}

    try:
        boxscore = statsapi.boxscore_data(game_pk)
    except Exception as exc:
        log.warning("statsapi boxscore failed", game_pk=game_pk, error=str(exc))
        return {"home": [], "away": []}

    return {
        "home": boxscore.get("home", {}).get("battingOrder", []),
        "away": boxscore.get("away", {}).get("battingOrder", []),
    }
