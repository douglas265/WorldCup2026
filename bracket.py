# -*- coding: utf-8 -*-
"""
bracket.py — Knockout bracket logic for WC2026.

Uses Flask-SQLAlchemy 3.x query API (db.session.execute / db.select).
All imports from app are deferred inside functions to avoid circular imports.
"""
import sys
from flask import current_app

def _db():
    # Always get db from the app currently handling the request,
    # avoiding the __main__ vs 'app' double-import problem.
    return current_app.extensions['sqlalchemy']

def _models():
    # Match/Team could live in '__main__' (python app.py) or 'app' (flask run)
    for mod_name in ('app', '__main__'):
        mod = sys.modules.get(mod_name)
        if mod and hasattr(mod, 'Match') and hasattr(mod, 'Team'):
            return mod.Match, mod.Team
    raise ImportError("Could not find Match/Team models in sys.modules")

# ---------------------------------------------------------------------------
# R32 source mapping
# ---------------------------------------------------------------------------
R32_SOURCES = {
    'R32-01': ('1A',   '2B'),
    'R32-02': ('1C',   '2D'),
    'R32-03': ('1B',   '2A'),
    'R32-04': ('1D',   '2C'),
    'R32-05': ('1E',   '2F'),
    'R32-06': ('1G',   '2H'),
    'R32-07': ('1F',   '2E'),
    'R32-08': ('1H',   '2G'),
    'R32-09': ('1I',   '2J'),
    'R32-10': ('1K',   '2L'),
    'R32-11': ('1J',   '2I'),
    'R32-12': ('1L',   '2K'),
    'R32-13': ('T3-1', 'T3-2'),
    'R32-14': ('T3-3', 'T3-4'),
    'R32-15': ('T3-5', 'T3-6'),
    'R32-16': ('T3-7', 'T3-8'),
}


# ---------------------------------------------------------------------------
# Group standings
# ---------------------------------------------------------------------------

def get_group_standings():
    db = _db()
    Match, Team = _models()

    teams = db.session.execute(db.select(Team)).scalars().all()
    stats = {t.id: {'team': t, 'pts': 0, 'gd': 0, 'gf': 0, 'ga': 0} for t in teams}

    completed = db.session.execute(
        db.select(Match)
        .where(Match.stage == 'Group Stage')
        .where(Match.result.isnot(None))
    ).scalars().all()

    for m in completed:
        if m.home_team_id not in stats or m.away_team_id not in stats:
            continue
        h = stats[m.home_team_id]
        a = stats[m.away_team_id]
        h['gf'] += m.home_score or 0
        h['ga'] += m.away_score or 0
        a['gf'] += m.away_score or 0
        a['ga'] += m.home_score or 0
        h['gd'] = h['gf'] - h['ga']
        a['gd'] = a['gf'] - a['ga']
        if m.result == 'home':
            h['pts'] += 3
        elif m.result == 'away':
            a['pts'] += 3
        else:
            h['pts'] += 1
            a['pts'] += 1

    by_group = {}
    for s in stats.values():
        g = s['team'].group
        if g:
            by_group.setdefault(g, []).append(s)

    for g in by_group:
        by_group[g].sort(key=lambda x: (x['pts'], x['gd'], x['gf']), reverse=True)

    return by_group


def _group_is_complete(group_letter, standings):
    db = _db()
    Match, _ = _models()

    team_ids = {s['team'].id for s in standings.get(group_letter, [])}
    if len(team_ids) < 4:
        return False
    intra = db.session.execute(
        db.select(Match)
        .where(Match.stage == 'Group Stage')
        .where(Match.home_team_id.in_(team_ids))
        .where(Match.away_team_id.in_(team_ids))
    ).scalars().all()
    played = sum(1 for m in intra if m.result is not None)
    return played >= 6


def _get_third_place_ranked(standings):
    third = []
    for g, ranked in standings.items():
        if len(ranked) >= 3 and _group_is_complete(g, standings):
            third.append(ranked[2])
    third.sort(key=lambda x: (x['pts'], x['gd'], x['gf']), reverse=True)
    return third


# ---------------------------------------------------------------------------
# Source code resolution
# ---------------------------------------------------------------------------

def _resolve_source(code, standings, third_place_ranked):
    if not code:
        return None

    if code.startswith('T3-'):
        idx = int(code[3:]) - 1
        if idx < len(third_place_ranked):
            return third_place_ranked[idx]['team']
        return None

    try:
        pos   = int(code[0]) - 1
        group = code[1]
    except (ValueError, IndexError):
        return None

    if not _group_is_complete(group, standings):
        return None

    ranked = standings.get(group, [])
    if len(ranked) <= pos:
        return None
    return ranked[pos]['team']


# ---------------------------------------------------------------------------
# Bracket advancement
# ---------------------------------------------------------------------------

def _seed_r32_from_groups():
    db = _db()
    Match, _ = _models()

    standings    = get_group_standings()
    third_ranked = _get_third_place_ranked(standings)

    changed = False
    for slot, (home_code, away_code) in R32_SOURCES.items():
        match = db.session.execute(
            db.select(Match).where(Match.bracket_slot == slot)
        ).scalar_one_or_none()
        if not match:
            continue

        if match.home_team_id is None:
            team = _resolve_source(home_code, standings, third_ranked)
            if team:
                match.home_team_id = team.id
                changed = True

        if match.away_team_id is None:
            team = _resolve_source(away_code, standings, third_ranked)
            if team:
                match.away_team_id = team.id
                changed = True

    return changed


def _advance_ko_winners():
    db = _db()
    Match, _ = _models()

    ko_stages = ['Round of 32', 'Round of 16', 'Quarter-Final', 'Semi-Final']
    completed = db.session.execute(
        db.select(Match)
        .where(Match.stage.in_(ko_stages))
        .where(Match.result.isnot(None))
        .where(Match.winner_next_slot.isnot(None))
    ).scalars().all()

    slot_index = {
        m.bracket_slot: m
        for m in db.session.execute(
            db.select(Match).where(Match.bracket_slot.isnot(None))
        ).scalars().all()
    }

    changed = False
    for match in completed:
        winner_id = (match.home_team_id if match.result == 'home'
                     else match.away_team_id)
        loser_id  = (match.away_team_id if match.result == 'home'
                     else match.home_team_id)

        if winner_id and match.winner_next_slot:
            next_m = slot_index.get(match.winner_next_slot)
            if next_m:
                if match.winner_next_pos == 'home' and next_m.home_team_id is None:
                    next_m.home_team_id = winner_id
                    changed = True
                elif match.winner_next_pos == 'away' and next_m.away_team_id is None:
                    next_m.away_team_id = winner_id
                    changed = True

        if loser_id and match.loser_next_slot:
            third_m = slot_index.get(match.loser_next_slot)
            if third_m:
                if match.loser_next_pos == 'home' and third_m.home_team_id is None:
                    third_m.home_team_id = loser_id
                    changed = True
                elif match.loser_next_pos == 'away' and third_m.away_team_id is None:
                    third_m.away_team_id = loser_id
                    changed = True

    return changed


def advance_bracket():
    db = _db()
    changed  = _seed_r32_from_groups()
    changed |= _advance_ko_winners()
    if changed:
        db.session.commit()
    return changed


# ---------------------------------------------------------------------------
# Template helper
# ---------------------------------------------------------------------------

def get_bracket_rounds():
    db = _db()
    Match, _ = _models()

    round_order = [
        ('Round of 32',   'Round of 32'),
        ('Round of 16',   'Round of 16'),
        ('Quarter-Final', 'Quarter-Final'),
        ('Semi-Final',    'Semi-Final'),
        ('3rd Place',     '3rd Place'),
        ('Final',         'Final'),
    ]
    result = []
    for label, stage in round_order:
        matches = db.session.execute(
            db.select(Match)
            .where(Match.stage == stage)
            .order_by(Match.bracket_slot)
        ).scalars().all()
        if matches:
            result.append({'label': label, 'matches': matches})
    return result
