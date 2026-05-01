# -*- coding: utf-8 -*-
"""
Run once to seed the database with WC2026 teams, group stage matches,
and knockout bracket matches.

Usage:
  python init_db.py            # teams + matches only
  python init_db.py --admin    # also create an admin account

Team/group data from ESPN API + Wikipedia (2026 FIFA World Cup draw).
Match schedule from ESPN API (site.api.espn.com).
Flag codes are 2-letter ISO 3166-1 alpha-2 (flag-icons compatible).
"""
import sys
from app import app, db, User, Team, Match
from datetime import datetime

# 48 teams across 12 groups. flag_emoji stores 2-letter ISO code for flag images.
TEAMS = [
    # Group A
    ("Mexico",                "A", "mx"),
    ("South Africa",          "A", "za"),
    ("South Korea",           "A", "kr"),
    ("Czechia",               "A", "cz"),
    # Group B
    ("Canada",                "B", "ca"),
    ("Bosnia-Herzegovina",    "B", "ba"),
    ("Qatar",                 "B", "qa"),
    ("Switzerland",           "B", "ch"),
    # Group C
    ("Brazil",                "C", "br"),
    ("Morocco",               "C", "ma"),
    ("Haiti",                 "C", "ht"),
    ("Scotland",              "C", "gb-sct"),
    # Group D
    ("United States",         "D", "us"),
    ("Paraguay",              "D", "py"),
    ("Australia",             "D", "au"),
    ("Turkiye",               "D", "tr"),
    # Group E
    ("Germany",               "E", "de"),
    ("Curacao",               "E", "cw"),
    ("Ivory Coast",           "E", "ci"),
    ("Ecuador",               "E", "ec"),
    # Group F
    ("Netherlands",           "F", "nl"),
    ("Japan",                 "F", "jp"),
    ("Sweden",                "F", "se"),
    ("Tunisia",               "F", "tn"),
    # Group G
    ("Belgium",               "G", "be"),
    ("Egypt",                 "G", "eg"),
    ("Iran",                  "G", "ir"),
    ("New Zealand",           "G", "nz"),
    # Group H
    ("Spain",                 "H", "es"),
    ("Cape Verde",            "H", "cv"),
    ("Saudi Arabia",          "H", "sa"),
    ("Uruguay",               "H", "uy"),
    # Group I
    ("France",                "I", "fr"),
    ("Iraq",                  "I", "iq"),
    ("Norway",                "I", "no"),
    ("Senegal",               "I", "sn"),
    # Group J
    ("Algeria",               "J", "dz"),
    ("Argentina",             "J", "ar"),
    ("Austria",               "J", "at"),
    ("Jordan",                "J", "jo"),
    # Group K
    ("Colombia",              "K", "co"),
    ("DR Congo",              "K", "cd"),
    ("Portugal",              "K", "pt"),
    ("Uzbekistan",            "K", "uz"),
    # Group L
    ("Croatia",               "L", "hr"),
    ("England",               "L", "gb-eng"),
    ("Ghana",                 "L", "gh"),
    ("Panama",                "L", "pa"),
]

# All 72 group stage matches (3 matchdays × 24 matches).
# Schedule from ESPN API. A few MD1/MD2 times are estimated (~).
GROUP_MATCHES = [
    # ── Group A ──────────────────────────────────────────────────────────────
    # MD1
    ("Mexico",          "South Africa",      "2026-06-11 19:00", "Group Stage", "Estadio Banorte"),
    ("South Korea",     "Czechia",           "2026-06-12 02:00", "Group Stage", "Estadio Akron"),
    # MD2
    ("Czechia",         "South Africa",      "2026-06-18 16:00", "Group Stage", "Mercedes-Benz Stadium"),
    ("Mexico",          "South Korea",       "2026-06-19 01:00", "Group Stage", "Estadio Akron"),
    # MD3 (simultaneous)
    ("Czechia",         "Mexico",            "2026-06-25 01:00", "Group Stage", "Estadio Banorte"),
    ("South Africa",    "South Korea",       "2026-06-25 01:00", "Group Stage", "Estadio BBVA"),

    # ── Group B ──────────────────────────────────────────────────────────────
    # MD1
    ("Canada",          "Bosnia-Herzegovina","2026-06-12 19:00", "Group Stage", "BMO Field"),
    ("Qatar",           "Switzerland",       "2026-06-13 19:00", "Group Stage", "Levi's Stadium"),
    # MD2
    ("Switzerland",     "Bosnia-Herzegovina","2026-06-18 19:00", "Group Stage", "SoFi Stadium"),
    ("Canada",          "Qatar",             "2026-06-18 22:00", "Group Stage", "BC Place"),
    # MD3 (simultaneous)
    ("Bosnia-Herzegovina","Qatar",           "2026-06-24 19:00", "Group Stage", "Lumen Field"),
    ("Switzerland",     "Canada",            "2026-06-24 19:00", "Group Stage", "BC Place"),

    # ── Group C ──────────────────────────────────────────────────────────────
    # MD1
    ("Brazil",          "Morocco",           "2026-06-13 22:00", "Group Stage", "MetLife Stadium"),
    ("Haiti",           "Scotland",          "2026-06-14 01:00", "Group Stage", "Gillette Stadium"),
    # MD2
    ("Scotland",        "Morocco",           "2026-06-19 22:00", "Group Stage", "Gillette Stadium"),
    ("Brazil",          "Haiti",             "2026-06-20 00:30", "Group Stage", "Lincoln Financial Field"),
    # MD3 (simultaneous)
    ("Morocco",         "Haiti",             "2026-06-24 22:00", "Group Stage", "Mercedes-Benz Stadium"),
    ("Scotland",        "Brazil",            "2026-06-24 22:00", "Group Stage", "Hard Rock Stadium"),

    # ── Group D ──────────────────────────────────────────────────────────────
    # MD1
    ("United States",   "Paraguay",          "2026-06-13 01:00", "Group Stage", "SoFi Stadium"),
    ("Australia",       "Turkiye",           "2026-06-14 04:00", "Group Stage", "BC Place"),
    # MD2
    ("United States",   "Australia",         "2026-06-19 19:00", "Group Stage", "Lumen Field"),
    ("Turkiye",         "Paraguay",          "2026-06-20 03:00", "Group Stage", "Levi's Stadium"),
    # MD3 (simultaneous)
    ("Paraguay",        "Australia",         "2026-06-26 02:00", "Group Stage", "Levi's Stadium"),
    ("Turkiye",         "United States",     "2026-06-26 02:00", "Group Stage", "SoFi Stadium"),

    # ── Group E ──────────────────────────────────────────────────────────────
    # MD1
    ("Germany",         "Curacao",           "2026-06-14 17:00", "Group Stage", "NRG Stadium"),
    ("Ivory Coast",     "Ecuador",           "2026-06-14 23:00", "Group Stage", "Lincoln Financial Field"),
    # MD2
    ("Germany",         "Ivory Coast",       "2026-06-20 20:00", "Group Stage", "BMO Field"),
    ("Ecuador",         "Curacao",           "2026-06-21 00:00", "Group Stage", "GEHA Field at Arrowhead Stadium"),
    # MD3 (simultaneous)
    ("Curacao",         "Ivory Coast",       "2026-06-25 20:00", "Group Stage", "Lincoln Financial Field"),
    ("Ecuador",         "Germany",           "2026-06-25 20:00", "Group Stage", "MetLife Stadium"),

    # ── Group F ──────────────────────────────────────────────────────────────
    # MD1
    ("Netherlands",     "Japan",             "2026-06-14 20:00", "Group Stage", "AT&T Stadium"),
    ("Sweden",          "Tunisia",           "2026-06-15 02:00", "Group Stage", "Estadio BBVA"),   # ~estimated
    # MD2
    ("Netherlands",     "Sweden",            "2026-06-20 17:00", "Group Stage", "NRG Stadium"),
    ("Tunisia",         "Japan",             "2026-06-21 04:00", "Group Stage", "Estadio BBVA"),
    # MD3 (simultaneous)
    ("Japan",           "Sweden",            "2026-06-25 23:00", "Group Stage", "AT&T Stadium"),
    ("Tunisia",         "Netherlands",       "2026-06-25 23:00", "Group Stage", "GEHA Field at Arrowhead Stadium"),

    # ── Group G ──────────────────────────────────────────────────────────────
    # MD1
    ("Belgium",         "Egypt",             "2026-06-15 19:00", "Group Stage", "Lumen Field"),
    ("Iran",            "New Zealand",       "2026-06-16 01:00", "Group Stage", "SoFi Stadium"),
    # MD2
    ("Belgium",         "Iran",              "2026-06-21 19:00", "Group Stage", "SoFi Stadium"),
    ("New Zealand",     "Egypt",             "2026-06-22 01:00", "Group Stage", "BC Place"),
    # MD3 (simultaneous)
    ("Egypt",           "Iran",              "2026-06-27 03:00", "Group Stage", "Lumen Field"),
    ("New Zealand",     "Belgium",           "2026-06-27 03:00", "Group Stage", "BC Place"),

    # ── Group H ──────────────────────────────────────────────────────────────
    # MD1
    ("Spain",           "Cape Verde",        "2026-06-15 16:00", "Group Stage", "Mercedes-Benz Stadium"),
    ("Saudi Arabia",    "Uruguay",           "2026-06-15 22:00", "Group Stage", "Hard Rock Stadium"),
    # MD2
    ("Spain",           "Saudi Arabia",      "2026-06-21 16:00", "Group Stage", "Mercedes-Benz Stadium"),
    ("Uruguay",         "Cape Verde",        "2026-06-21 22:00", "Group Stage", "Hard Rock Stadium"),
    # MD3 (simultaneous)
    ("Cape Verde",      "Saudi Arabia",      "2026-06-27 00:00", "Group Stage", "NRG Stadium"),
    ("Uruguay",         "Spain",             "2026-06-27 00:00", "Group Stage", "Estadio Akron"),

    # ── Group I ──────────────────────────────────────────────────────────────
    # MD1
    ("France",          "Senegal",           "2026-06-16 19:00", "Group Stage", "MetLife Stadium"),
    ("Iraq",            "Norway",            "2026-06-16 22:00", "Group Stage", "Gillette Stadium"),
    # MD2
    ("France",          "Iraq",              "2026-06-22 21:00", "Group Stage", "Lincoln Financial Field"),
    ("Norway",          "Senegal",           "2026-06-23 00:00", "Group Stage", "MetLife Stadium"),
    # MD3 (simultaneous)
    ("Norway",          "France",            "2026-06-26 19:00", "Group Stage", "Gillette Stadium"),
    ("Senegal",         "Iraq",              "2026-06-26 19:00", "Group Stage", "BMO Field"),

    # ── Group J ──────────────────────────────────────────────────────────────
    # MD1
    ("Argentina",       "Algeria",           "2026-06-17 01:00", "Group Stage", "GEHA Field at Arrowhead Stadium"),
    ("Austria",         "Jordan",            "2026-06-17 04:00", "Group Stage", "Levi's Stadium"),
    # MD2
    ("Argentina",       "Austria",           "2026-06-22 17:00", "Group Stage", "AT&T Stadium"),
    ("Jordan",          "Algeria",           "2026-06-23 03:00", "Group Stage", "Levi's Stadium"),
    # MD3 (simultaneous)
    ("Algeria",         "Austria",           "2026-06-26 21:00", "Group Stage", "GEHA Field at Arrowhead Stadium"),  # ~estimated
    ("Argentina",       "Jordan",            "2026-06-26 21:00", "Group Stage", "Levi's Stadium"),                   # ~estimated

    # ── Group K ──────────────────────────────────────────────────────────────
    # MD1
    ("Portugal",        "DR Congo",          "2026-06-17 17:00", "Group Stage", "NRG Stadium"),
    ("Colombia",        "Uzbekistan",        "2026-06-18 01:00", "Group Stage", "Lincoln Financial Field"),  # ~estimated
    # MD2
    ("Portugal",        "Uzbekistan",        "2026-06-23 17:00", "Group Stage", "NRG Stadium"),
    ("Colombia",        "DR Congo",          "2026-06-24 00:00", "Group Stage", "Lincoln Financial Field"),  # ~estimated
    # MD3 (simultaneous)
    ("Colombia",        "Portugal",          "2026-06-27 23:30", "Group Stage", "Hard Rock Stadium"),
    ("DR Congo",        "Uzbekistan",        "2026-06-27 23:30", "Group Stage", "Mercedes-Benz Stadium"),

    # ── Group L ──────────────────────────────────────────────────────────────
    # MD1
    ("England",         "Croatia",           "2026-06-17 20:00", "Group Stage", "AT&T Stadium"),
    ("Ghana",           "Panama",            "2026-06-17 23:00", "Group Stage", "BMO Field"),
    # MD2
    ("England",         "Ghana",             "2026-06-23 20:00", "Group Stage", "Gillette Stadium"),
    ("Croatia",         "Panama",            "2026-06-24 04:00", "Group Stage", "BMO Field"),           # ~estimated
    # MD3 (simultaneous)
    ("Croatia",         "Ghana",             "2026-06-27 21:00", "Group Stage", "Lincoln Financial Field"),
    ("Panama",          "England",           "2026-06-27 21:00", "Group Stage", "MetLife Stadium"),
]

# ---------------------------------------------------------------------------
# Knockout matches
# Tuple format:
#   (bracket_slot, home_src, away_src,
#    winner_next_slot, winner_next_pos,
#    loser_next_slot, loser_next_pos,
#    date_str, stage, venue)
#
# home_src / away_src:
#   '1A'  = 1st place Group A
#   'T3-N'= Nth best 3rd-place qualifier
#   None  = filled automatically by bracket advancement
# ---------------------------------------------------------------------------
KNOCKOUT_MATCHES = [
    # -------- Round of 32 (Jun 28 – Jul 4) --------
    ("R32-01","1A",  "2B",  "R16-01","home",None,  None,  "2026-06-28 19:00","Round of 32","SoFi Stadium"),
    ("R32-02","1C",  "2D",  "R16-01","away",None,  None,  "2026-06-29 17:00","Round of 32","NRG Stadium"),
    ("R32-03","1B",  "2A",  "R16-02","home",None,  None,  "2026-06-29 20:30","Round of 32","Gillette Stadium"),
    ("R32-04","1D",  "2C",  "R16-02","away",None,  None,  "2026-06-30 01:00","Round of 32","Estadio BBVA"),
    ("R32-05","1E",  "2F",  "R16-03","home",None,  None,  "2026-06-30 17:00","Round of 32","AT&T Stadium"),
    ("R32-06","1G",  "2H",  "R16-03","away",None,  None,  "2026-06-30 21:00","Round of 32","MetLife Stadium"),
    ("R32-07","1F",  "2E",  "R16-04","home",None,  None,  "2026-07-01 01:00","Round of 32","Estadio Banorte"),
    ("R32-08","1H",  "2G",  "R16-04","away",None,  None,  "2026-07-01 16:00","Round of 32","Mercedes-Benz Stadium"),
    ("R32-09","1I",  "2J",  "R16-05","home",None,  None,  "2026-07-01 20:00","Round of 32","Lumen Field"),
    ("R32-10","1K",  "2L",  "R16-05","away",None,  None,  "2026-07-02 00:00","Round of 32","Levi's Stadium"),
    ("R32-11","1J",  "2I",  "R16-06","home",None,  None,  "2026-07-02 19:00","Round of 32","SoFi Stadium"),
    ("R32-12","1L",  "2K",  "R16-06","away",None,  None,  "2026-07-02 23:00","Round of 32","BMO Field"),
    ("R32-13","T3-1","T3-2","R16-07","home",None,  None,  "2026-07-03 03:00","Round of 32","BC Place"),
    ("R32-14","T3-3","T3-4","R16-07","away",None,  None,  "2026-07-03 18:00","Round of 32","AT&T Stadium"),
    ("R32-15","T3-5","T3-6","R16-08","home",None,  None,  "2026-07-03 22:00","Round of 32","Hard Rock Stadium"),
    ("R32-16","T3-7","T3-8","R16-08","away",None,  None,  "2026-07-04 01:30","Round of 32","GEHA Field at Arrowhead Stadium"),
    # -------- Round of 16 (Jul 4–6) --------
    ("R16-01",None,  None,  "QF-01","home",None,  None,  "2026-07-04 17:00","Round of 16","NRG Stadium"),
    ("R16-02",None,  None,  "QF-01","away",None,  None,  "2026-07-04 21:00","Round of 16","Lincoln Financial Field"),
    ("R16-03",None,  None,  "QF-02","home",None,  None,  "2026-07-05 17:00","Round of 16","MetLife Stadium"),
    ("R16-04",None,  None,  "QF-02","away",None,  None,  "2026-07-05 21:00","Round of 16","AT&T Stadium"),
    ("R16-05",None,  None,  "QF-03","home",None,  None,  "2026-07-06 17:00","Round of 16","SoFi Stadium"),
    ("R16-06",None,  None,  "QF-03","away",None,  None,  "2026-07-06 21:00","Round of 16","Hard Rock Stadium"),
    ("R16-07",None,  None,  "QF-04","home",None,  None,  "2026-07-07 17:00","Round of 16","Lumen Field"),
    ("R16-08",None,  None,  "QF-04","away",None,  None,  "2026-07-07 21:00","Round of 16","BC Place"),
    # -------- Quarter-Finals (Jul 9–10) --------
    ("QF-01", None,  None,  "SF-01","home",None,  None,  "2026-07-09 18:00","Quarter-Final","MetLife Stadium"),
    ("QF-02", None,  None,  "SF-01","away",None,  None,  "2026-07-09 22:00","Quarter-Final","AT&T Stadium"),
    ("QF-03", None,  None,  "SF-02","home",None,  None,  "2026-07-10 18:00","Quarter-Final","SoFi Stadium"),
    ("QF-04", None,  None,  "SF-02","away",None,  None,  "2026-07-10 22:00","Quarter-Final","Hard Rock Stadium"),
    # -------- Semi-Finals (Jul 14–15) --------
    ("SF-01", None,  None,  "FINAL","home","3RD","home","2026-07-14 22:00","Semi-Final","MetLife Stadium"),
    ("SF-02", None,  None,  "FINAL","away","3RD","away","2026-07-15 22:00","Semi-Final","AT&T Stadium"),
    # -------- 3rd Place (Jul 18) --------
    ("3RD",   None,  None,  None,   None,  None,  None,  "2026-07-18 17:00","3rd Place","Hard Rock Stadium"),
    # -------- Final (Jul 19) --------
    ("FINAL", None,  None,  None,   None,  None,  None,  "2026-07-19 17:00","Final","MetLife Stadium"),
]


def seed():
    with app.app_context():
        db.create_all()

        # ---- Seed teams ----
        team_map = {}
        for name, group, flag in TEAMS:
            existing = Team.query.filter_by(name=name).first()
            if not existing:
                t = Team(name=name, group=group, flag_emoji=flag)
                db.session.add(t)
                db.session.flush()
                team_map[name] = t
            else:
                # Update group and flag in case they changed
                existing.group = group
                existing.flag_emoji = flag
                team_map[name] = existing

        db.session.commit()
        for t in Team.query.all():
            team_map[t.name] = t

        print(f"Seeded/updated {len(team_map)} teams.")

        # ---- Seed group stage matches ----
        group_added = 0
        for home_name, away_name, date_str, stage, venue in GROUP_MATCHES:
            home = team_map.get(home_name)
            away = team_map.get(away_name)
            if not home or not away:
                print(f"  Skipping {home_name} vs {away_name} - team not found")
                continue
            exists = Match.query.filter_by(
                home_team_id=home.id, away_team_id=away.id
            ).first()
            if not exists:
                dt = datetime.strptime(date_str, '%Y-%m-%d %H:%M')
                m = Match(home_team_id=home.id, away_team_id=away.id,
                          match_date=dt, stage=stage, venue=venue)
                db.session.add(m)
                group_added += 1

        db.session.commit()
        print(f"Added {group_added} group stage matches (72 total across 12 groups).")

        # ---- Seed knockout matches ----
        ko_added = 0
        for row in KNOCKOUT_MATCHES:
            (slot, h_src, a_src, wn_slot, wn_pos,
             ln_slot, ln_pos, date_str, stage, venue) = row

            if Match.query.filter_by(bracket_slot=slot).first():
                continue

            dt = datetime.strptime(date_str, '%Y-%m-%d %H:%M')
            m = Match(
                home_team_id     = None,
                away_team_id     = None,
                match_date       = dt,
                stage            = stage,
                venue            = venue,
                bracket_slot     = slot,
                home_source      = h_src,
                away_source      = a_src,
                winner_next_slot = wn_slot,
                winner_next_pos  = wn_pos,
                loser_next_slot  = ln_slot,
                loser_next_pos   = ln_pos,
            )
            db.session.add(m)
            ko_added += 1

        db.session.commit()
        print(f"Added {ko_added} knockout matches "
              f"(R32: 16, R16: 8, QF: 4, SF: 2, 3rd: 1, Final: 1).")

        # ---- Optional admin account ----
        if '--admin' in sys.argv:
            uname = input("Admin username: ").strip()
            email = input("Admin email: ").strip()
            pwd   = input("Admin password: ").strip()
            if not User.query.filter_by(username=uname).first():
                admin = User(username=uname, email=email, is_admin=True)
                admin.set_password(pwd)
                db.session.add(admin)
                db.session.commit()
                print(f"Admin '{uname}' created.")
            else:
                print("Username already exists - skipping admin creation.")


if __name__ == '__main__':
    seed()
