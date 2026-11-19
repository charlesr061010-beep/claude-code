#!/usr/bin/env python3
"""
Independent audit of Moonshot's answer bank (data/moonshot-data.js).

Recomputes every prompt's full answer set straight from the raw Lahman
tables, with code written separately from tools/build_data.py, and checks
every player record (identity, career span, position, franchise stints,
Jr./Sr. suffixes, nicknames) and every prompt's on-screen text. Only the
hand-written content lists (word lists, first-name groups, the birth-city
neighborhoods) are shared with the builder; all logic is restated here from
what each prompt says on screen.

    python tools/verify_bank.py            # pylahman's bundled data
    python tools/verify_bank.py --data DIR

Prints every difference and exits 1 if there is any.
"""
import argparse
import json
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
LAST_YEAR = 2025

# MLB-recognized major leagues (lgID). The 1871-75 NA (null lgID) and pre-1920
# independent clubs are not major leagues.
LEAGUES = {"NL", "AL", "AA", "UA", "PL", "FL", "NNL", "ECL", "ANL", "NSL", "EWL", "NN2", "NAL"}
POS = ["G_p", "G_c", "G_1b", "G_2b", "G_3b", "G_ss", "G_lf", "G_cf", "G_rf", "G_of", "G_dh"]

NICK = {
    "ANA": "Angels", "ARI": "Diamondbacks", "ATL": "Braves", "BAL": "Orioles", "BOS": "Red Sox", "CHC": "Cubs",
    "CHW": "White Sox", "CIN": "Reds", "CLE": "Guardians", "COL": "Rockies", "DET": "Tigers", "FLA": "Marlins",
    "HOU": "Astros", "KCR": "Royals", "LAD": "Dodgers", "MIL": "Brewers", "MIN": "Twins", "NYM": "Mets",
    "NYY": "Yankees", "OAK": "Athletics", "PHI": "Phillies", "PIT": "Pirates", "SDP": "Padres", "SEA": "Mariners",
    "SFG": "Giants", "STL": "Cardinals", "TBD": "Rays", "TEX": "Rangers", "TOR": "Blue Jays", "WSN": "Nationals",
}
ERAS = {  # slug -> (franchise, first year, last year)
    "brooklyn-dodgers": ("LAD", 1884, 1957), "new-york-giants": ("SFG", 1883, 1957),
    "montreal-expos": ("WSN", 1969, 2004), "st-louis-browns": ("BAL", 1902, 1953),
    "philadelphia-athletics": ("OAK", 1901, 1954), "kansas-city-athletics": ("OAK", 1955, 1967),
    "oakland-athletics": ("OAK", 1968, 2024), "boston-braves": ("ATL", 1876, 1952),
    "milwaukee-braves": ("ATL", 1953, 1965), "washington-senators-1901-60": ("MIN", 1901, 1960),
    "washington-senators-1961-71": ("TEX", 1961, 1971), "seattle-pilots": ("MIL", 1969, 1969),
    "houston-colt-45s": ("HOU", 1962, 1964), "florida-marlins": ("FLA", 1993, 2011),
    "tampa-bay-devil-rays": ("TBD", 1998, 2007), "california-angels": ("ANA", 1965, 1996),
    "new-york-highlanders": ("NYY", 1903, 1912), "cleveland-indians": ("CLE", 1915, 2021),
}
STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "DC": "Washington, D.C.", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts",
    "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York State", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington State",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}
COUNTRY = {"dr": "D.R.", "venezuela": "Venezuela", "cuba": "Cuba", "pr": "P.R.", "can": "CAN", "mexico": "México",
           "japan": "Japan", "panama": "Panama", "curacao": "Curaçao", "colombia": "Colombia"}
SUFFIX_EXPECTED = {  # (base name, MLB debut year) -> suffix shown in the game
    ("Ken Griffey", 1989): "Jr.", ("Ken Griffey", 1973): "Sr.", ("Vladimir Guerrero", 2019): "Jr.",
    ("Fernando Tatis", 2019): "Jr.", ("Fernando Tatis", 1997): "Sr.", ("Bobby Witt", 2022): "Jr.",
    ("Bobby Witt", 1986): "Sr.", ("Cal Ripken", 1981): "Jr.", ("Ronald Acuña", 2018): "Jr.",
    ("Lance McCullers", 2015): "Jr.", ("Lance McCullers", 1985): "Sr.", ("Jackie Bradley", 2013): "Jr.",
    ("Lourdes Gurriel", 2018): "Jr.", ("Jazz Chisholm", 2020): "Jr.", ("Luis Robert", 2020): "Jr.",
    ("Sandy Alomar", 1988): "Jr.", ("Sandy Alomar", 1964): "Sr.", ("Pete Rose", 1997): "Jr.",
    ("Tim Raines", 2001): "Jr.", ("Michael Harris", 2022): "II", ("Jose Cruz", 1997): "Jr.",
    ("Tony Gwynn", 2006): "Jr.", ("Gary Matthews", 1999): "Jr.", ("Gary Matthews", 1972): "Sr.",
    ("Eric Young", 2009): "Jr.", ("Eric Young", 1992): "Sr.", ("Delino DeShields", 2015): "Jr.",
    ("Delino DeShields", 1990): "Sr.",
}
ALIAS_EXPECTED = {  # nickname -> (base name, MLB debut year) of the player it must point to
    "Big Papi": ("David Ortiz", 1997), "Pudge Rodriguez": ("Ivan Rodriguez", 1991), "Pudge": ("Ivan Rodriguez", 1991),
    "A-Rod": ("Alex Rodriguez", 1994), "Goose Gossage": ("Rich Gossage", 1972), "Goose": ("Rich Gossage", 1972),
    "El Duque": ("Orlando Hernandez", 1998), "Mr. October": ("Reggie Jackson", 1967), "The Bambino": ("Babe Ruth", 1914),
    "Say Hey Kid": ("Willie Mays", 1951), "Big Hurt": ("Frank Thomas", 1990), "Junior Griffey": ("Ken Griffey", 1989),
    "Yaz": ("Carl Yastrzemski", 1961), "Donnie Baseball": ("Don Mattingly", 1982), "Doc Gooden": ("Dwight Gooden", 1984),
    "Mr. Cub": ("Ernie Banks", 1953), "Charlie Hustle": ("Pete Rose", 1963), "Big Unit": ("Randy Johnson", 1988),
    "The Rocket": ("Roger Clemens", 1984), "Mr. Padre": ("Tony Gwynn", 1982), "Iron Horse": ("Lou Gehrig", 1923),
    "Georgia Peach": ("Ty Cobb", 1905), "Big Train": ("Walter Johnson", 1907), "King Felix": ("Felix Hernandez", 2005),
    "Kung Fu Panda": ("Pablo Sandoval", 2008), "Prime Time": ("Deion Sanders", 1989), "Pudge Fisk": ("Carlton Fisk", 1969),
    "Hawk Harrelson": ("Ken Harrelson", 1963), "The Hawk": ("Andre Dawson", 1976), "Big Puma": ("Lance Berkman", 1999),
    "Joey Bats": ("Jose Bautista", 2004), "Vlad Jr.": ("Vladimir Guerrero", 2019), "Vlad Guerrero": ("Vladimir Guerrero", 1996),
    "Fausto Carmona": ("Roberto Hernandez", 2006), "Godzilla": ("Hideki Matsui", 2003), "Mike Stanton": ("Giancarlo Stanton", 2010),
}


def fold(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c))


def era_hund(er, ip_outs):
    """ERA in hundredths as the record books print it (half up), exact integer math."""
    return (5400 * er + ip_outs) // (2 * ip_outs) if ip_outs else 10 ** 9


def avg_thou(h, ab):
    """Batting average in thousandths as printed (half up)."""
    return (2000 * h + ab) // (2 * ab) if ab else -1


class Raw:
    def __init__(self, d):
        import pyarrow.parquet as pq
        self.t = lambda n: pq.read_table(os.path.join(d, n + ".parquet")).to_pylist()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data")
    args = ap.parse_args()
    d = args.data
    if not d:
        import importlib.util
        spec = importlib.util.find_spec("pylahman")
        if not spec:
            sys.exit("pip install pylahman pyarrow, or pass --data")
        d = os.path.join(os.path.dirname(spec.origin), "data")
    raw = Raw(d)

    text = open(os.path.join(ROOT, "data", "moonshot-data.js"), encoding="utf-8").read()
    M = json.loads(text[text.index("=") + 1:text.rindex(";")])
    IDS = json.load(open(os.path.join(ROOT, "data", "player-ids.json")))
    B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    BI = {c: i for i, c in enumerate(B64)}

    problems = []
    app_js = open(os.path.join(ROOT, "assets", "app.js"), encoding="utf-8").read()
    cat_block = app_js[app_js.index("var CAT_LABEL"):app_js.index("};", app_js.index("var CAT_LABEL"))]
    APP_CATEGORIES = set(re.findall(r"'?([a-z-]+)'?\s*:", cat_block))

    def bad(msg):
        problems.append(msg)

    # ------------------------------------------------------------------ raw data
    people = {r["playerID"]: r for r in raw.t("People")}
    teams = raw.t("Teams")
    tinfo = {}
    for t in teams:
        tinfo[(t["yearID"], t["teamID"])] = t
    fr_of = lambda y, tid: tinfo[(y, tid)]["franchID"] if (y, tid) in tinfo else None
    tG = lambda y, tid: (tinfo.get((y, tid)) or {}).get("G") or 0
    modern = lambda t: t["lgID"] in ("AL", "NL") and t["yearID"] >= 1903
    ws_team = {k for k, t in tinfo.items() if t["WSWin"] == "Y" and modern(t)}
    pen_team = {k for k, t in tinfo.items() if t["LgWin"] == "Y" and t["lgID"] in ("AL", "NL")}

    rows_app = defaultdict(list)        # pid -> qualifying Appearances rows
    for a in raw.t("Appearances"):
        if a["lgID"] not in LEAGUES:
            continue
        if (a["G_all"] or 0) > 0 or any((a[c] or 0) > 0 for c in POS):
            rows_app[a["playerID"]].append(a)
    players = set(rows_app)

    def nz(x):
        return x or 0

    bat = defaultdict(list)
    for b in raw.t("Batting"):
        if b["lgID"] in LEAGUES:
            bat[b["playerID"]].append(b)
    pit = defaultdict(list)
    for r in raw.t("Pitching"):
        if r["lgID"] in LEAGUES:
            pit[r["playerID"]].append(r)
    ipo = lambda r: nz(r.get("IPouts", r.get("IPOuts")))

    # -------------------------------------------------- player-level facts
    info = {}
    for pid in players:
        rows = rows_app[pid]
        years = {a["yearID"] for a in rows}
        frg, fry, frpos, pos = Counter(), defaultdict(set), defaultdict(Counter), Counter()
        ty, ymain = set(), defaultdict(Counter)
        for a in rows:
            f = fr_of(a["yearID"], a["teamID"])
            frg[f] += nz(a["G_all"])
            fry[f].add(a["yearID"])
            ty.add((a["yearID"], a["teamID"]))
            ymain[a["yearID"]][f] += nz(a["G_all"])
            for c in POS:
                pos[c] += nz(a[c])
                frpos[f][c] += nz(a[c])
        pp = people[pid]
        deb = pp["debut"].year if pp.get("debut") else None
        B = Counter()
        for b in bat[pid]:
            for c in ("AB", "H", "HR", "RBI", "SB", "R", "2B", "3B", "BB", "HBP", "SH", "SF", "G"):
                B[c] += nz(b[c])
        B["PA"] = B["AB"] + B["BB"] + B["HBP"] + B["SH"] + B["SF"]
        Pt = Counter()
        for r in pit[pid]:
            for c in ("W", "SV", "SO", "G", "ER", "SHO"):
                Pt[c] += nz(r[c])
            Pt["IPouts"] += ipo(r)
        info[pid] = dict(years=years, frg=frg, fry=fry, frpos=frpos, pos=pos, teams=ty, ymain=ymain,
                         y0=min(years), y1=max(years), G=sum(nz(a["G_all"]) for a in rows), deb=deb,
                         bat=B, pit=Pt, pp=pp)

    # ---------------------------------------------------------- player table
    if len(IDS) != len(M["players"]) or len(M["spans"]) != len(M["players"]):
        bad("player-ids.json / spans / players lengths differ")
    if len(set(IDS)) != len(IDS):
        bad("duplicate player ids in the player table")
    if set(IDS) != players:
        bad(f"player table vs Lahman: missing {sorted(players - set(IDS))[:10]}, extra {sorted(set(IDS) - players)[:10]}")
    idx = {pid: i for i, pid in enumerate(IDS)}
    FR = [f for f, _ in M["franchises"]]
    if FR != list(NICK) or any(NICK[f] != n for f, n in M["franchises"]):
        bad("franchise table differs from the 30 current clubs")

    def base_name(pid):
        pp = people[pid]
        first, last = (pp["nameFirst"] or "").strip(), (pp["nameLast"] or "").strip()
        return f"{first} {last}".strip() if first else f"{last} (first name unknown)"

    suffix_hits = Counter()
    for pid in players:
        i = idx.get(pid)
        if i is None:
            continue
        name, y0, y1, poslab = M["players"][i]
        nf = info[pid]
        exp = base_name(pid)
        key = (exp, nf["deb"])
        if key in SUFFIX_EXPECTED:
            exp = f"{exp} {SUFFIX_EXPECTED[key]}"
            suffix_hits[key] += 1
        if name != exp:
            bad(f"player {pid}: name {name!r}, expected {exp!r}")
        if (y0, y1) != (nf["y0"], nf["y1"]):
            bad(f"player {pid} {name}: years {y0}-{y1}, expected {nf['y0']}-{nf['y1']}")
        # primary position: most games among the specific spots (OF only if no split exists)
        spots = Counter({c: v for c, v in nf["pos"].items() if c != "G_of" and v > 0})
        if not spots and nf["pos"]["G_of"]:
            spots = Counter({"G_of": nf["pos"]["G_of"]})
        lab = {"G_p": "P", "G_c": "C", "G_1b": "1B", "G_2b": "2B", "G_3b": "3B", "G_ss": "SS", "G_lf": "LF",
               "G_cf": "CF", "G_rf": "RF", "G_of": "OF", "G_dh": "DH"}
        if spots:
            top = max(spots.values())
            ok_labels = {lab[c] for c, v in spots.items() if v == top}
            others = sorted(spots.values(), reverse=True)
            if poslab.startswith("P/"):
                second = others[1] if len(others) > 1 else 0
                if not ("P" in {lab[c] for c, v in spots.items() if v in others[:2]} and second >= 0.35 * others[0]
                        and others[0] >= 20):
                    bad(f"player {pid} {name}: two-way label {poslab} not supported")
            elif poslab not in ok_labels:
                bad(f"player {pid} {name}: position {poslab}, expected one of {sorted(ok_labels)}")
        elif poslab:
            bad(f"player {pid} {name}: position {poslab} but no position games")
        # franchise stints
        s = M["spans"][i]
        got = set()
        for k in range(0, len(s), 5):
            f = FR[BI[s[k]]]
            got.add((f, 1800 + (BI[s[k + 1]] << 6 | BI[s[k + 2]]), 1800 + (BI[s[k + 3]] << 6 | BI[s[k + 4]])))
        want = {(f, min(nf["fry"][f]), max(nf["fry"][f])) for f in nf["frg"] if f in NICK and nf["frg"][f] > 0}
        if got != want:
            bad(f"player {pid} {name}: stints {sorted(got)} vs expected {sorted(want)}")
    for key in SUFFIX_EXPECTED:
        if suffix_hits[key] != 1:
            bad(f"suffix target {key} matched {suffix_hits[key]} players")
    # nicknames
    alias_seen = {}
    for k, names in (M.get("aliases") or {}).items():
        pid = IDS[int(k)]
        for a in names:
            alias_seen[a] = pid
    for a, (nm, yr) in ALIAS_EXPECTED.items():
        pid = alias_seen.get(a)
        if not pid:
            bad(f"nickname {a!r} missing")
        elif base_name(pid) != nm or info[pid]["deb"] != yr:
            bad(f"nickname {a!r} points to {base_name(pid)} ({info[pid]['deb']}), expected {nm} ({yr})")

    # ------------------------------------------------------ derived tables
    season_cache = {}

    def seasons_by(pid, kind, with_fr):
        """{(year[, franchise]): totals, plus qualifying team games} from Batting/Pitching rows."""
        key = (pid, kind, with_fr)
        if key not in season_cache:
            season_cache[key] = _seasons_by(pid, kind, with_fr)
        return season_cache[key]

    def _seasons_by(pid, kind, with_fr):
        out = defaultdict(Counter)
        for r in (bat if kind == "bat" else pit)[pid]:
            y = r["yearID"]
            key = (y, fr_of(y, r["teamID"])) if with_fr else y
            c = out[key]
            if kind == "bat":
                for s in ("AB", "H", "HR", "RBI", "SB", "R", "2B", "3B", "BB", "HBP", "SH", "SF"):
                    c[s] += nz(r[s])
                c["PA"] += nz(r["AB"]) + nz(r["BB"]) + nz(r["HBP"]) + nz(r["SH"]) + nz(r["SF"])
            else:
                for s in ("W", "L", "SV", "SO", "ER", "CG", "SHO", "G"):
                    c[s] += nz(r[s])
                c["IPouts"] += ipo(r)
            c["TG"] = max(c["TG"], tG(y, r["teamID"]))
        if not with_fr:
            for y, c in out.items():
                c["TG"] = year_tg[pid][y]
        return out

    year_tg = defaultdict(Counter)   # pid -> year -> most games by any team he played for (bat or pitch rows)
    for src in (bat, pit):
        for pid_, rows in src.items():
            for r in rows:
                year_tg[pid_][r["yearID"]] = max(year_tg[pid_][r["yearID"]], tG(r["yearID"], r["teamID"]))
    lg_tg = defaultdict(Counter)     # pid -> (year, league) -> same, within one league
    for src in (bat, pit):
        for pid_, rows in src.items():
            for r in rows:
                k = (r["yearID"], r["lgID"])
                lg_tg[pid_][k] = max(lg_tg[pid_][k], tG(r["yearID"], r["teamID"]))

    bat_q = lambda c: c["PA"] >= 3.1 * c["TG"]
    pit_q = lambda c: c["IPouts"] >= 3 * c["TG"]
    allstar = defaultdict(set)    # pid -> {(year, franchise)}
    for a in raw.t("AllstarFull"):
        if a["lgID"] in ("AL", "NL") and a["playerID"] in players:
            allstar[a["playerID"]].add((a["yearID"], fr_of(a["yearID"], a["teamID"])))
    as_years = {p: {y for y, _ in s} for p, s in allstar.items()}
    awards = defaultdict(list)
    for a in raw.t("AwardsPlayers"):
        if a["playerID"] in players:
            awards[a["playerID"]].append(a)
    hofrows = defaultdict(list)
    for h in raw.t("HallOfFame"):
        hofrows[h["playerID"]].append(h)
    hof = {p for p, rs in hofrows.items() if p in players and any(r["inducted"] == "Y" and r["category"] == "Player" for r in rs)}
    for nm, yr in (("Carlos Beltran", 1998), ("Andruw Jones", 1996), ("Jeff Kent", 1992)):  # class of 2026
        hit = [p for p in players if base_name(p) == nm and info[p]["deb"] == yr]
        if len(hit) != 1:
            bad(f"2026 Hall of Famer {nm} matched {len(hit)}")
        hof.update(hit)
    post = defaultdict(list)
    for kind, tab in (("bat", "BattingPost"), ("pit", "PitchingPost")):
        for r in raw.t(tab):
            if r["lgID"] in ("AL", "NL") and r["yearID"] >= 1903 and r["playerID"] in players:
                post[r["playerID"]].append((kind, r))
    votes = defaultdict(list)       # (award, year, lg) -> [(points, pid)]
    for v in raw.t("AwardsSharePlayers"):
        if v["playerID"] in players and nz(v["pointsWon"]) > 0:
            votes[(v["awardID"], v["yearID"], v["lgID"])].append((v["pointsWon"], v["playerID"]))
    vote_rank = defaultdict(list)   # pid -> [(award, year, competition rank)]
    for (aw, y, lg), rs in votes.items():
        for pts, p in rs:
            vote_rank[p].append((aw, y, 1 + sum(1 for q, _ in rs if q > pts)))
    managers = defaultdict(list)
    for m in raw.t("Managers"):
        if m["lgID"] in LEAGUES and m["playerID"] in players:
            managers[m["playerID"]].append(m)

    def main_fr(pid, y):
        c = info[pid]["ymain"].get(y)
        if not c:
            return None
        top = max(c.values())
        return {f for f, g in c.items() if g == top}

    by_fr = defaultdict(set)
    for pid in players:
        for t in info[pid]["teams"]:
            by_fr[fr_of(*t)].add(pid)

    post_teams = defaultdict(set)
    for p_, rs in post.items():
        for _, r in rs:
            if nz(r["G"]) > 0:
                post_teams[p_].add((r["yearID"], r["teamID"]))
    ws_of = {p: {t for t in info[p]["teams"] | post_teams[p] if t in ws_team} for p in players}
    pen_of = {p: {t for t in info[p]["teams"] | post_teams[p] if t in pen_team} for p in players}

    def primary(pid):
        c = info[pid]["pos"]
        spots = {k: c[k] for k in ("G_p", "G_c", "G_1b", "G_2b", "G_3b", "G_ss", "G_dh")}
        spots["G_of"] = max(c["G_of"], c["G_lf"] + c["G_cf"] + c["G_rf"])
        top = max(spots.values())
        return {k for k, v in spots.items() if v == top and v > 0}

    # ------------------------------------------------------- prompt rules
    def S(pred):
        return {p for p in players if pred(p)}

    def season_any(kind, pred, with_fr=False, fr=None, years=None):
        out = set()
        for p in players:
            for k, c in seasons_by(p, kind, with_fr).items():
                y = k[0] if with_fr else k
                if with_fr and k[1] != fr:
                    continue
                if years and not (years[0] <= y <= years[1]):
                    continue
                if pred(c):
                    out.add(p)
                    break
        return out

    CAREER = {
        "hr300": lambda p: info[p]["bat"]["HR"] >= 300, "hr200": lambda p: info[p]["bat"]["HR"] >= 200,
        "hr150": lambda p: info[p]["bat"]["HR"] >= 150, "hr100": lambda p: info[p]["bat"]["HR"] >= 100,
        "h2500": lambda p: info[p]["bat"]["H"] >= 2500, "h2000": lambda p: info[p]["bat"]["H"] >= 2000,
        "h1500": lambda p: info[p]["bat"]["H"] >= 1500, "h1000": lambda p: info[p]["bat"]["H"] >= 1000,
        "rbi1000": lambda p: info[p]["bat"]["RBI"] >= 1000, "r1000": lambda p: info[p]["bat"]["R"] >= 1000,
        "2b300": lambda p: info[p]["bat"]["2B"] >= 300, "3b100": lambda p: info[p]["bat"]["3B"] >= 100,
        "sb300": lambda p: info[p]["bat"]["SB"] >= 300, "sb200": lambda p: info[p]["bat"]["SB"] >= 200,
        "sb150": lambda p: info[p]["bat"]["SB"] >= 150, "bb1000": lambda p: info[p]["bat"]["BB"] >= 1000,
        "avg300": lambda p: info[p]["bat"]["PA"] >= 3000 and avg_thou(info[p]["bat"]["H"], info[p]["bat"]["AB"]) >= 300,
        "avg290": lambda p: info[p]["bat"]["PA"] >= 3000 and avg_thou(info[p]["bat"]["H"], info[p]["bat"]["AB"]) >= 290,
        "hr100sb100": lambda p: info[p]["bat"]["HR"] >= 100 and info[p]["bat"]["SB"] >= 100,
        "w200": lambda p: info[p]["pit"]["W"] >= 200, "w150": lambda p: info[p]["pit"]["W"] >= 150,
        "w100": lambda p: info[p]["pit"]["W"] >= 100, "k1500": lambda p: info[p]["pit"]["SO"] >= 1500,
        "k1000": lambda p: info[p]["pit"]["SO"] >= 1000, "sv100": lambda p: info[p]["pit"]["SV"] >= 100,
        "sv50": lambda p: info[p]["pit"]["SV"] >= 50, "pg600": lambda p: info[p]["pit"]["G"] >= 600,
        "era3": lambda p: info[p]["pit"]["IPouts"] >= 3000 and era_hund(info[p]["pit"]["ER"], info[p]["pit"]["IPouts"]) < 300,
        "g2000": lambda p: info[p]["G"] >= 2000, "g1500": lambda p: info[p]["G"] >= 1500,
        "seasons15": lambda p: len(info[p]["years"]) >= 15, "seasons20": lambda p: len(info[p]["years"]) >= 20,
        "fr8": lambda p: len([f for f, g in info[p]["frg"].items() if g > 0]) >= 8,
        "as3": lambda p: len(as_years.get(p, ())) >= 3,
    }
    BATQ = lambda t: (lambda c: bat_q(c) and avg_thou(c["H"], c["AB"]) >= round(t * 1000))
    PITQ = lambda t: (lambda c: pit_q(c) and era_hund(c["ER"], c["IPouts"]) < round(t * 100))
    SEASON = {  # key -> (kind, predicate)
        "hr40": ("bat", lambda c: c["HR"] >= 40), "hr35": ("bat", lambda c: c["HR"] >= 35),
        "hr30": ("bat", lambda c: c["HR"] >= 30), "hr25": ("bat", lambda c: c["HR"] >= 25),
        "h200": ("bat", lambda c: c["H"] >= 200), "h190": ("bat", lambda c: c["H"] >= 190),
        "rbi130": ("bat", lambda c: c["RBI"] >= 130), "rbi120": ("bat", lambda c: c["RBI"] >= 120),
        "rbi100": ("bat", lambda c: c["RBI"] >= 100), "r130": ("bat", lambda c: c["R"] >= 130),
        "r120": ("bat", lambda c: c["R"] >= 120), "2b40": ("bat", lambda c: c["2B"] >= 40),
        "3b15": ("bat", lambda c: c["3B"] >= 15), "3b12": ("bat", lambda c: c["3B"] >= 12),
        "sb60": ("bat", lambda c: c["SB"] >= 60), "sb50": ("bat", lambda c: c["SB"] >= 50),
        "sb40": ("bat", lambda c: c["SB"] >= 40), "sb30": ("bat", lambda c: c["SB"] >= 30),
        "bb100": ("bat", lambda c: c["BB"] >= 100), "avg350": ("bat", BATQ(0.350)), "avg330": ("bat", BATQ(0.330)),
        "avg300": ("bat", BATQ(0.300)), "2020": ("bat", lambda c: c["HR"] >= 20 and c["SB"] >= 20),
        "triple3": ("bat", lambda c: BATQ(0.300)(c) and c["HR"] >= 30 and c["RBI"] >= 100),
        "w25": ("pit", lambda c: c["W"] >= 25), "w20": ("pit", lambda c: c["W"] >= 20),
        "w18": ("pit", lambda c: c["W"] >= 18), "w15": ("pit", lambda c: c["W"] >= 15),
        "l20": ("pit", lambda c: c["L"] >= 20), "so225": ("pit", lambda c: c["SO"] >= 225),
        "so200": ("pit", lambda c: c["SO"] >= 200), "so150": ("pit", lambda c: c["SO"] >= 150),
        "sv35": ("pit", lambda c: c["SV"] >= 35), "sv30": ("pit", lambda c: c["SV"] >= 30),
        "era2": ("pit", PITQ(2.00)), "era25": ("pit", PITQ(2.50)), "cg25": ("pit", lambda c: c["CG"] >= 25),
        "pg80": ("pit", lambda c: c["G"] >= 80), "ip250": ("pit", lambda c: c["IPouts"] >= 750),
    }
    TEAM_SEASON = {
        "avg290": ("bat", BATQ(0.290)), "sb20": ("bat", lambda c: c["SB"] >= 20), "2b30": ("bat", lambda c: c["2B"] >= 30),
        "w15": ("pit", lambda c: c["W"] >= 15), "w12": ("pit", lambda c: c["W"] >= 12), "w10": ("pit", lambda c: c["W"] >= 10),
        "ip200": ("pit", lambda c: c["IPouts"] >= 600), "era35": ("pit", PITQ(3.50)),
    }

    def leaders(stat):
        kind = "pit" if stat in ("W", "SO", "SV", "ERA") else "bat"
        per = defaultdict(list)
        for p in players:
            acc = defaultdict(Counter)
            for r in (bat if kind == "bat" else pit)[p]:
                k = (r["yearID"], r["lgID"])
                c = acc[k]
                for s in ("AB", "H", "HR", "RBI", "SB", "BB", "HBP", "SH", "SF", "W", "SO", "SV", "ER"):
                    if s in r:
                        c[s] += nz(r[s])
                if kind == "pit":
                    c["IPouts"] += ipo(r)
                c["PA"] = c["AB"] + c["BB"] + c["HBP"] + c["SH"] + c["SF"]
                c["TG"] = max(c["TG"], tG(r["yearID"], r["teamID"]))
            for (y, lg), c in acc.items():
                c["TG"] = lg_tg[p][(y, lg)]
                if stat == "SV" and y < 1969:
                    continue
                if stat == "AVG":
                    if not bat_q(c):
                        continue
                    v = c["H"] / c["AB"]
                elif stat == "ERA":
                    if not pit_q(c):
                        continue
                    v = -27 * c["ER"] / c["IPouts"]
                else:
                    v = c[stat]
                    if v <= 0:
                        continue
                per[(y, lg)].append((v, p))
        out = set()
        for rs in per.values():
            top = max(v for v, _ in rs)
            out |= {p for v, p in rs if abs(v - top) < 1e-9}
        return out

    def debut_y(p):
        d = info[p]["deb"]
        return d if d in info[p]["years"] else info[p]["y0"]

    def first_team(p):
        y = debut_y(p)
        cands = [(r["stint"], 0, r["teamID"]) for r in bat[p] if r["yearID"] == y] + \
                [(r["stint"], 1, r["teamID"]) for r in pit[p] if r["yearID"] == y]
        if cands:
            return fr_of(y, min(cands)[2])
        m = main_fr(p, y)
        return next(iter(m)) if m and len(m) == 1 else None

    def surely_18(p):
        """18 or younger on the day of his first MLB-recognized game, beyond doubt."""
        pp = people[p]
        by = pp.get("birthYear")
        if not by:
            return False
        d = pp.get("debut")
        if d is not None and d.year == debut_y(p) and pp.get("birthMonth") and pp.get("birthDay"):
            return d.year - by - ((d.month, d.day) < (pp["birthMonth"], pp["birthDay"])) <= 18
        return debut_y(p) - by <= 18

    WORDS = {}
    FIRST = {}
    sys.path.insert(0, HERE)
    import build_data as content   # word lists and first-name variants only (hand-written content)
    for k, (_, _, words) in content.WORD_LISTS.items():
        WORDS[k] = words
    for label, variants in content.FIRST_NAMES:
        FIRST["n-f-" + re.sub("[^a-z]+", "-", label.lower()).strip("-")] = {fold(v) for v in variants}

    last_count = Counter((people[p]["nameLast"] or "").strip() for p in players)
    hof_last = {(people[p]["nameLast"] or "").strip() for p in hof} | {
        (people[h]["nameLast"] or "").strip() for h, rs in hofrows.items()
        if h in people and any(r["inducted"] == "Y" and r["category"] == "Player" for r in rs)}

    def expected(pid_):
        m = re.match(r"^(team|pair|dec|tx|tp|tb|tc|te|ta|tm|tpost|tv|ts|c|s|df|wsd|as|ad|a|ap|v|h|hof|ws|post|pen|lead|rec|b|bh|bp|n|x|m|deb|fin|mate|era)-(.+)$", pid_)
        fam, rest = m.group(1), m.group(2)
        if fam == "team":
            return by_fr[rest]
        if fam == "pair":
            a, b = rest.split("-")
            return by_fr[a] & by_fr[b]
        if fam == "dec":
            f, dd = rest.split("-")
            dd = int(dd)
            return {p for p in by_fr[f] if any(fr_of(*t) == f and dd <= t[0] <= dd + 9 for t in info[p]["teams"])}
        if fam == "era":
            f, y0, y1 = ERAS[rest]
            return {p for p in by_fr[f] if any(fr_of(*t) == f and y0 <= t[0] <= y1 for t in info[p]["teams"])}
        if fam == "tx":
            key, f = rest.split("-")
            col = {"hr1": ("bat", "HR"), "sv1": ("pit", "SV"), "sho1": ("pit", "SHO"), "w1": ("pit", "W")}[key]
            src = bat if col[0] == "bat" else pit
            return {p for p in players if sum(nz(r[col[1]]) for r in src[p] if fr_of(r["yearID"], r["teamID"]) == f) > 0}
        if fam == "tp":
            key, f = rest.split("-")
            if key == "lhp":
                return {p for p in by_fr[f] if info[p]["frpos"][f]["G_p"] > 0 and people[p]["throws"] == "L"}
            if key == "switch":
                return {p for p in by_fr[f] if people[p]["bats"] == "B" and info[p]["pos"]["G_p"] < 0.5 * max(1, info[p]["G"])}
            col = {"c": "G_c", "1b": "G_1b", "2b": "G_2b", "3b": "G_3b", "ss": "G_ss", "of": "G_of", "dh": "G_dh"}[key]
            return {p for p in by_fr[f] if info[p]["frpos"][f][col] > 0}
        if fam == "tb":
            key, f = rest.split("-")
            if key == "intl":
                return {p for p in by_fr[f] if people[p]["birthCountry"] not in (None, "USA")}
            if key == "dr":
                return {p for p in by_fr[f] if people[p]["birthCountry"] == "D.R."}
            return {p for p in by_fr[f] if people[p]["birthCountry"] == "USA" and people[p]["birthState"] == key.upper()}
        if fam == "tc":
            key, f = rest.split("-")
            return {p for p in by_fr[f] if CAREER[key](p)}
        if fam == "te":
            key, f = rest.split("-")
            pred = {"as": lambda p: p in as_years, "ws": lambda p: bool(ws_of[p])}[key]
            return {p for p in by_fr[f] if pred(p)}
        if fam == "ta":
            key, f = rest.split("-")
            if key == "as":
                return {p for p, s in allstar.items() if any(fr == f for _, fr in s)}
            if key == "pen":
                return {p for p in players if any(fr_of(*t) == f for t in pen_of[p])}
            if key == "ws":
                return {p for p in players if any(fr_of(*t) == f for t in ws_of[p])}
        if fam == "tm":
            key, f = rest.split("-")
            if key == "debut":
                return {p for p in by_fr[f] if first_team(p) == f}
            if key == "final":
                return {p for p in by_fr[f] if info[p]["y1"] < LAST_YEAR and info[p]["y1"] in info[p]["fry"][f]}
        if fam == "tpost":
            return {p for p, rs in post.items() if any(nz(r["G"]) > 0 and fr_of(r["yearID"], r["teamID"]) == rest for _, r in rs)}
        if fam == "tv":
            f = rest.split("-")[1]
            return {p for p, rs in vote_rank.items() if any(aw == "Most Valuable Player" and f in (main_fr(p, y) or ()) for aw, y, _ in rs)}
        if fam == "ts":
            key, f = rest.split("-")
            kind, pred = TEAM_SEASON[key]
            return season_any(kind, pred, with_fr=True, fr=f)
        if fam == "c":
            return S(CAREER[rest])
        if fam == "s":
            kind, pred = SEASON[rest]
            return season_any(kind, pred)
        if fam == "df":
            key, dd = rest.split("-")
            kind, pred = SEASON[key]
            return season_any(kind, pred, years=(int(dd), int(dd) + 9))
        if fam == "wsd":
            dd = int(rest)
            return {p for p in players if any(dd <= y <= dd + 9 for y, _ in ws_of[p])}
        if fam == "as":
            if rest.isdigit() and len(rest) == 4:
                dd = int(rest)
                return {p for p, ys in as_years.items() if any(dd <= y <= dd + 9 for y in ys)}
            n = {"1": None, "2plus": 2, "3plus": 3, "5": 5}[rest]
            return {p for p, ys in as_years.items() if (len(ys) == 1 if n is None else len(ys) >= n)}
        if fam == "ad":
            key, dd = rest.split("-")
            dd = int(dd)
            return {p for p, rs in awards.items() if any(r["awardID"] == "Silver Slugger" and dd <= r["yearID"] <= dd + 9 for r in rs)}
        if fam == "a":
            names = {"mvp": {"Most Valuable Player"}, "roy": {"Rookie of the Year"}, "gg": {"Gold Glove"},
                     "ss": {"Silver Slugger"}, "cpoy": {"Comeback Player of the Year", "TSN Comeback Player of the Year"}}[rest]
            return {p for p, rs in awards.items() if any(r["awardID"] in names for r in rs)}
        if fam == "ap":
            aw = {"gg": "Gold Glove", "ss": "Silver Slugger"}[rest.split("-")[0]]
            return {p for p, rs in awards.items() if any(r["awardID"] == aw and r["notes"] in ("OF", "LF", "CF", "RF") for r in rs)}
        if fam == "v":
            key, cut = rest.split("-")
            aw = {"mvp": "Most Valuable Player", "cy": "Cy Young Award", "roy": "Rookie of the Year"}[key]
            lim = None if cut == "any" else int(cut[3:])
            return {p for p, rs in vote_rank.items() if any(a == aw and (lim is None or rk <= lim) for a, _, rk in rs)}
        if fam == "h":
            if rest == "all":
                return set(hof)
            if rest == "nows":
                return {p for p in hof if not ws_of[p]}
        if fam == "hof":
            best = {}
            for p, rs in hofrows.items():
                for r in rs:
                    if p in players and r["votedBy"] == "BBWAA" and r["ballots"] and nz(r["votes"]) > 0:
                        best[p] = max(best.get(p, 0), r["votes"] / r["ballots"])
            return set(best) if rest == "ballot" else {p for p, v in best.items() if v >= 0.25}
        if fam == "ws":
            if rest == "any":
                return {p for p in players if ws_of[p]}
            if rest == "2fr":
                return {p for p in players if len({fr_of(*t) for t in ws_of[p]}) >= 2}
            if rest == "never":
                return {p for p in players if len(info[p]["years"]) >= 15 and not ws_of[p]}
            col = {"hr": ("bat", "HR"), "w": ("pit", "W"), "sv": ("pit", "SV")}[rest]
            return {p for p, rs in post.items() if sum(nz(r[col[1]]) for k, r in rs if k == col[0] and r["round"] == "WS") > 0}
        if fam == "post":
            if rest == "any":
                return {p for p, rs in post.items() if any(r["round"] == "WS" and nz(r["G"]) > 0 for _, r in rs)}
            col = {"hr": ("bat", "HR"), "w": ("pit", "W")}[rest]
            return {p for p, rs in post.items() if sum(nz(r[col[1]]) for k, r in rs if k == col[0]) > 0}
        if fam == "pen":
            return {p for p in players if len({fr_of(*t) for t in pen_of[p]}) >= 2}
        if fam == "lead":
            return leaders({"hr": "HR", "rbi": "RBI", "sb": "SB", "h": "H", "avg": "AVG", "w": "W", "so": "SO",
                            "sv": "SV", "era": "ERA"}[rest])
        if fam == "rec":
            kind, n = rest[0], int(rest[1:])
            col = "W" if kind == "w" else "L"
            return {p for p in players if any(tinfo[t]["lgID"] in LEAGUES and (tinfo[t][col] or 0) >= n for t in info[p]["teams"])}
        if fam == "b":
            pp = lambda p: people[p]
            if rest == "2000s":
                return {p for p in players if (pp(p)["birthYear"] or 0) >= 2000}
            if rest == "intl":
                return {p for p in players if pp(p)["birthCountry"] not in (None, "USA")}
            if rest in COUNTRY:
                return {p for p in players if pp(p)["birthCountry"] == COUNTRY[rest]}
            if rest.startswith("st-"):
                st = rest[3:].upper()
                return {p for p in players if pp(p)["birthCountry"] == "USA" and pp(p)["birthState"] == st}
            if rest == "city-nyc":
                return {p for p in players if pp(p)["birthState"] == "NY" and pp(p)["birthCountry"] == "USA" and pp(p)["birthCity"] in content.NYC}
            if rest.startswith("city-"):
                city_slug = rest[5:]
                slug = lambda c, region: re.sub("[^a-z]+", "-", fold(f"{c} {region}").lower()).strip("-")
                region_of = lambda p: pp(p)["birthState"] if pp(p)["birthCountry"] == "USA" else pp(p)["birthCountry"]
                keys = [k for k in content.CITY_AREAS if slug(*k) == city_slug]
                names = {keys[0][0], *content.CITY_AREAS[keys[0]][0]} if keys else None
                out = set()
                for p in players:
                    c = pp(p)["birthCity"]
                    if not c:
                        continue
                    if (names and c in names and region_of(p) == keys[0][1]) or slug(c, region_of(p)) == city_slug:
                        out.add(p)
                return out
        if fam == "bh":
            ctry, key = rest.split("-")
            pred = {"as": lambda p: p in as_years, "ws": lambda p: bool(ws_of[p])}[key]
            return {p for p in players if people[p]["birthCountry"] == COUNTRY[ctry] and pred(p)}
        if fam == "bp":
            ctry, pos = rest.split("-")
            col = {"p": "G_p", "c": "G_c", "1b": "G_1b", "2b": "G_2b", "3b": "G_3b", "ss": "G_ss", "of": "G_of"}[pos]
            return {p for p in players if people[p]["birthCountry"] == COUNTRY[ctry] and col in primary(p)}
        if fam == "n":
            first = lambda p: (people[p]["nameFirst"] or "").strip()
            last = lambda p: (people[p]["nameLast"] or "").strip()
            if rest.startswith("last-"):
                return {p for p in players if fold(last(p)).upper().startswith(rest[5:])}
            if rest.startswith("first-"):
                return {p for p in players if fold(first(p)).upper().startswith(rest[6:])}
            if rest == "allit":
                return {p for p in players if first(p) and last(p) and fold(first(p))[0].upper() == fold(last(p))[0].upper()}
            if rest == "short":
                return {p for p in players if 0 < len(re.sub("[^A-Za-z]", "", fold(last(p)))) <= 3}
            if rest == "long":
                return {p for p in players if len(re.sub("[^A-Za-z]", "", fold(last(p)))) >= 11}
            if rest == "z":
                return {p for p in players if "z" in fold(last(p)).lower()}
            if rest == "x":
                return {p for p in players if "x" in fold(f"{first(p)} {last(p)}").lower()}
            if rest == "double":
                return {p for p in players if re.search(r"(.)\1", fold(last(p)).lower())}
            if rest == "jr-mc":
                return {p for p in players if fold(last(p)).lower().startswith(("mc", "mac"))}
            if rest == "space":
                return {p for p in players if " " in last(p)}
            if rest.startswith("w-"):
                return {p for p in players if last(p) in WORDS[rest[2:]]}
            if rest.startswith("f-"):
                vs = FIRST["n-" + rest]
                out = set()
                for p in players:
                    ft = fold(first(p).split(" ")[0]) if first(p) else ""
                    gt = fold((people[p]["nameGiven"] or "").strip().split(" ")[0]) if people[p]["nameGiven"] else ""
                    if ft in vs or (gt in vs and len(first(p).split(" ")[0]) > 1):
                        out.add(p)
                return out
            if rest == "unique":
                return {p for p in players if last_count[last(p)] == 1}
            if rest == "hoflast":
                return {p for p in players if last(p) in hof_last and p not in hof}
        if fam == "x":
            if rest == "heavy":
                return {p for p in players if (people[p]["weight"] or 0) >= 260}
            if rest == "switch-as":
                return {p for p in players if people[p]["bats"] == "B" and p in as_years}
            if rest == "teen":
                return {p for p in players if surely_18(p)}
        if fam == "m":
            if rest == "any":
                return set(managers)
            if rest == "pm":
                return {p for p, ms in managers.items() if any(m["plyrMgr"] == "Y" for m in ms)}
        if fam == "deb":
            return {p for p in players if debut_y(p) == int(rest)}
        if fam == "fin":
            return {p for p in players if info[p]["y1"] == int(rest)}
        raise KeyError(pid_)

    def mate_star(pr):
        mt = re.match(r"^Was a teammate of (.+)$", pr["t"])
        ms = re.search(r"played (\d{4})–(\d{4})$", pr.get("s", ""))
        hits = [i for i, row in enumerate(M["players"]) if row[0] == mt.group(1) and row[1] == int(ms.group(1)) and row[2] == int(ms.group(2))]
        return IDS[hits[0]] if len(hits) == 1 else None


    # ------------------------------------------------------ on-screen wording
    # Every prompt's text is re-derived from its rule key, so a label can't say
    # "40+" over a 30-HR rule or name the wrong club.
    N = lambda f: NICK[f]
    DEMONYM = {"dr": "Dominican", "venezuela": "Venezuelan", "cuba": "Cuban", "can": "Canadian", "pr": "Puerto Rican",
               "mexico": "Mexican", "japan": "Japanese"}
    POSWORD = {"p": "pitcher", "c": "catcher", "1b": "first baseman", "2b": "second baseman", "3b": "third baseman",
               "ss": "shortstop", "of": "outfielder"}
    COUNTRY_NAME = {"dr": "the Dominican Republic", "venezuela": "Venezuela", "cuba": "Cuba", "pr": "Puerto Rico",
                    "can": "Canada", "mexico": "Mexico", "japan": "Japan", "panama": "Panama", "colombia": "Colombia",
                    "curacao": "Curaçao"}
    ERA_NAME = {"brooklyn-dodgers": "Brooklyn Dodgers", "new-york-giants": "New York Giants",
                "montreal-expos": "Montreal Expos", "st-louis-browns": "St. Louis Browns",
                "philadelphia-athletics": "Philadelphia Athletics", "kansas-city-athletics": "Kansas City Athletics",
                "oakland-athletics": "Oakland Athletics", "boston-braves": "Boston Braves",
                "milwaukee-braves": "Milwaukee Braves", "washington-senators-1901-60": "Washington Senators (1901–60)",
                "washington-senators-1961-71": "Washington Senators (1961–71)", "seattle-pilots": "Seattle Pilots",
                "houston-colt-45s": "Houston Colt .45s", "florida-marlins": "Florida Marlins",
                "tampa-bay-devil-rays": "Tampa Bay Devil Rays", "california-angels": "California Angels",
                "new-york-highlanders": "New York Highlanders", "cleveland-indians": "Cleveland Indians"}
    CAREER_TEXT = {
        "hr300": "300+ career home runs", "hr200": "200+ career home runs", "hr150": "150+ career home runs",
        "hr100": "100+ career home runs", "h2500": "2,500+ career hits", "h2000": "2,000+ career hits",
        "h1500": "1,500+ career hits", "h1000": "1,000+ career hits", "rbi1000": "1,000+ career RBI",
        "r1000": "1,000+ career runs scored", "2b300": "300+ career doubles", "3b100": "100+ career triples",
        "sb300": "300+ career stolen bases", "sb200": "200+ career stolen bases", "sb150": "150+ career stolen bases",
        "bb1000": "1,000+ career walks (as a hitter)", "avg300": ".300+ career batting average (min. 3,000 PA)",
        "avg290": ".290+ career batting average (min. 3,000 PA)", "hr100sb100": "100+ career home runs and 100+ steals",
        "w200": "200+ career wins", "w150": "150+ career wins", "w100": "100+ career wins",
        "k1500": "1,500+ career strikeouts (pitching)", "k1000": "1,000+ career strikeouts (pitching)",
        "sv100": "100+ career saves", "sv50": "50+ career saves", "pg600": "Pitched in 600+ games",
        "era3": "Sub-3.00 career ERA (min. 1,000 IP)", "g2000": "Played in 2,000+ games",
        "g1500": "1,500+ career games played", "seasons15": "Played 15+ seasons in the majors",
        "seasons20": "Played 20+ seasons in the majors", "fr8": "Played for 8+ different franchises",
        "as3": "3+ All-Star selections",
    }
    SEASON_TEXT = {
        "hr40": "Hit 40+ home runs", "hr35": "Hit 35+ home runs", "hr30": "Hit 30+ home runs", "hr25": "Hit 25+ home runs",
        "h200": "Had 200+ hits", "h190": "Had 190+ hits", "rbi130": "Drove in 130+ runs", "rbi120": "Drove in 120+ runs",
        "rbi100": "Drove in 100+ runs", "r130": "Scored 130+ runs", "r120": "Scored 120+ runs",
        "2b40": "Hit 40+ doubles", "3b15": "Hit 15+ triples", "3b12": "Hit 12+ triples", "sb60": "Stole 60+ bases",
        "sb50": "Stole 50+ bases", "sb40": "Stole 40+ bases", "sb30": "Stole 30+ bases", "bb100": "Drew 100+ walks",
        "avg350": "Hit .350+", "avg330": "Hit .330+", "avg300": "Hit .300+", "w25": "Won 25+ games",
        "w20": "Won 20+ games", "w18": "Won 18+ games", "w15": "Won 15+ games", "l20": "Lost 20+ games",
        "so225": "Struck out 225+ batters", "so200": "Struck out 200+ batters", "so150": "Struck out 150+ batters",
        "sv35": "Saved 35+ games", "sv30": "Saved 30+ games", "cg25": "Threw 25+ complete games",
        "pg80": "Pitched in 80+ games", "ip250": "Pitched 250+ innings",
    }
    SEASON_WHOLE = {"2020": "20 HR / 20 SB season", "triple3": ".300 / 30 HR / 100 RBI season",
                    "era2": "Sub-2.00 ERA in a season", "era25": "Sub-2.50 ERA in a season"}
    TEAM_SEASON_TEXT = {"avg290": "Hit .290+", "sb20": "Stole 20+ bases", "2b30": "Hit 30+ doubles",
                        "w15": "Won 15+ games", "w12": "Won 12+ games", "w10": "Won 10+ games",
                        "ip200": "Pitched 200+ innings", "era35": "Posted a sub-3.50 ERA"}
    TP_TEXT = {"1b": "Played first base for", "2b": "Played second base for", "3b": "Played third base for",
               "c": "Played catcher for", "dh": "Played DH for", "ss": "Played shortstop for",
               "of": "Played the outfield for", "lhp": "Left-handed pitcher for",
               "switch": "Switch-hitter who played for"}
    TX_TEXT = {"hr1": "Homered for", "sv1": "Recorded a save for", "sho1": "Threw a shutout for",
               "w1": "Won a game as a pitcher for"}
    FIXED_TEXT = {
        "a-mvp": "Won an MVP award", "a-roy": "Won Rookie of the Year", "a-gg": "Won a Gold Glove",
        "a-ss": "Won a Silver Slugger", "a-cpoy": "Won a Comeback Player of the Year award",
        "ap-gg-of": "Won a Gold Glove as an outfielder", "ap-ss-of": "Won a Silver Slugger as an outfielder",
        "as-1": "Made exactly one All-Star team", "as-2plus": "Made 2+ All-Star teams",
        "as-3plus": "Made 3+ All-Star teams", "as-5": "Made 5+ All-Star teams",
        "h-all": "Hall of Famer", "h-nows": "Hall of Famer who never won a World Series",
        "hof-ballot": "Appeared on a Hall of Fame writers' ballot",
        "hof-25": "Got 25%+ of the vote on a Hall of Fame writers' ballot",
        "ws-any": "Won a World Series", "ws-2fr": "Won World Series titles with two different franchises",
        "ws-hr": "Homered in a World Series game", "ws-w": "Won a World Series game as a pitcher",
        "ws-sv": "Saved a World Series game", "ws-never": "Played 15+ seasons and never won a World Series",
        "post-any": "Played in a World Series game", "post-hr": "Homered in a postseason game",
        "post-w": "Won a postseason game as a pitcher", "pen-2fr": "Won pennants with two or more franchises",
        "b-intl": "Born outside the United States", "b-2000s": "Born in 2000 or later",
        "b-city-nyc": "Born in New York City",
        "x-heavy": "Listed at 260+ pounds", "x-switch-as": "Switch-hitting All-Star",
        "x-teen": "Debuted at age 18 or younger",
        "n-allit": "Alliterative name", "n-short": "Last name of three letters or fewer",
        "n-long": "Last name of 11+ letters", "n-z": "Last name contains a Z", "n-x": "Name contains an X",
        "n-double": "Last name has a double letter", "n-jr-mc": "Last name starts with Mc or Mac",
        "n-space": "Last name of two or more words", "n-unique": "Only player in MLB history with his last name",
        "n-hoflast": "Shares a last name with a Hall of Famer (but isn't one)",
        "n-w-color": "Last name is a color", "n-w-animal": "Last name is an animal", "n-w-job": "Last name is a job",
        "n-w-food": "Last name is a food", "n-w-president": "Shares a last name with a U.S. president",
        "n-w-nature": "Last name is a feature of nature",
        "m-any": "Played and managed in the majors", "m-pm": "Was a player-manager",
        "lead-hr": "Led his league in home runs", "lead-rbi": "Led his league in RBI",
        "lead-sb": "Led his league in stolen bases", "lead-h": "Led his league in hits",
        "lead-avg": "Won a batting title", "lead-w": "Led his league in wins",
        "lead-so": "Led his league in strikeouts (pitching)", "lead-era": "Won an ERA title",
        "rec-w110": "Played for a 110-win team", "rec-w105": "Played for a 105-win team",
        "rec-l110": "Played for a 110-loss team", "rec-l105": "Played for a 105-loss team",
        "v-mvp-any": "Received a vote for MVP", "v-cy-any": "Received a vote for the Cy Young",
        "v-roy-any": "Received a vote for Rookie of the Year",
        "bh-dr-as": "All-Star born in the Dominican Republic",
        "bh-dr-ws": "World Series champion born in the Dominican Republic",
    }
    CITY_LABEL = {"chicago-il": "Chicago", "philadelphia-pa": "Philadelphia", "los-angeles-ca": "Los Angeles",
                  "boston-ma": "Boston"}

    def expected_text(pr):
        pid_ = pr["id"]
        if pid_ in FIXED_TEXT:
            return FIXED_TEXT[pid_]
        m = re.match(r"^([a-z]+)-(.+)$", pid_)
        fam, rest = m.group(1), m.group(2)
        parts = rest.split("-")
        if fam == "team":
            return f"Played for the {N(rest)}"
        if fam == "pair":
            return f"Played for the {N(parts[0])} and the {N(parts[1])}"
        if fam == "dec":
            return f"Played for the {N(parts[0])} in the {parts[1]}s"
        if fam == "era":
            return f"Played for the {ERA_NAME[rest]}"
        if fam == "tx":
            return f"{TX_TEXT[parts[0]]} the {N(parts[1])}"
        if fam == "tp":
            return f"{TP_TEXT[parts[0]]} the {N(parts[1])}"
        if fam == "tb":
            k, f = parts
            if k == "intl":
                return f"Born outside the U.S. and played for the {N(f)}"
            if k == "dr":
                return f"Born in the Dominican Republic and played for the {N(f)}"
            return f"Born in {STATE_NAMES[k.upper()]} and played for the {N(f)}"
        if fam == "tc":
            return f"{CAREER_TEXT[parts[0]]} and played for the {N(parts[1])}"
        if fam == "te":
            what = {"as": "made an All-Star team", "ws": "won a World Series"}[parts[0]]
            return f"Played for the {N(parts[1])} and {what}"
        if fam == "ta":
            k, f = parts
            return {"as": f"Made an All-Star team with the {N(f)}", "pen": f"Played for a pennant-winning {N(f)} team",
                    "ws": f"Won a World Series with the {N(f)}"}[k]
        if fam == "tm":
            k, f = parts
            return {"debut": f"Made his MLB debut with the {N(f)}", "final": f"Played his final MLB season with the {N(f)}"}[k]
        if fam == "tpost":
            return f"Played in the postseason for the {N(rest)}"
        if fam == "tv":
            return f"Received an MVP vote as a member of the {N(parts[1])}"
        if fam == "ts":
            return f"{TEAM_SEASON_TEXT[parts[0]]} in a season for the {N(parts[1])}"
        if fam == "c":
            return CAREER_TEXT[rest]
        if fam == "s":
            return SEASON_WHOLE.get(rest) or f"{SEASON_TEXT[rest]} in a season"
        if fam == "df":
            return f"{SEASON_TEXT[parts[0]]} in a season in the {parts[1]}s"
        if fam == "wsd":
            return f"Won a World Series in the {rest}s"
        if fam == "as":
            return f"Made an All-Star team in the {rest}s"
        if fam == "ad":
            return f"Won a Silver Slugger in the {parts[1]}s"
        if fam == "v":
            aw = {"mvp": "MVP voting", "cy": "the Cy Young voting", "roy": "Rookie of the Year voting"}[parts[0]]
            return f"Finished in the top {parts[1][3:]} of {aw}"
        if fam == "b":
            if rest.startswith("st-"):
                return f"Born in {STATE_NAMES[rest[3:].upper()]}"
            if rest.startswith("city-"):
                key = rest[5:]
                hit = [(c, r) for c, r in content.CITY_AREAS] + [(c, r) for c, r in (
                    ("Chicago", "IL"), ("St. Louis", "MO"), ("San Francisco", "CA"), ("Houston", "TX"),
                    ("Cleveland", "OH"), ("Atlanta", "GA"), ("San Pedro de Macoris", "D.R."))]
                for c, r in hit:
                    if re.sub("[^a-z]+", "-", fold(f"{c} {r}").lower()).strip("-") == key:
                        if key in CITY_LABEL:
                            return f"Born in {CITY_LABEL[key]}"
                        if r in STATE_NAMES:
                            return f"Born in {c}, {STATE_NAMES[r].replace(' State', '')}"
                        return f"Born in {c}, {dict(CUBA='Cuba').get(r.upper(), 'Dominican Republic' if r == 'D.R.' else r)}"
                raise KeyError(rest)
            return f"Born in {COUNTRY_NAME[rest]}"
        if fam == "bp":
            return f"{DEMONYM[parts[0]]}-born {POSWORD[parts[1]]}"
        if fam == "n":
            if rest.startswith("last-"):
                return f"Last name starts with {rest[5:]}"
            if rest.startswith("first-"):
                return f"First name starts with {rest[6:]}"
            if rest.startswith("f-"):
                label = next(lb for lb, _ in content.FIRST_NAMES
                             if "f-" + re.sub("[^a-z]+", "-", lb.lower()).strip("-") == rest)
                return f"First name: {label}"
        if fam == "deb":
            return f"Made his MLB debut in {rest}"
        if fam == "fin":
            return f"Played his last MLB season in {rest}"
        if fam == "mate":
            return pr["t"]  # checked by identifying the star from it
        raise KeyError(pid_)

    team_note = {}
    for pr in M["prompts"]:
        if pr["id"].startswith("team-"):
            sub_ = pr.get("s") or ""
            team_note[pr["id"][5:]] = sub_
    for pr in M["prompts"]:
        try:
            want_t = expected_text(pr)
        except Exception as e:  # noqa: BLE001
            bad(f"{pr['id']}: no wording rule ({e!r})")
            continue
        if pr["t"] != want_t:
            bad(f"{pr['id']}: text {pr['t']!r}, expected {want_t!r}")
        codes = re.findall(r"\b(" + "|".join(NICK) + r")\b", pr["id"])
        if pr["id"].startswith("era-"):
            codes = [ERAS[pr["id"][4:]][0]]  # tagged with today's franchise (no same-club clash in a daily)
        if sorted(pr.get("tm") or []) != sorted(codes):
            bad(f"{pr['id']}: team tags {pr.get('tm')} vs {codes}")
        for f in ([] if pr["id"].startswith("era-") else codes):  # relocated franchises say which names count
            if team_note.get(f) and team_note[f] not in (pr.get("s") or ""):
                bad(f"{pr['id']}: fine print lacks {team_note[f]!r}")
        k = re.sub(r"^(s|df|ts|c)-", "", pr["id"]).split("-")[0]
        if pr["id"].split("-")[0] in ("s", "df", "ts") and k.startswith(("avg", "era", "triple")):
            if "ualif" not in (pr.get("s") or ""):
                bad(f"{pr['id']}: rate-stat prompt doesn't say it needs a qualified season")
        if pr.get("c") not in APP_CATEGORIES:
            bad(f"{pr['id']}: category {pr.get('c')!r} unknown to the app")

    # --------------------------------------------------------- compare prompts
    checked = Counter()
    for pr in M["prompts"]:
        s = pr["a"]
        got = [((BI[s[i]] << 12) | (BI[s[i + 1]] << 6) | BI[s[i + 2]]) for i in range(0, len(s), 3)]
        got_ids = [IDS[v >> 3] for v in got]
        if len(set(got_ids)) != len(got_ids):
            bad(f"{pr['id']}: duplicate answers")
        try:
            if pr["id"].startswith("mate-"):
                star = mate_star(pr)
                if not star:
                    bad(f"{pr['id']}: can't identify the star from the prompt text")
                    continue
                want = {p for p in players if p != star and info[p]["teams"] & info[star]["teams"]}
            else:
                want = expected(pr["id"])
        except Exception as e:  # noqa: BLE001
            bad(f"{pr['id']}: no independent rule ({e!r})")
            continue
        checked[pr["id"].split("-")[0]] += 1
        have = set(got_ids)
        if have != want:
            extra, missing = have - want, want - have
            def show(xs):
                return ", ".join(f"{M['players'][idx[x]][0]} ({x})" for x in sorted(xs)[:6])
            bad(f"{pr['id']} [{pr['t']}]: {len(extra)} extra [{show(extra)}], {len(missing)} missing [{show(missing)}]")

    print(f"players checked: {len(IDS)}; prompts checked: {sum(checked.values())} of {len(M['prompts'])}")
    print("by family:", dict(sorted(checked.items())))
    if problems:
        print(f"\n{len(problems)} problem(s):")
        for p in problems:
            print("  -", p)
        sys.exit(1)
    print("No differences: every prompt and player matches the independent rules.")


if __name__ == "__main__":
    main()
