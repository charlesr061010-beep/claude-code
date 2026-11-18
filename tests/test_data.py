#!/usr/bin/env python3
"""Fact checks on the generated answer bank (data/moonshot-data.js).

Run:  python tests/test_data.py        (no dependencies)

Each check pins a piece of baseball record that a player could look up, so a
regression in the pipeline (a dropped league, a mis-joined franchise, a bad
qualifier) shows up as a named failure rather than a silently wrong answer.
"""
import json
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data", "moonshot-data.js")


def load():
    text = open(DATA, encoding="utf-8").read()
    start = text.index("window.MOONSHOT_DATA=") + len("window.MOONSHOT_DATA=")
    return json.loads(text[start:text.rindex(";")])


B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
B64_INDEX = {c: i for i, c in enumerate(B64)}


def decode(s):
    return [(B64_INDEX[s[i]] << 12) | (B64_INDEX[s[i + 1]] << 6) | B64_INDEX[s[i + 2]] for i in range(0, len(s), 3)]


D = load()
for _p in D["prompts"]:
    _p["a"] = decode(_p["a"])
PLAYERS = D["players"]
PROMPTS = {p["id"]: p for p in D["prompts"]}
FAILS = []
CHECKS = 0


def pid(name, debut=None):
    """Index of the player called `name` (whose first season is `debut`, if given)."""
    hits = [i for i, p in enumerate(PLAYERS) if p[0] == name and (debut is None or p[1] == debut)]
    if not hits or (debut is not None and len(hits) > 1):
        raise KeyError(f"{name} ({debut}) matched {len(hits)} players")
    return hits[0]  # players are sorted by fame, so a bare name means the famous one


def answers(prompt_id):
    return {a >> 3: a & 7 for a in PROMPTS[prompt_id]["a"]}


def names(prompt_id):
    return sorted(PLAYERS[i][0] for i in answers(prompt_id))


def check(cond, msg):
    global CHECKS
    CHECKS += 1
    if not cond:
        FAILS.append(msg)


def has(prompt_id, *who):
    if prompt_id not in PROMPTS:
        check(False, f"missing prompt {prompt_id}")
        return
    a = answers(prompt_id)
    for w in who:
        try:
            i = pid(*w) if isinstance(w, tuple) else pid(w)
        except KeyError as e:
            check(False, f"{prompt_id}: {e}")
            continue
        check(i in a, f"{prompt_id}: expected {w}")


def lacks(prompt_id, *who):
    if prompt_id not in PROMPTS:
        check(False, f"missing prompt {prompt_id}")
        return
    a = answers(prompt_id)
    for w in who:
        try:
            i = pid(*w) if isinstance(w, tuple) else pid(w)
        except KeyError as e:
            check(False, f"{prompt_id}: {e}")
            continue
        check(i not in a, f"{prompt_id}: did not expect {w}")


def exactly(prompt_id, expected):
    if prompt_id not in PROMPTS:
        check(False, f"missing prompt {prompt_id}")
        return
    got = Counter(names(prompt_id))
    want = Counter(expected)
    check(got == want, f"{prompt_id}: extra {sorted((got - want).elements())}, missing {sorted((want - got).elements())}")


# --- Structure -----------------------------------------------------------------
for p in D["prompts"]:
    a = p["a"]
    check(len(a) == len({x >> 3 for x in a}), f"{p['id']}: duplicate answers")
    check(all(0 <= (x & 7) <= 5 for x in a), f"{p['id']}: bad tier")
    check(all((x >> 3) < len(PLAYERS) for x in a), f"{p['id']}: bad player index")
    check(sum(1 for x in a if (x & 7) >= 3) >= 3, f"{p['id']}: fewer than 3 deep cuts")
    check(p["d"] in (1, 2, 3), f"{p['id']}: bad difficulty")
check(len(PROMPTS) == len(D["prompts"]), "duplicate prompt ids")
check(D["meta"]["answers"] == sum(len(p["a"]) for p in D["prompts"]), "meta answer count")

# --- Milestone clubs (career totals through 2025) -------------------------------
has("c-hr400", *[
    "Barry Bonds", "Hank Aaron", "Babe Ruth", "Albert Pujols", "Alex Rodriguez", "Willie Mays", "Ken Griffey Jr.",
    "Jim Thome", "Sammy Sosa", "Frank Robinson", "Mark McGwire", "Harmon Killebrew", "Rafael Palmeiro",
    "Reggie Jackson", "Manny Ramirez", "Mike Schmidt", "David Ortiz", "Mickey Mantle", "Jimmie Foxx",
    "Willie McCovey", "Frank Thomas", "Ted Williams", "Ernie Banks", "Eddie Mathews", "Mel Ott",
    "Gary Sheffield", "Eddie Murray", "Miguel Cabrera"])  # every 500-HR hitter; the 500 prompt itself has no deep cuts
exactly("c-w300", [
    "Cy Young", "Walter Johnson", "Pete Alexander", "Christy Mathewson", "Pud Galvin", "Warren Spahn",
    "Kid Nichols", "Greg Maddux", "Roger Clemens", "Tim Keefe", "Steve Carlton", "John Clarkson",
    "Eddie Plank", "Nolan Ryan", "Don Sutton", "Phil Niekro", "Gaylord Perry", "Tom Seaver",
    "Old Hoss Radbourn", "Mickey Welch", "Tom Glavine", "Randy Johnson", "Lefty Grove", "Early Wynn"])
exactly("c-h3000", [
    "Pete Rose", "Ty Cobb", "Hank Aaron", "Stan Musial", "Tris Speaker", "Derek Jeter", "Cap Anson",
    "Honus Wagner", "Carl Yastrzemski", "Albert Pujols", "Paul Molitor", "Eddie Collins", "Willie Mays",
    "Eddie Murray", "Nap Lajoie", "Cal Ripken Jr.", "Miguel Cabrera", "Adrian Beltre", "George Brett",
    "Paul Waner", "Robin Yount", "Tony Gwynn", "Alex Rodriguez", "Dave Winfield", "Ichiro Suzuki",
    "Craig Biggio", "Rickey Henderson", "Rod Carew", "Lou Brock", "Rafael Palmeiro", "Wade Boggs",
    "Al Kaline", "Roberto Clemente"])
has("c-k2500", "Nolan Ryan", "Randy Johnson", "Clayton Kershaw", "Justin Verlander", "Max Scherzer", "Bob Gibson")
lacks("c-k2500", "Sandy Koufax", "Dwight Gooden")
has("c-sv300", "Mariano Rivera", "Trevor Hoffman", "Lee Smith", "Kenley Jansen", "Craig Kimbrel", "Dennis Eckersley")
has("c-sb500", "Rickey Henderson", "Lou Brock", "Ty Cobb", "Tim Raines", "Vince Coleman")

# --- Single seasons --------------------------------------------------------------
has("s-hr50", "Aaron Judge", "Cal Raleigh", "Shohei Ohtani", "Roger Maris", "Pete Alonso", "Kyle Schwarber")
lacks("s-hr50", "Hank Aaron", "Lou Gehrig")
has("s-avg400", "Ted Williams", "Rogers Hornsby", "Ty Cobb", "George Sisler", "Josh Gibson")
lacks("s-avg400", "Tony Gwynn", "George Brett")
has("s-w25", "Denny McLain", "Steve Carlton", "Bob Welch", "Sandy Koufax")
has("s-sv50", "Bobby Thigpen", "Francisco Rodriguez", "Eric Gagne", "Edwin Diaz")

# --- Awards -------------------------------------------------------------------------
has("a-mvp", "Shohei Ohtani", "Aaron Judge", "Barry Bonds", "Mike Trout", "Ichiro Suzuki")
lacks("a-mvp", "Derek Jeter", "Tony Gwynn")
has("a-cy", "Paul Skenes", "Tarik Skubal", "Sandy Koufax", "Eric Gagne")
has("a-roy", "Paul Skenes", "Derek Jeter", "Jackie Robinson", "Fernando Valenzuela")
has("a-wsmvp", "Yoshinobu Yamamoto", "Corey Seager", "Derek Jeter")
has("ta-cy-LAD", "Sandy Koufax", "Clayton Kershaw", "Fernando Valenzuela", "Eric Gagne")
lacks("ta-cy-LAD", "Greg Maddux")

# --- Hall of Fame (players, through the 2026 class) -----------------------------
has("h-all", "Ichiro Suzuki", "CC Sabathia", "Billy Wagner", "Dick Allen", "Dave Parker", "Carlos Beltran",
    "Andruw Jones", "Jeff Kent", "Josh Gibson", "Babe Ruth")
lacks("h-all", "Pete Rose", "Barry Bonds", "Roger Clemens", "Alex Rodriguez", "Shoeless Joe Jackson")
has("h-fb", "Derek Jeter", "Ichiro Suzuki", "Ken Griffey Jr.", "Mariano Rivera")
lacks("h-fb", "Bert Blyleven", "Andruw Jones")

# --- Franchises and pairs --------------------------------------------------------------
has("pair-BOS-NYY", "Babe Ruth", "Johnny Damon", "Wade Boggs", "Roger Clemens", "Jacoby Ellsbury")
lacks("pair-BOS-NYY", "Derek Jeter", "Ted Williams", "David Ortiz")
has("team-WSN", "Andre Dawson", "Gary Carter", "Juan Soto", "Max Scherzer", "Vladimir Guerrero")
has("team-LAD", "Jackie Robinson", "Sandy Koufax", "Shohei Ohtani", "Roy Campanella")
has("team-OAK", "Rickey Henderson", "Mark McGwire", "Jimmie Foxx")
has("team-BAL", "Cal Ripken Jr.", "Satchel Paige", "George Sisler")       # Browns count for the Orioles
has("team-MIN", "Walter Johnson", "Kirby Puckett")                   # original Senators count for the Twins
has("era-seattle-pilots", "Jim Bouton", "Tommy Harper")
lacks("era-seattle-pilots", "Robin Yount")
has("era-montreal-expos", "Andre Dawson", "Tim Raines", "Pedro Martinez")
lacks("era-montreal-expos", "Juan Soto")
has("ta-ws-LAD", "Shohei Ohtani", "Mookie Betts", "Freddie Freeman", "Sandy Koufax")
has("ta-ws-CHC", "Kris Bryant", "Anthony Rizzo", "Javier Baez")
has("ta-ws-NYY", "Derek Jeter", "Babe Ruth", "Mariano Rivera")
check("ta-ws-SEA" not in PROMPTS, "Mariners have no title, so no Mariners World Series prompt")
has("tm-lifer-NYY", "Derek Jeter", "Mariano Rivera", "Mickey Mantle", "Lou Gehrig")
lacks("tm-lifer-NYY", "Babe Ruth", "Joe Torre")
has("tb-ven-DET", "Miguel Cabrera")
has("tp-c-NYM", "Mike Piazza", "Gary Carter")

# --- World Series means the modern World Series ----------------------------------------
has("ws-any", "Derek Jeter", "Babe Ruth")
lacks("ws-any", "Ted Williams", "Ken Griffey Jr.", "Ernie Banks", "Tony Gwynn", "Barry Bonds")

# --- All-Star Game means AL vs NL ---------------------------------------------------------
ws_as_prompts = [k for k in PROMPTS if k.startswith("as-19") or k.startswith("as-20")]
check(len(ws_as_prompts) >= 8, "All-Star decade prompts missing")
lacks("as-1930", ("Josh Gibson", None))  # East-West games are not the MLB All-Star Game

# --- Birthplaces -----------------------------------------------------------------------------
has("b-japan", "Shohei Ohtani", "Ichiro Suzuki", "Yoshinobu Yamamoto", "Hideki Matsui")
has("b-can", "Vladimir Guerrero Jr.", "Larry Walker", "Joey Votto", "Fergie Jenkins")
lacks("b-can", "Freddie Freeman")  # born in California
has("b-dr", ("Vladimir Guerrero", 1996), ("Pedro Martinez", 1992), "David Ortiz", "Juan Soto")
has("b-st-nj", "Derek Jeter", "Mike Trout")
has("b-day-12-25", "Rickey Henderson")

# --- No unrecognized leagues --------------------------------------------------------------------
check(min(p[1] for p in PLAYERS) >= 1876, "a player's first season predates the NL (National Association leak)")

# --- Name games -----------------------------------------------------------------------------------
has("n-w-animal", "Mike Trout", "Tim Salmon", "Kevin Bass", "Nellie Fox")
has("n-w-president", "Reggie Jackson", "Walter Johnson", "Randy Johnson")


# --- Newer families ---------------------------------------------------------------------------
has("mate-derek-jeter", "Mariano Rivera", "Alex Rodriguez", "Ichiro Suzuki", "Paul O'Neill")
lacks("mate-derek-jeter", "Derek Jeter", "Babe Ruth", "David Ortiz")
has("mate-babe-ruth", "Lou Gehrig", "Tris Speaker")
lacks("mate-babe-ruth", "Joe DiMaggio")       # DiMaggio arrived in 1936, Ruth left after 1935
has("mate-shohei-ohtani", "Mike Trout", "Mookie Betts", "Albert Pujols")
has("te-cy-BOS", "Roger Clemens", "Pedro Martinez", "Tom Seaver", "John Smoltz")
lacks("te-cy-BOS", "Curt Schilling")           # never won a Cy Young
has("ta-pen-NYM", "Tom Seaver", "Mike Piazza", "Willie Mays")
has("m-NYY", "Yogi Berra", "Joe Torre", "Aaron Boone", "Don Mattingly", "Billy Martin")
lacks("m-NYY", "Joe McCarthy")                # managed, never played in the majors
has("m-pm", "Pete Rose", "Joe Torre", "Frank Robinson")
has("m-ws", "Joe Torre", "Dusty Baker", "Lou Piniella", "Mike Scioscia")
has("lead-hr", "Babe Ruth", "Aaron Judge", "Cal Raleigh", "Mike Schmidt", "Ty Cobb")
has("lead-avg", "Tony Gwynn", "Ichiro Suzuki", "Wade Boggs", "Ted Williams")
lacks("lead-avg", "Derek Jeter", "Mike Trout")
has("lead-era", "Babe Ruth", "Sandy Koufax", "Pedro Martinez")
has("lead-sv", "Mariano Rivera", "Trevor Hoffman", "Bruce Sutter")
lacks("lead-sv", "Cy Young", "Christy Mathewson", "Satchel Paige")
has("bp-pr-c", "Ivan Rodriguez", "Yadier Molina", "Jorge Posada", "Benito Santiago")
has("bp-venezuela-ss", "Omar Vizquel", "Luis Aparicio", "Dave Concepcion")
has("ap-gg-ss", "Ozzie Smith", "Derek Jeter", "Omar Vizquel")
lacks("ap-gg-ss", "Honus Wagner")         # Gold Gloves began in 1957
has("rec-w110", "Babe Ruth", "Ichiro Suzuki", "Derek Jeter", "Mookie Betts")
has("rec-l110", ("Yogi Berra", None), "Randy Johnson", "Miguel Cabrera", "Jose Altuve")
lacks("rec-l110", "Mike Trout")
has("df-hr40-1990", "Ken Griffey Jr.", "Mark McGwire", "Brady Anderson")
lacks("df-hr40-1990", "Hank Aaron")

# --- Franchise leaders, ten-year men, multi-franchise honors ------------------------------------
has("tl-hr-NYY", "Babe Ruth", "Roger Maris", "Wally Pipp", "Graig Nettles", "Aaron Judge")
lacks("tl-hr-NYY", "Derek Jeter")
has("tl-so-LAD", "Sandy Koufax", "Clayton Kershaw", "Hideo Nomo")
has("tm-ten-CHC", "Ernie Banks", "Ryne Sandberg", "Greg Maddux")
lacks("tm-ten-CHC", "Kris Bryant")             # seven seasons as a Cub
has("as-3fr", "Roger Clemens", "Alex Rodriguez", "Reggie Jackson")
lacks("as-3fr", "Derek Jeter")
has("pen-2fr", "Babe Ruth", "Willie Mays", "Max Scherzer")
has("mate-vladimir-guerrero-jr", "George Springer", "Bo Bichette")
lacks("mate-vladimir-guerrero-jr", ("Vladimir Guerrero", 1996))   # father, never teammates
has("mate-josh-gibson", "Buck Leonard", "Satchel Paige")

# --- Career bookends, birthplace honors, Hall of Famers by state ---------------------------------
has("tm-final-NYY", "Derek Jeter", "Lou Gehrig", "Mariano Rivera", "Alex Rodriguez")
lacks("tm-final-NYY", "Babe Ruth", "Aaron Judge")   # Ruth finished a Brave; Judge is active
has("tm-final-BOS", "David Ortiz", "Ted Williams", "Dennis Eckersley")
has("fin-2014", "Derek Jeter", "Paul Konerko", "Alfonso Soriano")
has("fin-2016", "David Ortiz", "Alex Rodriguez")
lacks("fin-2016", "Derek Jeter")
has("h-st-ca", "Ted Williams", "Joe DiMaggio", "Tony Gwynn", "Jeff Kent", "CC Sabathia")
has("h-st-al", "Hank Aaron", "Willie Mays", "Satchel Paige", "Ozzie Smith")
has("bh-pr-ws", "Roberto Clemente", "Mike Lowell", "Carlos Correa")
has("bh-japan-as", "Shohei Ohtani", "Ichiro Suzuki", "Hideo Nomo")
check(all(PROMPTS[k].get("ty") for k in PROMPTS if k.startswith(("fin-", "deb-", "n-"))),
      "name-game, debut and last-season prompts are typed innings")

# --- The 2025 season (the newest, most error-prone data) ------------------------------------------
has("a-roy", "Nick Kurtz", "Drake Baldwin")
has("ta-mvp-NYY", "Aaron Judge")
has("ta-ws-LAD", "Yoshinobu Yamamoto", "Shohei Ohtani")
has("ta-pen-TOR", "Vladimir Guerrero Jr.", "Joe Carter")
has("a-cpoy", "Jacob deGrom")
has("now-LAD-2025", "Shohei Ohtani", "Yoshinobu Yamamoto", "Freddie Freeman", "Mookie Betts")
has("now-NYY-2025", "Aaron Judge", "Paul Goldschmidt")
has("now-NYM-2025", "Juan Soto", "Pete Alonso")
lacks("now-NYM-2025", "Jacob deGrom")

# --- Tier sanity ---------------------------------------------------------------------------------
for p in D["prompts"]:
    tiers = [x & 7 for x in p["a"]]
    first_real = next((t for t in tiers if t != 1), None)
    check(first_real == 0, f"{p['id']}: most common non-Too-Cute answer should be a Bunt")
    check(any(t == 0 for t in tiers), f"{p['id']}: has no Bunt")

print(f"{CHECKS} checks, {len(FAILS)} failures")
for f in FAILS:
    print("  FAIL:", f)
sys.exit(1 if FAILS else 0)
