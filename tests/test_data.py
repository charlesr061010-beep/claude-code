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

# --- The two bank rules ------------------------------------------------------------
# Every prompt has at least 100 valid answers, and at most 1% of a prompt's
# answers score the maximum (Home Run).
for p in D["prompts"]:
    a = p["a"]
    check(len(a) >= 100, f"{p['id']}: only {len(a)} answers")
    hr = sum(1 for x in a if (x & 7) == 5)
    check(hr <= len(a) // 100, f"{p['id']}: {hr} Home Runs out of {len(a)}")
_all = [x for p in D["prompts"] for x in p["a"]]
check(sum(1 for x in _all if (x & 7) == 5) <= len(_all) / 100, "more than 1% of all answers are Home Runs")

# --- Milestone clubs (career totals through 2025) -------------------------------
# The small clubs are no longer prompts of their own; every member must still
# turn up in the bigger prompt that contains the club.
has("c-hr300", *[
    "Barry Bonds", "Hank Aaron", "Babe Ruth", "Albert Pujols", "Alex Rodriguez", "Willie Mays", "Ken Griffey Jr.",
    "Jim Thome", "Sammy Sosa", "Frank Robinson", "Mark McGwire", "Harmon Killebrew", "Rafael Palmeiro",
    "Reggie Jackson", "Manny Ramirez", "Mike Schmidt", "David Ortiz", "Mickey Mantle", "Jimmie Foxx",
    "Willie McCovey", "Frank Thomas", "Ted Williams", "Ernie Banks", "Eddie Mathews", "Mel Ott",
    "Gary Sheffield", "Eddie Murray", "Miguel Cabrera"])  # the 500-HR club
has("c-w150", *[
    "Cy Young", "Walter Johnson", "Pete Alexander", "Christy Mathewson", "Pud Galvin", "Warren Spahn",
    "Kid Nichols", "Greg Maddux", "Roger Clemens", "Tim Keefe", "Steve Carlton", "John Clarkson",
    "Eddie Plank", "Nolan Ryan", "Don Sutton", "Phil Niekro", "Gaylord Perry", "Tom Seaver",
    "Old Hoss Radbourn", "Mickey Welch", "Tom Glavine", "Randy Johnson", "Lefty Grove", "Early Wynn"])  # 300 wins
has("c-h2000", *[
    "Pete Rose", "Ty Cobb", "Hank Aaron", "Stan Musial", "Tris Speaker", "Derek Jeter", "Cap Anson",
    "Honus Wagner", "Carl Yastrzemski", "Albert Pujols", "Paul Molitor", "Eddie Collins", "Willie Mays",
    "Eddie Murray", "Nap Lajoie", "Cal Ripken Jr.", "Miguel Cabrera", "Adrian Beltre", "George Brett",
    "Paul Waner", "Robin Yount", "Tony Gwynn", "Alex Rodriguez", "Dave Winfield", "Ichiro Suzuki",
    "Craig Biggio", "Rickey Henderson", "Rod Carew", "Lou Brock", "Rafael Palmeiro", "Wade Boggs",
    "Al Kaline", "Roberto Clemente"])  # 3,000 hits
has("c-k1500", "Nolan Ryan", "Randy Johnson", "Clayton Kershaw", "Justin Verlander", "Max Scherzer", "Bob Gibson",
    "Sandy Koufax")
lacks("c-k1500", "Mariano Rivera")              # 1,173 strikeouts
has("c-sv100", "Mariano Rivera", "Trevor Hoffman", "Lee Smith", "Kenley Jansen", "Craig Kimbrel", "Dennis Eckersley")
lacks("c-sv100", "Babe Ruth")
has("c-sb300", "Rickey Henderson", "Lou Brock", "Ty Cobb", "Tim Raines", "Vince Coleman")

# --- Single seasons --------------------------------------------------------------
has("s-hr40", "Aaron Judge", "Cal Raleigh", "Shohei Ohtani", "Roger Maris", "Pete Alonso", "Kyle Schwarber")
lacks("s-hr40", "Tony Gwynn", "Ichiro Suzuki")
has("s-avg350", "Ted Williams", "Rogers Hornsby", "Ty Cobb", "George Sisler", "Josh Gibson", "Tony Gwynn")
lacks("s-avg350", "Mike Trout", "Derek Jeter")  # Jeter's best was .349
has("s-w25", "Denny McLain", "Steve Carlton", "Bob Welch", "Sandy Koufax")
has("s-sv35", "Bobby Thigpen", "Francisco Rodriguez", "Eric Gagne", "Edwin Diaz")

# --- Awards and voting -----------------------------------------------------------------
has("a-mvp", "Shohei Ohtani", "Aaron Judge", "Barry Bonds", "Mike Trout", "Ichiro Suzuki")
lacks("a-mvp", "Derek Jeter", "Tony Gwynn")
has("v-mvp-any", "Derek Jeter", "Tony Gwynn", "Shohei Ohtani")   # vote-getters, not just winners
has("v-cy-any", "Paul Skenes", "Tarik Skubal", "Sandy Koufax", "Eric Gagne")
lacks("v-cy-any", "Babe Ruth")                   # the award began in 1956
has("a-roy", "Paul Skenes", "Derek Jeter", "Jackie Robinson", "Fernando Valenzuela", "Nick Kurtz", "Drake Baldwin")
has("tv-mvp-NYY", "Babe Ruth", "Roger Maris", "Aaron Judge")
has("tpost-LAD", "Sandy Koufax", "Clayton Kershaw", "Fernando Valenzuela", "Yoshinobu Yamamoto")

# --- Hall of Fame (players, through the 2026 class) -----------------------------
has("h-all", "Ichiro Suzuki", "CC Sabathia", "Billy Wagner", "Dick Allen", "Dave Parker", "Carlos Beltran",
    "Andruw Jones", "Jeff Kent", "Josh Gibson", "Babe Ruth", "Ted Williams", "Hank Aaron", "Satchel Paige")
lacks("h-all", "Pete Rose", "Barry Bonds", "Roger Clemens", "Alex Rodriguez", "Shoeless Joe Jackson")
has("hof-ballot", "Barry Bonds", "Roger Clemens", "Dale Murphy")
lacks("hof-ballot", "Mike Trout")                 # still active, so never on a ballot (Rose did get 1992 write-ins)

# --- Franchises and pairs --------------------------------------------------------------
has("pair-BOS-NYY", "Babe Ruth", "Johnny Damon", "Wade Boggs", "Roger Clemens", "Jacoby Ellsbury")
lacks("pair-BOS-NYY", "Derek Jeter", "Ted Williams", "David Ortiz")
has("team-WSN", "Andre Dawson", "Gary Carter", "Juan Soto", "Max Scherzer", "Vladimir Guerrero")
has("team-LAD", "Jackie Robinson", "Sandy Koufax", "Shohei Ohtani", "Roy Campanella")
has("team-OAK", "Rickey Henderson", "Mark McGwire", "Jimmie Foxx")
has("team-BAL", "Cal Ripken Jr.", "Satchel Paige", "George Sisler")   # Browns count for the Orioles
has("team-MIN", "Walter Johnson", "Kirby Puckett")                   # original Senators count for the Twins
has("era-montreal-expos", "Andre Dawson", "Tim Raines", "Pedro Martinez")
lacks("era-montreal-expos", "Juan Soto")
has("ta-ws-LAD", "Shohei Ohtani", "Mookie Betts", "Freddie Freeman", "Sandy Koufax", "Yoshinobu Yamamoto")
has("ta-ws-NYY", "Derek Jeter", "Babe Ruth", "Mariano Rivera")
check("ta-ws-SEA" not in PROMPTS, "Mariners have no title, so no Mariners World Series prompt")
has("ta-pen-TOR", "Vladimir Guerrero Jr.", "Joe Carter")
has("tp-c-NYM", "Mike Piazza", "Gary Carter")
has("dec-LAD-2020", "Shohei Ohtani", "Yoshinobu Yamamoto", "Freddie Freeman", "Mookie Betts")
has("dec-NYY-2020", "Aaron Judge", "Paul Goldschmidt")
has("dec-NYM-2020", "Juan Soto", "Pete Alonso")
lacks("dec-NYM-2020", "Mike Piazza")
has("tm-final-NYY", "Derek Jeter", "Lou Gehrig", "Mariano Rivera", "Alex Rodriguez")
lacks("tm-final-NYY", "Babe Ruth", "Aaron Judge")   # Ruth finished a Brave; Judge is active
has("tm-final-BOS", "David Ortiz", "Ted Williams", "Dennis Eckersley")
has("tx-hr1-NYY", "Babe Ruth", "Derek Jeter", "Aaron Judge")
lacks("tx-hr1-NYY", "Mariano Rivera")

# --- World Series means the modern World Series ----------------------------------------
has("ws-any", "Derek Jeter", "Babe Ruth")
lacks("ws-any", "Ted Williams", "Ken Griffey Jr.", "Ernie Banks", "Tony Gwynn", "Barry Bonds")
has("post-any", "Ted Williams", "Barry Bonds", "Tony Gwynn")    # played in one, never won
lacks("post-any", "Ernie Banks", "Ken Griffey Jr.")              # never reached a World Series

# --- All-Star Game means AL vs NL ---------------------------------------------------------
check(len([k for k in PROMPTS if k.startswith("as-19") or k.startswith("as-20")]) >= 6, "All-Star decade prompts missing")
lacks("as-1930", ("Josh Gibson", None))  # East-West games are not the MLB All-Star Game
has("as-3plus", "Roger Clemens", "Alex Rodriguez", "Reggie Jackson", "Derek Jeter")

# --- Birthplaces -----------------------------------------------------------------------------
has("b-can", "Vladimir Guerrero Jr.", "Larry Walker", "Joey Votto", "Fergie Jenkins")
lacks("b-can", "Freddie Freeman")  # born in California
has("b-dr", ("Vladimir Guerrero", 1996), ("Pedro Martinez", 1992), "David Ortiz", "Juan Soto")
has("b-pr", "Roberto Clemente", "Ivan Rodriguez", "Yadier Molina", "Mike Lowell", "Carlos Correa")
has("b-venezuela", "Omar Vizquel", "Luis Aparicio", "Miguel Cabrera")
has("b-intl", "Shohei Ohtani", "Ichiro Suzuki", "Yoshinobu Yamamoto")
has("b-st-nj", "Derek Jeter", "Mike Trout")

# --- No unrecognized leagues --------------------------------------------------------------------
check(min(p[1] for p in PLAYERS) >= 1876, "a player's first season predates the NL (National Association leak)")

# --- Name games (typed innings) -------------------------------------------------------------------
has("n-w-animal", "Mike Trout", "Tim Salmon", "Kevin Bass", "Nellie Fox")
has("n-w-president", "Reggie Jackson", "Walter Johnson", "Randy Johnson")
check(all(PROMPTS[k].get("ty") for k in PROMPTS if k.startswith(("fin-", "deb-", "n-"))),
      "name-game, debut and last-season prompts are typed innings")

# --- Teammates, managers, leaders, records ---------------------------------------------------------
has("mate-derek-jeter", "Mariano Rivera", "Alex Rodriguez", "Ichiro Suzuki", "Paul O'Neill")
lacks("mate-derek-jeter", "Derek Jeter", "Babe Ruth", "David Ortiz")
has("mate-babe-ruth", "Lou Gehrig", "Tris Speaker")
lacks("mate-babe-ruth", "Joe DiMaggio")       # DiMaggio arrived in 1936, Ruth left after 1935
has("mate-shohei-ohtani", "Mike Trout", "Mookie Betts", "Albert Pujols")
has("mate-vladimir-guerrero-jr", "George Springer", "Bo Bichette")
lacks("mate-vladimir-guerrero-jr", ("Vladimir Guerrero", 1996))   # father, never teammates
has("mate-josh-gibson", "Buck Leonard", "Satchel Paige")
has("m-any", "Yogi Berra", "Joe Torre", "Aaron Boone", "Don Mattingly", "Billy Martin", "Pete Rose")
lacks("m-any", "Joe McCarthy")                 # managed, never played in the majors
has("m-pm", "Pete Rose", "Joe Torre", "Frank Robinson")
has("lead-hr", "Babe Ruth", "Aaron Judge", "Cal Raleigh", "Mike Schmidt", "Ty Cobb")
has("lead-avg", "Tony Gwynn", "Ichiro Suzuki", "Wade Boggs", "Ted Williams")
lacks("lead-avg", "Derek Jeter", "Mike Trout")
has("lead-era", "Babe Ruth", "Sandy Koufax", "Pedro Martinez")
has("rec-w110", "Babe Ruth", "Ichiro Suzuki", "Derek Jeter", "Mookie Betts")
has("rec-l110", ("Yogi Berra", None), "Randy Johnson", "Miguel Cabrera", "Jose Altuve")
lacks("rec-l110", "Mike Trout")
has("pen-2fr", "Babe Ruth", "Willie Mays", "Max Scherzer")
has("fin-2014", "Derek Jeter", "Paul Konerko", "Alfonso Soriano")
has("fin-2016", "David Ortiz", "Alex Rodriguez")
lacks("fin-2016", "Derek Jeter")
has("a-cpoy", "Jacob deGrom")

# --- Found by the independent audit (tools/verify_bank.py) ---------------------------------------
has("v-mvp-top3", "Roberto Alomar", "Manny Ramirez")   # tied for 3rd in the 1999 AL vote: both count
has("tpost-ATL", "Terrance Gore")                      # 2021 NLDS; never a regular-season game for Atlanta
has("ta-ws-ATL", "Terrance Gore")
has("ws-any", "Terrance Gore")
has("tp-switch-CHC", "Ian Happ")                       # a position player, mop-up inning or not
lacks("s-era25", "Cristopher Sanchez", "Bob Lemon")    # 2.50 in the books (2.495 and 2.499 unrounded)
lacks("ts-era35-STL", "Rick Ankiel")                   # 3.50 in 2000
has("n-jr-mc", "Mark McGwire", "Manny Machado")        # the letters, as the prompt says
has("n-hoflast", "Mudcat Grant")                       # Frank Grant, Hall of Fame 2006
has("rec-l110", "Pete Browning")                       # 1889 Louisville (AA) went 27-111
has("tm-debut-CHC", "Cap Anson")                       # 1871-75 NA isn't MLB: his MLB debut was the 1876 Cubs
has("ta-pen-ATL", "Kid Nichols")                       # 1890s Beaneaters pennants count
has("x-teen", "Ty Cobb")                               # 18 years, 255 days
lacks("x-teen", "Juan Soto")                           # 19 at his debut
has("bp-dr-of", "Luis Liberato")                       # 3 games in the OF, 3 at DH: a tie counts
has("b-city-nyc", "Herb Score")                        # born in Rosedale, Queens
has("b-city-los-angeles-ca", "Don Drysdale", "Ryan Braun", "Jered Weaver")  # Van Nuys, Mission Hills, Northridge
has("b-city-boston-ma", "Shano Collins")               # Charlestown
has("b-city-havana-cuba", "Luis Tiant")                # Marianao
has("n-w-food", "Darryl Strawberry")
has("n-w-job", "Jim Abbott")
lacks("n-f-john-johnny-or-jack", "Jonathan Papelbon")  # Jonathan isn't John

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
