"""NBA scores and standings service using nba_api."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from nba_api.stats.endpoints import LeagueStandings, ScoreboardV2

logger = logging.getLogger(__name__)


@dataclass
class GameResult:
    """A single game's result."""

    away_team: str
    away_score: int
    home_team: str
    home_score: int
    status: str  # e.g. "Final", "Final/OT"


@dataclass
class StandingsEntry:
    """A team's standings entry."""

    rank: int
    team: str
    wins: int
    losses: int
    pct: float
    games_back: str


@dataclass
class NbaStatsData:
    """Container for NBA stats data."""

    games: list[GameResult]
    east_standings: list[StandingsEntry]
    west_standings: list[StandingsEntry]
    scores_date: str  # e.g. "Feb 13"


class NbaStatsService:
    """Fetches NBA scores and standings from the official NBA.com API."""

    def fetch_yesterday_scores(self) -> list[GameResult]:
        """Fetch yesterday's game results."""
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        date_str = yesterday.strftime("%Y-%m-%d")

        try:
            scoreboard = ScoreboardV2(game_date=date_str)
            data = scoreboard.get_dict()
        except Exception as e:
            logger.error(f"Failed to fetch NBA scores: {type(e).__name__}: {e}")
            return []

        games: list[GameResult] = []
        result_sets = data.get("resultSets", [])

        # Find the LineScore result set — contains per-team rows
        line_score = None
        game_header = None
        for rs in result_sets:
            if rs.get("name") == "LineScore":
                line_score = rs
            elif rs.get("name") == "GameHeader":
                game_header = rs

        if not line_score:
            return games

        headers = line_score.get("headers", [])
        rows = line_score.get("rowSet", [])

        if not rows:
            return games

        try:
            team_abbr_idx = headers.index("TEAM_ABBREVIATION")
            pts_idx = headers.index("PTS")
        except ValueError:
            logger.error(f"Unexpected LineScore headers: {headers}")
            return games

        # Build game status lookup from GameHeader
        game_status: dict[str, str] = {}
        if game_header:
            gh_headers = game_header.get("headers", [])
            gh_rows = game_header.get("rowSet", [])
            try:
                gid_idx = gh_headers.index("GAME_ID")
                status_idx = gh_headers.index("GAME_STATUS_TEXT")
                for row in gh_rows:
                    game_status[row[gid_idx]] = row[status_idx].strip()
            except (ValueError, IndexError):
                pass

        game_id_idx = headers.index("GAME_ID")

        # LineScore has 2 rows per game (visitor, home) ordered by GAME_ID
        i = 0
        while i + 1 < len(rows):
            visitor = rows[i]
            home = rows[i + 1]

            # Skip games that haven't finished (PTS is None)
            if visitor[pts_idx] is None or home[pts_idx] is None:
                i += 2
                continue

            gid = visitor[game_id_idx]
            status = game_status.get(gid, "Final")

            games.append(
                GameResult(
                    away_team=visitor[team_abbr_idx],
                    away_score=int(visitor[pts_idx]),
                    home_team=home[team_abbr_idx],
                    home_score=int(home[pts_idx]),
                    status=status,
                )
            )
            i += 2

        return games

    def fetch_standings(self) -> tuple[list[StandingsEntry], list[StandingsEntry]]:
        """Fetch current conference standings. Returns (east, west)."""
        try:
            standings = LeagueStandings(league_id="00", season_type="Regular Season")
            data = standings.get_dict()
        except Exception as e:
            logger.error(f"Failed to fetch NBA standings: {type(e).__name__}: {e}")
            return [], []

        result_sets = data.get("resultSets", [])
        if not result_sets:
            return [], []

        rs = result_sets[0]
        headers = rs.get("headers", [])
        rows = rs.get("rowSet", [])

        try:
            conf_idx = headers.index("Conference")
            team_idx = headers.index("TeamCity")
            name_idx = headers.index("TeamName")
            wins_idx = headers.index("WINS")
            losses_idx = headers.index("LOSSES")
            pct_idx = headers.index("WinPCT")
            rank_idx = headers.index("PlayoffRank")
            gb_idx = headers.index("ConferenceGamesBack")
        except ValueError as e:
            logger.error(f"Unexpected standings headers: {e}")
            return [], []

        east: list[StandingsEntry] = []
        west: list[StandingsEntry] = []

        for row in rows:
            entry = StandingsEntry(
                rank=int(row[rank_idx]),
                team=f"{row[team_idx]} {row[name_idx]}",
                wins=int(row[wins_idx]),
                losses=int(row[losses_idx]),
                pct=float(row[pct_idx]),
                games_back=str(row[gb_idx]),
            )
            if row[conf_idx] == "East":
                east.append(entry)
            else:
                west.append(entry)

        # Sort by rank, limit to top 10
        east.sort(key=lambda e: e.rank)
        west.sort(key=lambda e: e.rank)

        return east[:10], west[:10]

    def fetch_all(self) -> NbaStatsData | None:
        """Fetch scores and standings. Returns None if no data available."""
        games = self.fetch_yesterday_scores()
        east, west = self.fetch_standings()

        if not games and not east:
            logger.info("No NBA data available (off-season or no games yesterday)")
            return None

        yesterday = datetime.now(timezone.utc) - timedelta(days=1)

        return NbaStatsData(
            games=games,
            east_standings=east,
            west_standings=west,
            scores_date=yesterday.strftime("%b %d"),
        )


def render_nba_stats_html(stats: NbaStatsData) -> str:
    """Render NBA scores and standings as inline-styled HTML for email."""
    parts: list[str] = []

    # Scores table
    if stats.games:
        parts.append(
            f'<p style="margin: 0 0 8px 0; font-family: Calibri, \'Segoe UI\', Arial, sans-serif; '
            f'font-size: 13px; font-weight: bold; color: #666666; text-transform: uppercase; letter-spacing: 0.5px;">'
            f"Scores &mdash; {stats.scores_date}</p>"
        )
        parts.append(
            '<table role="presentation" width="100%" cellpadding="5" cellspacing="0" '
            'style="font-family: Calibri, \'Segoe UI\', Arial, sans-serif; font-size: 14px; '
            'border-collapse: collapse; margin-bottom: 16px;">'
        )
        for game in stats.games:
            away_bold = "font-weight: bold;" if game.away_score > game.home_score else ""
            home_bold = "font-weight: bold;" if game.home_score > game.away_score else ""
            parts.append(
                f"<tr>"
                f'<td style="border-bottom: 1px solid #f0f0f0; color: #333333; {away_bold} width: 35%;">{game.away_team} {game.away_score}</td>'
                f'<td style="border-bottom: 1px solid #f0f0f0; color: #999999; width: 10%; text-align: center;">@</td>'
                f'<td style="border-bottom: 1px solid #f0f0f0; color: #333333; {home_bold} width: 35%;">{game.home_team} {game.home_score}</td>'
                f'<td style="border-bottom: 1px solid #f0f0f0; color: #999999; width: 20%; text-align: right; font-size: 12px;">{game.status}</td>'
                f"</tr>"
            )
        parts.append("</table>")

    # Standings — East and West side by side
    if stats.east_standings or stats.west_standings:
        parts.append(
            '<p style="margin: 0 0 8px 0; font-family: Calibri, \'Segoe UI\', Arial, sans-serif; '
            'font-size: 13px; font-weight: bold; color: #666666; text-transform: uppercase; letter-spacing: 0.5px;">'
            "Conference Standings</p>"
        )
        parts.append(
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            'style="margin-bottom: 16px;"><tr>'
        )

        for conf_name, entries in [("East", stats.east_standings), ("West", stats.west_standings)]:
            parts.append(
                '<td style="width: 50%; vertical-align: top; padding-right: 8px;" valign="top">'
            )
            parts.append(
                f'<table role="presentation" width="100%" cellpadding="3" cellspacing="0" '
                f'style="font-family: Calibri, \'Segoe UI\', Arial, sans-serif; font-size: 12px; border-collapse: collapse;">'
            )
            parts.append(
                f'<tr style="background-color: #f8f9fa;">'
                f'<td colspan="3" style="font-weight: bold; color: #0066cc; font-size: 12px; padding: 4px 3px; border-bottom: 1px solid #e0e0e0;">{conf_name}</td>'
                f"</tr>"
                f'<tr style="background-color: #f8f9fa;">'
                f'<td style="font-weight: bold; color: #999999; font-size: 11px; border-bottom: 1px solid #e0e0e0;">Team</td>'
                f'<td style="font-weight: bold; color: #999999; font-size: 11px; border-bottom: 1px solid #e0e0e0; text-align: center;">W-L</td>'
                f'<td style="font-weight: bold; color: #999999; font-size: 11px; border-bottom: 1px solid #e0e0e0; text-align: right;">GB</td>'
                f"</tr>"
            )
            for entry in entries:
                # Abbreviate team name: just use last word (team name without city)
                short_name = entry.team.split()[-1] if entry.team else entry.team
                gb_display = "-" if entry.games_back == "0.0" or entry.games_back == "0" else entry.games_back
                parts.append(
                    f"<tr>"
                    f'<td style="border-bottom: 1px solid #f0f0f0; color: #333333; font-size: 12px; white-space: nowrap;">'
                    f"{entry.rank}. {short_name}</td>"
                    f'<td style="border-bottom: 1px solid #f0f0f0; color: #666666; font-size: 12px; text-align: center;">'
                    f"{entry.wins}-{entry.losses}</td>"
                    f'<td style="border-bottom: 1px solid #f0f0f0; color: #999999; font-size: 12px; text-align: right;">'
                    f"{gb_display}</td>"
                    f"</tr>"
                )
            parts.append("</table></td>")

        parts.append("</tr></table>")

    return "\n".join(parts)


def render_nba_stats_text(stats: NbaStatsData) -> str:
    """Render NBA scores and standings as plain text."""
    lines: list[str] = []

    if stats.games:
        lines.append(f"SCORES — {stats.scores_date}")
        for game in stats.games:
            away_marker = "*" if game.away_score > game.home_score else " "
            home_marker = "*" if game.home_score > game.away_score else " "
            lines.append(
                f"  {away_marker}{game.away_team} {game.away_score}  @  {home_marker}{game.home_team} {game.home_score}  ({game.status})"
            )
        lines.append("")

    if stats.east_standings or stats.west_standings:
        lines.append("CONFERENCE STANDINGS")
        for conf_name, entries in [("East", stats.east_standings), ("West", stats.west_standings)]:
            lines.append(f"  {conf_name}:")
            for entry in entries:
                short_name = entry.team.split()[-1] if entry.team else entry.team
                gb_display = "-" if entry.games_back in ("0.0", "0") else entry.games_back
                lines.append(
                    f"    {entry.rank:>2}. {short_name:<14} {entry.wins:>2}-{entry.losses:<2}  GB: {gb_display}"
                )
        lines.append("")

    return "\n".join(lines)
