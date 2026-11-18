#!/usr/bin/env python3
"""
Build Moonshot's question + answer bank (data/moonshot-data.js) from the
Lahman Baseball Database (SABR, CC BY-SA 3.0).

    pip install pylahman pyarrow
    python tools/build_data.py                 # finds pylahman's bundled data
    python tools/build_data.py --data DIR      # or point at a folder of Lahman .parquet files

What it produces
----------------
* players  - every MLB player in the database (name, first/last season, position)
* prompts  - the question bank. Each prompt carries its complete list of valid
             answers, ordered from most to least commonly guessed, with a
             rarity tier per answer.

How rarity is estimated
-----------------------
There is no crowd of past guesses to learn from, so each answer gets an
estimated "pick share": how often a typical fan would name that player for that
prompt. It comes from a fame score (awards, All-Star games, Hall of Fame,
milestones, career totals, and how recently the player was active) weighted by
how strongly the player is associated with the prompt (e.g. share of career
spent with the team). Shares come from a softmax over those weights; tiers are
cut from the shares, like Krillion's crowd-sourced tiers.
"""
import argparse
import json
import math
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import date
from itertools import combinations

import pyarrow.parquet as pq

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

FRANCHISES = {
    "ANA": ("Angels", "Incl. California & Anaheim Angels"),
    "ARI": ("Diamondbacks", None),
    "ATL": ("Braves", "Incl. Boston & Milwaukee Braves"),
    "BAL": ("Orioles", "Incl. St. Louis Browns"),
    "BOS": ("Red Sox", None),
    "CHC": ("Cubs", None),
    "CHW": ("White Sox", None),
    "CIN": ("Reds", None),
    "CLE": ("Guardians", "Incl. Cleveland Indians"),
    "COL": ("Rockies", None),
    "DET": ("Tigers", None),
    "FLA": ("Marlins", "Incl. Florida Marlins"),
    "HOU": ("Astros", "Incl. Houston Colt .45s"),
    "KCR": ("Royals", None),
    "LAD": ("Dodgers", "Incl. Brooklyn Dodgers"),
    "MIL": ("Brewers", "Incl. 1969 Seattle Pilots"),
    "MIN": ("Twins", "Incl. Washington Senators (1901–60)"),
    "NYM": ("Mets", None),
    "NYY": ("Yankees", "Incl. New York Highlanders"),
    "OAK": ("Athletics", "Incl. Philadelphia, Kansas City & Oakland A's"),
    "PHI": ("Phillies", None),
    "PIT": ("Pirates", None),
    "SDP": ("Padres", None),
    "SEA": ("Mariners", None),
    "SFG": ("Giants", "Incl. New York Giants"),
    "STL": ("Cardinals", None),
    "TBD": ("Rays", "Incl. Tampa Bay Devil Rays"),
    "TEX": ("Rangers", "Incl. Washington Senators (1961–71)"),
    "TOR": ("Blue Jays", None),
    "WSN": ("Nationals", "Incl. Montreal Expos"),
}

# Historical team identities: (label, franchise, first year, last year)
ERAS = [
    ("Brooklyn Dodgers", "LAD", 1884, 1957, "Brooklyn, 1884–1957 (incl. Robins & Superbas)"),
    ("New York Giants", "SFG", 1883, 1957, "The NL Giants, 1883–1957"),
    ("Montreal Expos", "WSN", 1969, 2004, "1969–2004"),
    ("St. Louis Browns", "BAL", 1902, 1953, "AL Browns, 1902–53"),
    ("Philadelphia Athletics", "OAK", 1901, 1954, "1901–54"),
    ("Kansas City Athletics", "OAK", 1955, 1967, "1955–67"),
    ("Oakland Athletics", "OAK", 1968, 2024, "1968–2024"),
    ("Boston Braves", "ATL", 1876, 1952, "Incl. Beaneaters, Doves & Bees, through 1952"),
    ("Milwaukee Braves", "ATL", 1953, 1965, "1953–65"),
    ("Washington Senators (1901–60)", "MIN", 1901, 1960, "The original Senators, before the move to Minnesota"),
    ("Washington Senators (1961–71)", "TEX", 1961, 1971, "The expansion Senators, before the move to Texas"),
    ("Seattle Pilots", "MIL", 1969, 1969, "One season only: 1969"),
    ("Houston Colt .45s", "HOU", 1962, 1964, "1962–64"),
    ("Florida Marlins", "FLA", 1993, 2011, "1993–2011"),
    ("Tampa Bay Devil Rays", "TBD", 1998, 2007, "1998–2007"),
    ("California Angels", "ANA", 1965, 1996, "1965–96"),
    ("New York Highlanders", "NYY", 1903, 1912, "The Yankees' original name, 1903–12"),
    ("Cleveland Indians", "CLE", 1915, 2021, "1915–2021"),
]

POS_COLS = ["G_p", "G_c", "G_1b", "G_2b", "G_3b", "G_ss", "G_lf", "G_cf", "G_rf", "G_of", "G_dh"]
POS_LABEL = {"G_p": "P", "G_c": "C", "G_1b": "1B", "G_2b": "2B", "G_3b": "3B", "G_ss": "SS",
             "G_lf": "LF", "G_cf": "CF", "G_rf": "RF", "G_of": "OF", "G_dh": "DH"}
POS_PROMPT = [  # (column, phrase)
    ("G_c", "Played catcher"), ("G_1b", "Played first base"), ("G_2b", "Played second base"),
    ("G_3b", "Played third base"), ("G_ss", "Played shortstop"), ("G_of", "Played the outfield"),
    ("G_dh", "Played DH"),
]

COUNTRIES = {  # Lahman birthCountry -> display
    "D.R.": "the Dominican Republic", "Venezuela": "Venezuela", "Cuba": "Cuba", "P.R.": "Puerto Rico",
    "CAN": "Canada", "México": "Mexico", "Japan": "Japan", "Panama": "Panama", "Ireland": "Ireland",
    "England": "England", "Australia": "Australia", "Germany": "Germany", "Colombia": "Colombia",
    "South Korea": "South Korea", "Taiwan": "Taiwan", "Curaçao": "Curaçao", "Nicaragua": "Nicaragua",
    "U.S. Virgin Islands": "the U.S. Virgin Islands", "Netherlands": "the Netherlands",
    "Italy": "Italy", "Bahamas": "the Bahamas", "Scotland": "Scotland", "Aruba": "Aruba",
}
COUNTRY_ALIASES = {"West Germany": "Germany", "East Germany": "Germany"}

STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "DC": "Washington, D.C.", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts",
    "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
    "VA": "Virginia", "WA": "Washington State", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}

# Word lists for the name prompts. Matching is on the exact last name, so the
# lists stick to plain dictionary words (plus the spelling variants named in
# each prompt's hint) to keep every answer defensible.
WORD_LISTS = {
    "color": ("Last name is a color", "Plain color words; Greene and Grey count — e.g. Brown, White, Rose",
              {"Black", "Blue", "Brown", "Gold", "Gray", "Grey", "Green", "Greene", "Pink", "Red", "Rose",
               "Scarlet", "Silver", "Tan", "White", "Orange", "Violet", "Amber", "Ivory", "Coral",
               "Lavender", "Indigo", "Crimson", "Maroon", "Navy", "Peach", "Plum", "Ruby", "Teal",
               "Lemon", "Cherry", "Copper", "Bronze", "Sage", "Khaki", "Beige", "Magenta", "Cyan",
               "Azure", "Burgundy", "Mauve", "Olive", "Emerald", "Jade", "Rust", "Sable"}),
    "animal": ("Last name is an animal", "Any creature — e.g. Trout, Salmon, Fox, Bird, Martin (the bird)",
               {"Trout", "Salmon", "Bass", "Pike", "Fox", "Wolf", "Bird", "Crane", "Lamb", "Finch",
                "Martin", "Drake", "Hare", "Hart", "Buck", "Crow", "Swan", "Moose", "Hawk", "Hawks",
                "Robin", "Robins", "Wren", "Peacock", "Partridge", "Sparrow", "Lion", "Bear", "Bull",
                "Colt", "Steer", "Mule", "Ram", "Seal", "Fish", "Herring", "Perch", "Mullet", "Sturgeon",
                "Shark", "Whale", "Dove", "Jay", "Lark", "Raven", "Rook", "Eagle", "Falcon", "Owl", "Kite",
                "Teal", "Heron", "Stork", "Quail", "Gull", "Pigeon", "Mouse", "Rabbit", "Badger", "Beaver",
                "Otter", "Mink", "Weasel", "Ferret", "Ox", "Bison", "Buffalo", "Elk", "Deer", "Doe", "Fawn",
                "Stag", "Roe", "Coyote", "Hog", "Boar", "Bunting", "Nightingale", "Starling", "Woodcock",
                "Hen", "Gosling", "Puma", "Cougar", "Panther", "Tiger", "Pony", "Camel", "Bee", "Hornet",
                "Wasp", "Moth", "Spider", "Toad", "Snail", "Haddock", "Pickerel", "Carp", "Bream", "Cod",
                "Marlin", "Snapper", "Grouper", "Mackerel", "Flounder", "Minnow", "Shad", "Plover",
                "Swallow", "Thrush", "Cardinal", "Oriole", "Bull", "Pigg", "Kidd", "Coon", "Gopher",
                "Lynx", "Fowl", "Goose", "Duck", "Crabb", "Wolfe"}),
    "job": ("Last name is a job", "Occupations, old trades included — e.g. Judge, Baker, Cooper, Taylor",
            {"Judge", "Baker", "Miller", "Smith", "Cook", "Carpenter", "Mason", "Taylor", "Fisher",
             "Hunter", "Porter", "Cooper", "Turner", "Butler", "Potter", "Weaver", "Farmer", "Gardner",
             "Gardener", "Shepherd", "Sawyer", "Brewer", "Barber", "Archer", "Carter", "Chandler", "Dyer",
             "Fletcher", "Glover", "Mercer", "Skinner", "Slater", "Tanner", "Wright", "Marshall", "Page",
             "Bishop", "Knight", "Dean", "King", "Fielder", "Banker", "Bowman", "Cartwright", "Wheeler",
             "Painter", "Plumber", "Singer", "Steward", "Thatcher", "Collier", "Draper", "Forester",
             "Granger", "Lawyer", "Miner", "Monk", "Nurse", "Pope", "Priest", "Proctor", "Sergeant",
             "Shoemaker", "Spicer", "Warden", "Constable", "Marshal", "Ranger", "Pilot", "Hatter",
             "Joiner", "Roper", "Trapper", "Cutler", "Deacon", "Pastor", "Doctor", "Teacher", "Trainer",
             "Butcher", "Messenger", "Packer", "Pitcher", "Catcher", "Batter", "Runner", "Boxer",
             "Dancer", "Driver", "Gunner", "Jester", "Mayor", "Poet", "Sheriff", "Skipper", "Sweeper",
             "Teller", "Usher", "Fuller", "Barker", "Carver", "Falconer", "Glazier", "Harper", "Mariner",
             "Mower", "Plowman", "Saddler", "Seaman", "Shearer", "Tinker", "Tiller", "Fiddler", "Piper",
             "Bowyer", "Chancellor", "Governor", "Senator", "Treasurer", "Clerk", "Sailor", "Trucker",
             "Logger", "Rancher", "Waiter", "Cobbler", "Tailor", "Bailiff", "Abbot", "Brewster",
             "Plummer", "Chaplain", "Coach", "Scout", "Batman", "Major", "General", "Colonel", "Captain",
             "Admiral", "Squire", "Steele"}.difference({"Steele"})),
    "president": ("Shares a last name with a U.S. president", "Washington through Trump — e.g. Johnson, Adams, Ford",
                  {"Washington", "Adams", "Jefferson", "Madison", "Monroe", "Jackson", "Van Buren", "Harrison",
                   "Tyler", "Polk", "Taylor", "Fillmore", "Pierce", "Buchanan", "Lincoln", "Johnson",
                   "Grant", "Hayes", "Garfield", "Arthur", "Cleveland", "McKinley", "Roosevelt", "Taft",
                   "Wilson", "Harding", "Coolidge", "Hoover", "Truman", "Eisenhower", "Kennedy", "Nixon",
                   "Ford", "Carter", "Reagan", "Bush", "Clinton", "Obama", "Trump", "Biden"}),
    "calendar": ("Last name is a month or day of the week", "e.g. May, Monday, Sunday",
                 {"January", "February", "March", "April", "May", "June", "July", "August", "September",
                  "October", "November", "December", "Monday", "Tuesday", "Wednesday", "Thursday",
                  "Friday", "Saturday", "Sunday"}),
    "nature": ("Last name is a feature of nature", "Landforms, water, weather, trees — plurals count. e.g. Hill, Rivers, Stone",
               {"Hill", "Hills", "River", "Rivers", "Stone", "Stones", "Wood", "Woods", "Lake", "Lakes",
                "Brook", "Brooks", "Field", "Fields", "Forest", "Glen", "Dale", "Vale", "Valley", "Rock",
                "Rocks", "Shore", "Shores", "Marsh", "Moor", "Heath", "Meadow", "Meadows", "Bank", "Banks",
                "Cliff", "Cliffs", "Clay", "Sand", "Sands", "Pond", "Pool", "Ocean", "Sea", "Bay", "Isle",
                "Island", "Grove", "Groves", "Mountain", "Mountains", "Rain", "Snow", "Frost", "Storm",
                "Storms", "Cloud", "Sky", "Star", "Sun", "Moon", "Winter", "Winters", "Summer", "Summers",
                "Spring", "Springs", "Thorn", "Bush", "Ash", "Oak", "Oaks", "Pine", "Pines", "Birch", "Elm",
                "Rose", "Flower", "Flowers", "Root", "Roots", "Branch", "Leaf", "Reed", "Reeds", "Ridge",
                "Peak", "Hollow", "Canyon", "Creek", "Cove", "Coast", "Beach", "Gale", "Waters", "Wells",
                "Stream", "Dew", "Mist", "Thunder", "Lightning", "Hail", "Earth", "Boulder", "Knoll",
                "Mound", "Bog", "Glade", "Dell", "Marshes", "Fern", "Moss", "Heather", "Willow", "Cedar",
                "Maple", "Hazel", "Holly", "Ivy", "Laurel", "Cypress", "Poplar", "Aspen", "Rainey"}.difference({"Rainey"})),
}

FIRST_NAMES = [  # (label, variants on nameFirst / first given name)
    ("Mike or Michael", {"Mike", "Michael", "Mikey"}),
    ("Bob, Bobby, Rob or Robert", {"Bob", "Bobby", "Rob", "Robbie", "Robby", "Robert"}),
    ("Jim, Jimmy or James", {"Jim", "Jimmy", "Jimmie", "James", "Jamie"}),
    ("Joe, Joey or Joseph", {"Joe", "Joey", "Joseph"}),
    ("Bill, Billy, Will or William", {"Bill", "Billy", "Will", "Willie", "William", "Willy"}),
    ("John, Johnny or Jack", {"John", "Johnny", "Jack", "Jackie", "Jon", "Jonny", "Jonathan"}),
    ("Tom, Tommy or Thomas", {"Tom", "Tommy", "Thomas"}),
    ("Dave or David", {"Dave", "David", "Davey", "Davy"}),
    ("Steve, Steven or Stephen", {"Steve", "Steven", "Stephen", "Stevie"}),
    ("Chris or Christopher", {"Chris", "Christopher", "Kris", "Kristopher"}),
    ("Matt or Matthew", {"Matt", "Matthew", "Matty"}),
    ("Ryan", {"Ryan"}),
    ("Jose", {"Jose", "José"}),
    ("Juan", {"Juan"}),
    ("Luis", {"Luis"}),
    ("Carlos", {"Carlos"}),
    ("Pedro", {"Pedro"}),
    ("Rafael", {"Rafael"}),
    ("Frank, Frankie or Francisco", {"Frank", "Frankie", "Franky", "Francisco", "Francis"}),
    ("Eddie, Ed or Edward", {"Eddie", "Ed", "Edward", "Eddy"}),
    ("Ken, Kenny or Kenneth", {"Ken", "Kenny", "Kenneth"}),
    ("Dan, Danny or Daniel", {"Dan", "Danny", "Daniel"}),
    ("Tony or Anthony", {"Tony", "Anthony", "Antonio"}),
    ("Rick, Ricky, Rich or Richard", {"Rick", "Ricky", "Rich", "Richie", "Richard", "Dick", "Ricardo"}),
    ("Charlie, Chuck or Charles", {"Charlie", "Chuck", "Charles", "Charley"}),
    ("George", {"George"}),
    ("Larry or Lawrence", {"Larry", "Lawrence", "Laurence"}),
    ("Pete or Peter", {"Pete", "Peter"}),
    ("Paul", {"Paul"}),
    ("Kevin", {"Kevin"}),
    ("Jason", {"Jason"}),
    ("Josh or Joshua", {"Josh", "Joshua"}),
    ("Tyler", {"Tyler"}),
    ("Brian or Bryan", {"Brian", "Bryan"}),
    ("Jeff or Jeffrey", {"Jeff", "Jeffrey", "Geoff"}),
    ("Greg or Gregory", {"Greg", "Gregory", "Gregg"}),
    ("Andy or Andrew", {"Andy", "Andrew", "Drew"}),
    ("Alex, Alejandro or Alexander", {"Alex", "Alexander", "Alejandro"}),
    ("Nick or Nicholas", {"Nick", "Nicholas", "Nicky"}),
    ("Zack or Zach", {"Zack", "Zach", "Zachary", "Zac"}),
]

# Players who are famous *because* they were obscure, unusual or briefly
# somewhere: everyone thinks they're a deep cut, so they score "Too Cute".
TOO_CUTE_NAMES = [
    ("Eddie", "Gaedel"), ("Moonlight", "Graham"), ("Bob", "Uecker"), ("Crash", "Davis"), ("Jim", "Abbott"),
    ("Rick", "Ankiel"), ("Mark", "Fidrych"), ("Bo", "Jackson"), ("Deion", "Sanders"), ("Pete", "Gray"),
    ("Jim", "Morris"), ("Joe", "Nuxhall"), ("Chuck", "Connors"), ("Jim", "Thorpe"), ("Mario", "Mendoza"),
    ("Bucky", "Dent"), ("Bill", "Buckner"), ("Mitch", "Williams"), ("Steve", "Blass"), ("Ralph", "Branca"),
    ("Bobby", "Thomson"), ("Don", "Larsen"), ("Harvey", "Haddix"), ("Armando", "Galarraga"),
    ("Kurt", "Bevacqua"), ("Bartolo", "Colon"), ("Jamie", "Moyer"), ("Minnie", "Minoso"),
    ("John", "Rocker"), ("Dock", "Ellis"), ("Bill", "Lee"), ("Hideki", "Irabu"), ("Kei", "Igawa"),
]

# Editorial fame floors for players whose cultural footprint outruns what the
# box-score model can see (pre-All-Star-Game legends, crossover celebrities).
# "First Last:debut year".
ICONS_S = """Babe Ruth:1914, Lou Gehrig:1923, Ty Cobb:1905, Willie Mays:1951, Hank Aaron:1954,
Mickey Mantle:1951, Joe DiMaggio:1936, Ted Williams:1939, Jackie Robinson:1947, Roberto Clemente:1955,
Sandy Koufax:1955, Nolan Ryan:1966, Pete Rose:1963, Derek Jeter:1995, Ken Griffey:1989, Barry Bonds:1986,
Shohei Ohtani:2018, Aaron Judge:2016, Mike Trout:2011, Cy Young:1890, Yogi Berra:1946, Stan Musial:1941,
Honus Wagner:1897, Walter Johnson:1907, Shoeless Joe Jackson:1908, Mariano Rivera:1995, David Ortiz:1997,
Ichiro Suzuki:2001, Albert Pujols:2001, Alex Rodriguez:1994, Cal Ripken:1981, Roger Clemens:1984,
Randy Johnson:1988"""
ICONS_A = """Christy Mathewson:1900, Satchel Paige:1948, Bob Gibson:1959, Johnny Bench:1967, Reggie Jackson:1967,
Rickey Henderson:1979, Tony Gwynn:1982, Greg Maddux:1986, Pedro Martinez:1992, Sammy Sosa:1989,
Mark McGwire:1986, Chipper Jones:1993, Frank Thomas:1990, Clayton Kershaw:2008, Bryce Harper:2012,
Mookie Betts:2014, Tom Seaver:1967, Ernie Banks:1953, Roger Maris:1957, Whitey Ford:1950,
Hank Greenberg:1930, Jimmie Foxx:1925, Rogers Hornsby:1915, Dizzy Dean:1930, Bo Jackson:1986,
Kirby Puckett:1984, George Brett:1973, Mike Schmidt:1972, Ozzie Smith:1978, Ryne Sandberg:1981,
Don Mattingly:1982, Dwight Gooden:1984, Darryl Strawberry:1983, Fernando Valenzuela:1980,
Jose Canseco:1985, Juan Soto:2018, Ronald Acuna:2018, Vladimir Guerrero:2019, Fernando Tatis:2019,
Paul Skenes:2024, Tim Lincecum:2007, Justin Verlander:2005, Max Scherzer:2008, Buster Posey:2009,
Joey Votto:2007, Miguel Cabrera:2003, Manny Ramirez:1993, Jim Thome:1991, Ivan Rodriguez:1991,
Mike Piazza:1992, Jeff Bagwell:1991, Craig Biggio:1988, Johnny Damon:1995, Kris Bryant:2015,
Anthony Rizzo:2011, Francisco Lindor:2015, Jose Altuve:2011, Gerrit Cole:2013, Freddie Freeman:2010,
Bobby Witt:2022, Elly De La Cruz:2023, Cal Raleigh:2021, Pete Alonso:2019, Yadier Molina:2004,
Dustin Pedroia:2006, Josh Hamilton:2007, Carl Yastrzemski:1961, Lefty Grove:1925, Pete Alexander:1911,
Joe Morgan:1963, Rod Carew:1967, Al Kaline:1953, Brooks Robinson:1955, Frank Robinson:1956,
Harmon Killebrew:1954, Eddie Mathews:1952, Warren Spahn:1942, Bob Feller:1936, Duke Snider:1947,
Roy Campanella:1948, Pee Wee Reese:1940, Thurman Munson:1969,
Kirk Gibson:1979, Orel Hershiser:1983, Dennis Eckersley:1975, Omar Vizquel:1989, Roberto Alomar:1988,
Robinson Cano:2005, Andre Dawson:1976, Christy Mathewson:1900, Tris Speaker:1907, Mel Ott:1926,
Jim Palmer:1965, Steve Carlton:1965, Willie McCovey:1959, Willie Stargell:1962, Lou Brock:1961,
Wade Boggs:1982, Paul Molitor:1978, Dave Winfield:1973, Eddie Murray:1977, Tony Perez:1964,
Edgar Martinez:1987, Larry Walker:1989, Todd Helton:1997, Vladimir Guerrero:1996, Bernie Williams:1991,
Jorge Posada:1995, Andy Pettitte:1995, Paul O'Neill:1985, Curt Schilling:1988, Tom Glavine:1987,
John Smoltz:1988, Trevor Hoffman:1993, Bryce Harper:2012, Giancarlo Stanton:2010, Corey Seager:2015,
Jacob deGrom:2014, Zack Greinke:2004, Felix Hernandez:2005, Roy Halladay:1998, Carlos Correa:2015,
Hideki Matsui:2003, Hideo Nomo:1995, Yu Darvish:2012, Josh Gibson:1930, Oscar Charleston:1920,
Buck Leonard:1934, Cool Papa Bell:1922, Ken Griffey:1973, Moises Alou:1990, Felipe Alou:1958"""


def parse_icons(text):
    out = []
    for item in text.replace("\n", " ").split(","):
        item = item.strip()
        if item:
            name, yr = item.rsplit(":", 1)
            out.append((name.strip(), int(yr)))
    return out


TIERS = [
    # key, label, points, max estimated pick share (None = catch-all)
    ("bunt", "Bunt", 10),
    ("cute", "Too Cute", 15),
    ("single", "Single", 30),
    ("double", "Double", 60),
    ("triple", "Triple", 85),
    ("hr", "Home Run", 100),
]
T_BUNT, T_CUTE, T_SINGLE, T_DOUBLE, T_TRIPLE, T_HR = range(6)
# Estimated pick-share thresholds (fraction of all fans' answers)
SHARE_BUNT, SHARE_SINGLE, SHARE_DOUBLE, SHARE_TRIPLE = 0.03, 0.008, 0.002, 0.0004
SOFTMAX_TAU = 9.0   # fame points per e-fold of pick share
ASSOC_GAMMA = 3.0   # how hard prompt association (team share, repeat feats) bends the share

# 2026 Hall of Fame class (elected after the Lahman snapshot was taken).
HOF_2026 = [("Carlos", "Beltran"), ("Andruw", "Jones"), ("Jeff", "Kent")]


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def find_data_dir(arg):
    if arg:
        return arg
    try:
        import importlib.util
        spec = importlib.util.find_spec("pylahman")
        if spec and spec.origin:
            d = os.path.join(os.path.dirname(spec.origin), "data")
            if os.path.isdir(d):
                return d
    except Exception:
        pass
    sys.exit("Could not find Lahman data. `pip install pylahman` or pass --data DIR")


def z(x):
    return x or 0


def ascii_fold(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


class DB:
    def __init__(self, data_dir):
        self.dir = data_dir

    def rows(self, name):
        return pq.read_table(os.path.join(self.dir, name + ".parquet")).to_pylist()


# --------------------------------------------------------------------------
# Load + aggregate
# --------------------------------------------------------------------------

def build(data_dir):
    db = DB(data_dir)
    teams = db.rows("Teams")
    people = {r["playerID"]: r for r in db.rows("People")}
    appearances = db.rows("Appearances")
    batting = db.rows("Batting")
    pitching = db.rows("Pitching")
    awards = db.rows("AwardsPlayers")
    allstar = db.rows("AllstarFull")
    hof = db.rows("HallOfFame")
    batpost = db.rows("BattingPost")
    pitpost = db.rows("PitchingPost")

    franch_of = {}           # (year, teamID) -> franchID
    team_name = {}           # (year, teamID) -> name
    ws_winner = set()        # (year, teamID)
    sched = defaultdict(list)
    for t in teams:
        k = (t["yearID"], t["teamID"])
        franch_of[k] = t["franchID"]
        team_name[k] = t["name"]
        if t["WSWin"] == "Y":
            ws_winner.add(k)
        if t["lgID"] in ("AL", "NL"):
            sched[t["yearID"]].append(t["G"] or 0)
    sched = {y: sorted(g)[len(g) // 2] for y, g in sched.items()}

    # ---- players ---------------------------------------------------------
    P = {}

    def player(pid):
        if pid not in P:
            P[pid] = {
                "id": pid, "years": set(), "G": 0, "fr_G": Counter(), "fr_years": defaultdict(set),
                "pos": Counter(), "fr_pos": defaultdict(Counter), "era_G": Counter(),
                "fr_dec_G": Counter(), "year_fr": defaultdict(Counter),
                "bat": Counter(), "pit": Counter(), "bat_season": {}, "pit_season": {},
                "bat_fr_season": {}, "pit_fr_season": {},
                "awards": [], "allstar": [], "ws": set(), "post": Counter(),
            }
        return P[pid]

    for a in appearances:
        pid = a["playerID"]
        k = (a["yearID"], a["teamID"])
        fr = franch_of.get(k)
        g = z(a["G_all"])
        if g <= 0 and not any(z(a[c]) for c in POS_COLS):
            continue
        p = player(pid)
        y = a["yearID"]
        p["years"].add(y)
        p["G"] += g
        p["fr_G"][fr] += g
        p["fr_years"][fr].add(y)
        p["year_fr"][y][fr] += g
        p["fr_dec_G"][(fr, y // 10 * 10)] += g
        nm = team_name.get(k)
        for era in ERAS:
            if fr == era[1] and era[2] <= y <= era[3]:
                p["era_G"][era[0]] += g
        for c in POS_COLS:
            v = z(a[c])
            if v:
                p["pos"][c] += v
                p["fr_pos"][fr][c] += v
        if k in ws_winner:
            p["ws"].add((y, fr))

    BAT = ["G", "AB", "R", "H", "2B", "3B", "HR", "RBI", "SB", "CS", "BB", "SO", "IBB", "HBP", "SH", "SF"]
    for b in batting:
        pid = b["playerID"]
        if pid not in P:
            continue
        p = P[pid]
        y = b["yearID"]
        fr = franch_of.get((y, b["teamID"]))
        vals = {c: z(b[c]) for c in BAT}
        vals["PA"] = vals["AB"] + vals["BB"] + vals["HBP"] + vals["SH"] + vals["SF"]
        p["bat"].update(vals)
        p["bat_season"].setdefault(y, Counter()).update(vals)
        p["bat_fr_season"].setdefault((y, fr), Counter()).update(vals)
        if b["stint"] == 1:
            p.setdefault("stint1", {})[y] = fr

    PIT = ["W", "L", "G", "GS", "CG", "SHO", "SV", "IPouts", "H", "ER", "HR", "BB", "SO"]
    for r in pitching:
        pid = r["playerID"]
        if pid not in P:
            continue
        p = P[pid]
        y = r["yearID"]
        fr = franch_of.get((y, r["teamID"]))
        vals = {c: z(r.get(c, r.get("IPOuts") if c == "IPouts" else 0)) for c in PIT}
        p["pit"].update(vals)
        p["pit_season"].setdefault(y, Counter()).update(vals)
        p["pit_fr_season"].setdefault((y, fr), Counter()).update(vals)
        if r["stint"] == 1:
            p.setdefault("stint1p", {})[y] = fr

    for r in batpost:
        if r["playerID"] in P:
            p = P[r["playerID"]]
            p["post"]["HR"] += z(r["HR"])
            p["post"]["G"] += z(r["G"])
            if r["round"] == "WS":
                p["post"]["WS_HR"] += z(r["HR"])
                p["post"]["WS_G"] += z(r["G"])
    for r in pitpost:
        if r["playerID"] in P:
            p = P[r["playerID"]]
            p["post"]["W"] += z(r["W"])
            p["post"]["SV"] += z(r["SV"])
            if r["round"] == "WS":
                p["post"]["WS_W"] += z(r["W"])
                p["post"]["WS_SV"] += z(r["SV"])

    def main_franch(p, y):
        c = p["year_fr"].get(y)
        if not c:
            return None
        return c.most_common(1)[0][0]

    for a in awards:
        if a["playerID"] in P:
            p = P[a["playerID"]]
            p["awards"].append((a["awardID"], a["yearID"], main_franch(p, a["yearID"])))
    for a in allstar:
        if a["playerID"] in P:
            fr = franch_of.get((a["yearID"], a["teamID"]))
            P[a["playerID"]]["allstar"].append((a["yearID"], fr))

    # Hall of Fame (players only) + first-ballot detection
    hof_rows = defaultdict(list)
    for h in hof:
        hof_rows[h["playerID"]].append(h)
    for pid, rows in hof_rows.items():
        if pid not in P:
            continue
        ind = [r for r in rows if r["inducted"] == "Y" and r["category"] == "Player"]
        if ind:
            r = ind[0]
            P[pid]["hof"] = r["yearID"]
            bbwaa_years = sorted(x["yearID"] for x in rows if x["votedBy"] == "BBWAA")
            P[pid]["first_ballot"] = (r["votedBy"] == "BBWAA" and bbwaa_years and bbwaa_years[0] == r["yearID"])
    for first, last in HOF_2026:
        cands = [p for p in P.values() if people[p["id"]]["nameFirst"] == first
                 and people[p["id"]]["nameLast"] == last and max(p["years"]) >= 2005]
        for p in cands:
            p["hof"] = 2026
            p["first_ballot"] = False

    # ---- derived per-player fields ---------------------------------------
    for pid, p in P.items():
        pp = people.get(pid, {})
        p["first"] = (pp.get("nameFirst") or "").strip()
        p["last"] = (pp.get("nameLast") or "").strip()
        p["given"] = (pp.get("nameGiven") or "").strip()
        p["name"] = f'{p["first"]} {p["last"]}'.strip()
        p["y0"], p["y1"] = min(p["years"]), max(p["years"])
        d = pp.get("debut")
        p["mlb_debut"] = d.year if d else None
        p["seasons"] = len(p["years"])
        p["country"] = COUNTRY_ALIASES.get(pp.get("birthCountry"), pp.get("birthCountry"))
        p["state"] = pp.get("birthState") if pp.get("birthCountry") == "USA" else None
        p["city"] = pp.get("birthCity")
        p["bmonth"], p["bday"], p["byear"] = pp.get("birthMonth"), pp.get("birthDay"), pp.get("birthYear")
        p["height"], p["weight"] = pp.get("height"), pp.get("weight")
        p["bats"], p["throws"] = pp.get("bats"), pp.get("throws")
        posc = Counter({c: v for c, v in p["pos"].items() if c != "G_of"})
        if not posc and p["pos"].get("G_of"):
            posc["G_of"] = p["pos"]["G_of"]
        top = posc.most_common(2)
        lab = POS_LABEL[top[0][0]] if top else ""
        if (len(top) == 2 and {top[0][0], top[1][0]} & {"G_p"} and top[1][1] >= 0.35 * top[0][1]
                and top[0][1] >= 20):
            lab = "P/" + POS_LABEL[[c for c, _ in top if c != "G_p"][0]]
        p["poslabel"] = lab
        dy = p["mlb_debut"] or p["y0"]
        p["debut_fr"] = (p.get("stint1", {}).get(dy) or p.get("stint1p", {}).get(dy) or main_franch(p, dy))
        aw = Counter(a[0] for a in p["awards"])
        p["aw"] = aw
        p["n_allstar"] = len({y for y, _ in p["allstar"]})
        p["n_ws"] = len(p["ws"])

    compute_fame(P)
    return P, people, sched


# --------------------------------------------------------------------------
# Fame model
# --------------------------------------------------------------------------

def compute_fame(P):
    for p in P.values():
        b, pt, aw = p["bat"], p["pit"], p["aw"]
        v = 0.0
        v += b["H"] / 160 + b["HR"] / 22 + b["SB"] / 90 + b["RBI"] / 400
        v += pt["W"] / 12 + pt["SV"] / 22 + pt["SO"] / 280
        v += p["G"] / 450
        v += 2.6 * p["n_allstar"]
        v += 11 * aw["Most Valuable Player"] + 9 * aw["Cy Young Award"] + 4 * aw["Rookie of the Year"]
        v += 4 * aw["World Series MVP"] + 1.5 * (aw["ALCS MVP"] + aw["NLCS MVP"]) + 1.5 * aw["All-Star Game MVP"]
        v += 0.7 * aw["Gold Glove"] + 0.8 * aw["Silver Slugger"] + 3 * aw["Triple Crown"]
        v += 1.0 * aw["Rolaids Relief Man Award"] + 1.0 * aw["Reliever of the Year Award"]
        v += 6 * (b["HR"] >= 500) + 6 * (b["H"] >= 3000) + 6 * (pt["W"] >= 300) + 4 * (pt["SO"] >= 3000)
        v += 4 * (pt["SV"] >= 400) + 3 * (b["HR"] >= 400)
        y1 = p["y1"]
        rec = (1.4 if y1 >= 2022 else 1.3 if y1 >= 2010 else 1.2 if y1 >= 2000 else 1.05 if y1 >= 1990
               else 0.95 if y1 >= 1975 else 0.85 if y1 >= 1955 else 0.72 if y1 >= 1930 else 0.55)
        v *= rec
        if p.get("hof"):
            v += 22 if y1 >= 1930 else 16
        if y1 >= 2024:
            v += 2.5  # active players are top of mind
        p["fame_raw"] = v
        p["fame"] = 20 * math.log1p(v / 4)
    for tier, (floor, bump) in ((ICONS_S, (80, 3)), (ICONS_A, (70, 1))):
        for name, yr in parse_icons(tier):
            same = [p for p in P.values() if ascii_fold(p["name"]) == name]
            hits = [p for p in same if p.get("mlb_debut") == yr]
            if not hits:
                hits = [p for p in same if p["y0"] - 1 <= yr <= p["y1"]][:1]
            if not hits:
                print("  ! icon not found:", name, yr, file=sys.stderr)
            for p in hits:
                p["fame"] = max(p["fame"], floor) + bump
    ranked = sorted(P.values(), key=lambda p: -p["fame"])
    for i, p in enumerate(ranked):
        p["fame_rank"] = i + 1


# --------------------------------------------------------------------------
# Prompt bank
# --------------------------------------------------------------------------

class Bank:
    def __init__(self, P):
        self.P = P
        self.prompts = []
        self.ids = set()

    def add(self, pid, text, sub, cat, answers, team=None, extra=None, min_n=8):
        """answers: dict playerID -> association multiplier (0..~1.5)."""
        if pid in self.ids:
            raise ValueError("duplicate prompt id " + pid)
        if len(answers) < min_n:
            return False
        self.ids.add(pid)
        self.prompts.append({"id": pid, "text": text, "sub": sub, "cat": cat, "answers": answers,
                             "team": team, "extra": extra or {}})
        return True


def assoc_team(p, fr):
    share = p["fr_G"][fr] / max(p["G"], 1)
    return 0.35 + 0.65 * math.sqrt(min(1.0, share))


def season_bonus(n):
    return min(1.5, 1 + 0.1 * (n - 1))


RECENT_YEAR = 2022  # feats from the last few seasons are top of mind


def recent_bonus(years):
    return 1.4 if years and max(years) >= RECENT_YEAR else 1.0


def qualifies_bat(c, sched_len):
    return c["PA"] >= 3.1 * sched_len


def qualifies_pit(c, sched_len):
    return c["IPouts"] / 3 >= sched_len


def avg(c):
    return c["H"] / c["AB"] if c["AB"] else 0


def era(c):
    ip = c["IPouts"] / 3
    return 9 * c["ER"] / ip if ip else 99


def build_prompts(P, sched):
    bank = Bank(P)
    players = list(P.values())
    FR = list(FRANCHISES)
    tn = {k: v[0] for k, v in FRANCHISES.items()}
    tsub = {k: v[1] for k, v in FRANCHISES.items()}

    by_fr = defaultdict(list)
    for p in players:
        for fr in p["fr_G"]:
            if fr in FRANCHISES:
                by_fr[fr].append(p)

    # ---- 1. Single franchise ------------------------------------------------
    for fr in FR:
        ans = {p["id"]: assoc_team(p, fr) for p in by_fr[fr]}
        bank.add(f"team-{fr}", f"Played for the {tn[fr]}", tsub[fr], "team", ans, team=[fr])

    # ---- 2. Franchise pairs ---------------------------------------------------
    for a, b in combinations(FR, 2):
        ans = {}
        for p in by_fr[a]:
            if p["fr_G"][b] > 0:
                share = (p["fr_G"][a] + p["fr_G"][b]) / max(p["G"], 1)
                ans[p["id"]] = 0.35 + 0.65 * math.sqrt(min(1, share))
        subs = "; ".join(s for s in (tsub[a], tsub[b]) if s) or "Any games for both franchises"
        bank.add(f"pair-{a}-{b}", f"Played for the {tn[a]} and the {tn[b]}", subs, "pair", ans, team=[a, b])

    # ---- 3. Historical identities + decades + current season ---------------
    for label, fr, y0, y1, sub in ERAS:
        ans = {p["id"]: 0.35 + 0.65 * math.sqrt(min(1, p["era_G"][label] / max(p["G"], 1)))
               for p in players if p["era_G"][label] > 0}
        bank.add("era-" + re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-"),
                 f"Played for the {label}", sub, "era", ans, team=[fr])

    for fr in FR:
        decades = sorted({d for (f, d) in (k for p in by_fr[fr] for k in p["fr_dec_G"]) if f == fr})
        for d in decades:
            if d < 1900:
                continue
            ans = {}
            for p in by_fr[fr]:
                g = p["fr_dec_G"][(fr, d)]
                if g > 0:
                    ans[p["id"]] = 0.35 + 0.65 * math.sqrt(min(1, g / max(p["G"], 1)))
            bank.add(f"dec-{fr}-{d}", f"Played for the {tn[fr]} in the {d}s",
                     f"Any game from {d} to {d + 9}" + (f" · {tsub[fr]}" if tsub[fr] else ""),
                     "decade", ans, team=[fr])

    last_year = max(y for p in players for y in p["years"])
    for fr in FR:
        ans = {p["id"]: 0.7 + 0.3 * min(1, p["fr_G"][fr] / max(p["G"], 1))
               for p in by_fr[fr] if last_year in p["fr_years"][fr]}
        bank.add(f"now-{fr}-{last_year}", f"Played for the {tn[fr]} in {last_year}",
                 f"Appeared in at least one game in the {last_year} season", "decade", ans, team=[fr])

    # ---- 4. Franchise × achievement ---------------------------------------
    def fr_seasons(p, fr, kind):
        src = p["bat_fr_season"] if kind == "bat" else p["pit_fr_season"]
        return [(y, c) for (y, f), c in src.items() if f == fr]

    TEAM_SEASON = [
        # key, phrase, kind, predicate(c, sched_len)
        ("hr30", "Hit 30+ home runs in a season for the {t}", "bat", lambda c, s: c["HR"] >= 30),
        ("hr40", "Hit 40+ home runs in a season for the {t}", "bat", lambda c, s: c["HR"] >= 40),
        ("rbi100", "Drove in 100+ runs in a season for the {t}", "bat", lambda c, s: c["RBI"] >= 100),
        ("avg300", "Hit .300+ in a season for the {t}", "bat",
         lambda c, s: qualifies_bat(c, s) and avg(c) >= 0.2995),
        ("h200", "Had 200+ hits in a season for the {t}", "bat", lambda c, s: c["H"] >= 200),
        ("sb30", "Stole 30+ bases in a season for the {t}", "bat", lambda c, s: c["SB"] >= 30),
        ("w15", "Won 15+ games in a season for the {t}", "pit", lambda c, s: c["W"] >= 15),
        ("w20", "Won 20+ games in a season for the {t}", "pit", lambda c, s: c["W"] >= 20),
        ("so200", "Struck out 200+ batters in a season for the {t}", "pit", lambda c, s: c["SO"] >= 200),
        ("sv30", "Saved 30+ games in a season for the {t}", "pit", lambda c, s: c["SV"] >= 30),
        ("sv20", "Saved 20+ games in a season for the {t}", "pit", lambda c, s: c["SV"] >= 20),
        ("era3", "Posted a sub-3.00 ERA in a season for the {t}", "pit",
         lambda c, s: qualifies_pit(c, s) and era(c) < 3.0),
    ]
    SUBS = {"avg300": "Qualified for the batting title (3.1 PA per team game)",
            "era3": "Qualified for the ERA title (1 IP per team game)"}
    for fr in FR:
        for key, phrase, kind, pred in TEAM_SEASON:
            ans = {}
            for p in by_fr[fr]:
                ys = [y for y, c in fr_seasons(p, fr, kind) if pred(c, sched.get(y, 154))]
                if ys:
                    ans[p["id"]] = assoc_team(p, fr) * season_bonus(len(ys)) * recent_bonus(ys)
            bank.add(f"ts-{key}-{fr}", phrase.format(t=tn[fr]), SUBS.get(key, "Single season, with this franchise"),
                     "team-stat", ans, team=[fr])

    TEAM_AWARD = [
        ("mvp", "Most Valuable Player", "Won MVP as a member of the {t}", 5),
        ("cy", "Cy Young Award", "Won the Cy Young as a member of the {t}", 4),
        ("roy", "Rookie of the Year", "Won Rookie of the Year with the {t}", 4),
        ("gg", "Gold Glove", "Won a Gold Glove with the {t}", 8),
        ("ss", "Silver Slugger", "Won a Silver Slugger with the {t}", 8),
    ]
    for fr in FR:
        for key, award, phrase, mn in TEAM_AWARD:
            ans = {}
            for p in by_fr[fr]:
                n = sum(1 for a, y, f in p["awards"] if a == award and f == fr)
                if n:
                    ans[p["id"]] = assoc_team(p, fr) * season_bonus(n)
            bank.add(f"ta-{key}-{fr}", phrase.format(t=tn[fr]),
                     "Award counted for the team he played most for that season", "team-award", ans,
                     team=[fr], min_n=mn)
        # All-Star
        ans = {}
        for p in by_fr[fr]:
            n = len({y for y, f in p["allstar"] if f == fr})
            if n:
                ans[p["id"]] = assoc_team(p, fr) * season_bonus(n)
        bank.add(f"ta-as-{fr}", f"Made an All-Star team as a member of the {tn[fr]}",
                 "Selected to the All-Star Game while on this franchise", "team-award", ans, team=[fr])
        # World Series
        ans = {}
        for p in by_fr[fr]:
            n = sum(1 for y, f in p["ws"] if f == fr)
            if n:
                ans[p["id"]] = assoc_team(p, fr) * season_bonus(n)
        bank.add(f"ta-ws-{fr}", f"Won a World Series with the {tn[fr]}",
                 "Played for the franchise during a championship season", "team-award", ans, team=[fr],
                 min_n=10)
        # Hall of Fame
        ans = {p["id"]: assoc_team(p, fr) for p in by_fr[fr] if p.get("hof")}
        bank.add(f"ta-hof-{fr}", f"Hall of Famer who played for the {tn[fr]}",
                 "Inducted as a player (through the 2026 class)", "team-award", ans, team=[fr], min_n=5)
        # Debut
        ans = {p["id"]: assoc_team(p, fr) for p in by_fr[fr] if p["debut_fr"] == fr}
        bank.add(f"tm-debut-{fr}", f"Made his MLB debut with the {tn[fr]}", "First big-league team",
                 "team-misc", ans, team=[fr])
        # One-franchise career
        ans = {p["id"]: 1.0 for p in by_fr[fr]
               if len([f for f in p["fr_G"] if p["fr_G"][f] > 0]) == 1 and p["seasons"] >= 8}
        bank.add(f"tm-lifer-{fr}", f"Spent his entire career (8+ seasons) with the {tn[fr]}",
                 "Never played a game for another franchise", "team-misc", ans, team=[fr], min_n=5)
        # Birthplace
        ans = {p["id"]: assoc_team(p, fr) for p in by_fr[fr] if p["country"] and p["country"] != "USA"}
        bank.add(f"tb-intl-{fr}", f"Born outside the U.S. and played for the {tn[fr]}",
                 "Puerto Rico counts as outside the 50 states", "team-birth", ans, team=[fr])
        for code, slug in (("D.R.", "dr"), ("Venezuela", "ven"), ("Cuba", "cub"), ("P.R.", "pr"),
                           ("CAN", "can"), ("México", "mex"), ("Japan", "jpn")):
            ans = {p["id"]: assoc_team(p, fr) for p in by_fr[fr] if p["country"] == code}
            bank.add(f"tb-{slug}-{fr}", f"Born in {COUNTRIES[code]} and played for the {tn[fr]}", None,
                     "team-birth", ans, team=[fr], min_n=10)
        for st, stname in (("CA", "California"), ("TX", "Texas"), ("FL", "Florida"), ("NY", "New York"),
                           ("PA", "Pennsylvania"), ("IL", "Illinois"), ("OH", "Ohio")):
            ans = {p["id"]: assoc_team(p, fr) for p in by_fr[fr] if p["state"] == st}
            bank.add(f"tb-{st.lower()}-{fr}", f"Born in {stname} and played for the {tn[fr]}", None,
                     "team-birth", ans, team=[fr], min_n=25)
        # Positions
        for col, phrase in POS_PROMPT:
            ans = {}
            for p in by_fr[fr]:
                g = p["fr_pos"][fr][col]
                if g > 0:
                    ans[p["id"]] = assoc_team(p, fr) * (0.6 + 0.4 * min(1, g / max(1, p["fr_G"][fr])))
            bank.add(f"tp-{col[2:]}-{fr}", f"{phrase} for the {tn[fr]}", "At least one game at the position",
                     "team-pos", ans, team=[fr])
        ans = {p["id"]: assoc_team(p, fr) for p in by_fr[fr] if p["fr_pos"][fr]["G_p"] > 0 and p["throws"] == "L"}
        bank.add(f"tp-lhp-{fr}", f"Left-handed pitcher for the {tn[fr]}", "Threw left, pitched at least one game",
                 "team-pos", ans, team=[fr])
        ans = {p["id"]: assoc_team(p, fr) for p in by_fr[fr]
               if p["fr_pos"][fr]["G_p"] > 0 and p["pos"]["G_p"] < 0.1 * p["G"]}
        bank.add(f"tp-pospitch-{fr}", f"Position player who pitched for the {tn[fr]}",
                 "Mostly a position player, took the mound at least once", "team-pos", ans, team=[fr], min_n=10)
        ans = {p["id"]: assoc_team(p, fr) for p in by_fr[fr] if p["bats"] == "B" and p["fr_pos"][fr]["G_p"] == 0}
        bank.add(f"tp-switch-{fr}", f"Switch-hitter who played for the {tn[fr]}", "Position players only",
                 "team-pos", ans, team=[fr])
        # Career milestones × team
        CM = [
            ("hr300", "300+ career home runs", lambda p: p["bat"]["HR"] >= 300, 5),
            ("h2000", "2,000+ career hits", lambda p: p["bat"]["H"] >= 2000, 8),
            ("w200", "200+ career wins", lambda p: p["pit"]["W"] >= 200, 5),
            ("k2000", "2,000+ career strikeouts (pitching)", lambda p: p["pit"]["SO"] >= 2000, 5),
            ("sv200", "200+ career saves", lambda p: p["pit"]["SV"] >= 200, 4),
            ("avg300", ".300+ career batting average", lambda p: p["bat"]["PA"] >= 3000 and avg(p["bat"]) >= 0.2995, 6),
            ("sb300", "300+ career stolen bases", lambda p: p["bat"]["SB"] >= 300, 5),
        ]
        for key, phrase, pred, mn in CM:
            ans = {p["id"]: assoc_team(p, fr) for p in by_fr[fr] if pred(p)}
            sub = "Career totals across all teams" + (" (min. 3,000 PA)" if key == "avg300" else "")
            bank.add(f"tc-{key}-{fr}", f"{phrase} and played for the {tn[fr]}", sub, "team-career", ans,
                     team=[fr], min_n=mn)

    # ---- 5. Career milestones ---------------------------------------------
    CAREER = [
        ("hr500", "500+ career home runs", lambda p: p["bat"]["HR"] >= 500),
        ("hr400", "400+ career home runs", lambda p: p["bat"]["HR"] >= 400),
        ("hr300", "300+ career home runs", lambda p: p["bat"]["HR"] >= 300),
        ("hr200", "200+ career home runs", lambda p: p["bat"]["HR"] >= 200),
        ("h3000", "3,000+ career hits", lambda p: p["bat"]["H"] >= 3000),
        ("h2500", "2,500+ career hits", lambda p: p["bat"]["H"] >= 2500),
        ("h2000", "2,000+ career hits", lambda p: p["bat"]["H"] >= 2000),
        ("rbi1500", "1,500+ career RBI", lambda p: p["bat"]["RBI"] >= 1500),
        ("r1500", "1,500+ career runs scored", lambda p: p["bat"]["R"] >= 1500),
        ("2b500", "500+ career doubles", lambda p: p["bat"]["2B"] >= 500),
        ("3b150", "150+ career triples", lambda p: p["bat"]["3B"] >= 150),
        ("sb500", "500+ career stolen bases", lambda p: p["bat"]["SB"] >= 500),
        ("sb300", "300+ career stolen bases", lambda p: p["bat"]["SB"] >= 300),
        ("bb1500", "1,500+ career walks (as a hitter)", lambda p: p["bat"]["BB"] >= 1500),
        ("so2000b", "Struck out 2,000+ times as a hitter", lambda p: p["bat"]["SO"] >= 2000),
        ("avg300", ".300+ career batting average (min. 3,000 PA)",
         lambda p: p["bat"]["PA"] >= 3000 and avg(p["bat"]) >= 0.2995),
        ("avg320", ".320+ career batting average (min. 3,000 PA)",
         lambda p: p["bat"]["PA"] >= 3000 and avg(p["bat"]) >= 0.3195),
        ("hr300sb300", "300+ career home runs and 300+ steals",
         lambda p: p["bat"]["HR"] >= 300 and p["bat"]["SB"] >= 300),
        ("hr200sb200", "200+ career home runs and 200+ steals",
         lambda p: p["bat"]["HR"] >= 200 and p["bat"]["SB"] >= 200),
        ("w300", "300+ career wins", lambda p: p["pit"]["W"] >= 300),
        ("w250", "250+ career wins", lambda p: p["pit"]["W"] >= 250),
        ("w200", "200+ career wins", lambda p: p["pit"]["W"] >= 200),
        ("k3000", "3,000+ career strikeouts (pitching)", lambda p: p["pit"]["SO"] >= 3000),
        ("k2500", "2,500+ career strikeouts (pitching)", lambda p: p["pit"]["SO"] >= 2500),
        ("k2000", "2,000+ career strikeouts (pitching)", lambda p: p["pit"]["SO"] >= 2000),
        ("sv300", "300+ career saves", lambda p: p["pit"]["SV"] >= 300),
        ("sv200", "200+ career saves", lambda p: p["pit"]["SV"] >= 200),
        ("sv100", "100+ career saves", lambda p: p["pit"]["SV"] >= 100),
        ("sho40", "40+ career shutouts", lambda p: p["pit"]["SHO"] >= 40),
        ("era3", "Sub-3.00 career ERA (min. 1,000 IP)",
         lambda p: p["pit"]["IPouts"] >= 3000 and era(p["pit"]) < 3.0),
        ("pg800", "Pitched in 800+ games", lambda p: p["pit"]["G"] >= 800),
        ("w100sv100", "100+ career wins and 100+ career saves",
         lambda p: p["pit"]["W"] >= 100 and p["pit"]["SV"] >= 100),
        ("g2500", "Played in 2,500+ games", lambda p: p["G"] >= 2500),
        ("seasons20", "Played 20+ seasons in the majors", lambda p: p["seasons"] >= 20),
        ("decades4", "Played in four different decades", lambda p: len({y // 10 for y in p["years"]}) >= 4),
        ("fr8", "Played for 8+ different franchises", lambda p: len([f for f in p["fr_G"] if p["fr_G"][f]]) >= 8),
        ("fr10", "Played for 10+ different franchises", lambda p: len([f for f in p["fr_G"] if p["fr_G"][f]]) >= 10),
        ("hrp", "Pitcher with 20+ career home runs",
         lambda p: p["pos"]["G_p"] >= 0.8 * p["G"] and p["bat"]["HR"] >= 20),
        ("all9", "Played all nine positions in his career",
         lambda p: all(p["pos"][c] > 0 for c in ("G_p", "G_c", "G_1b", "G_2b", "G_3b", "G_ss"))
         and p["pos"]["G_of"] > 0 and (sum(p["pos"][c] > 0 for c in ("G_lf", "G_cf", "G_rf")) == 3)),
        ("onegame", "Played in exactly one MLB game", lambda p: p["G"] == 1),
        ("lifer15", "Spent 15+ seasons with one franchise and never played elsewhere",
         lambda p: p["seasons"] >= 15 and len([f for f in p["fr_G"] if p["fr_G"][f]]) == 1),
    ]
    for key, text, pred in CAREER:
        ans = {p["id"]: 1.0 for p in players if pred(p)}
        bank.add(f"c-{key}", text, "Regular season, all teams combined", "career", ans,
                 min_n=8 if key not in ("hr500", "w300", "h3000") else 6)

    # ---- 6. Single-season feats -------------------------------------------
    SEASON = [
        ("hr60", "Hit 60+ home runs in a season", "bat", lambda c, s: c["HR"] >= 60),
        ("hr50", "Hit 50+ home runs in a season", "bat", lambda c, s: c["HR"] >= 50),
        ("hr45", "Hit 45+ home runs in a season", "bat", lambda c, s: c["HR"] >= 45),
        ("hr40", "Hit 40+ home runs in a season", "bat", lambda c, s: c["HR"] >= 40),
        ("h220", "Had 220+ hits in a season", "bat", lambda c, s: c["H"] >= 220),
        ("h200", "Had 200+ hits in a season", "bat", lambda c, s: c["H"] >= 200),
        ("rbi140", "Drove in 140+ runs in a season", "bat", lambda c, s: c["RBI"] >= 140),
        ("rbi130", "Drove in 130+ runs in a season", "bat", lambda c, s: c["RBI"] >= 130),
        ("r130", "Scored 130+ runs in a season", "bat", lambda c, s: c["R"] >= 130),
        ("2b50", "Hit 50+ doubles in a season", "bat", lambda c, s: c["2B"] >= 50),
        ("3b20", "Hit 20+ triples in a season", "bat", lambda c, s: c["3B"] >= 20),
        ("3b15", "Hit 15+ triples in a season", "bat", lambda c, s: c["3B"] >= 15),
        ("sb80", "Stole 80+ bases in a season", "bat", lambda c, s: c["SB"] >= 80),
        ("sb60", "Stole 60+ bases in a season", "bat", lambda c, s: c["SB"] >= 60),
        ("sb50", "Stole 50+ bases in a season", "bat", lambda c, s: c["SB"] >= 50),
        ("bb120", "Drew 120+ walks in a season", "bat", lambda c, s: c["BB"] >= 120),
        ("so200b", "Struck out 200+ times in a season as a hitter", "bat", lambda c, s: c["SO"] >= 200),
        ("avg350", "Hit .350+ in a season (qualified)", "bat",
         lambda c, s: qualifies_bat(c, s) and avg(c) >= 0.3495),
        ("avg400", "Hit .400+ in a season (qualified)", "bat",
         lambda c, s: qualifies_bat(c, s) and avg(c) >= 0.3995),
        ("3030", "30 HR / 30 SB season", "bat", lambda c, s: c["HR"] >= 30 and c["SB"] >= 30),
        ("4040", "40 HR / 40 SB season", "bat", lambda c, s: c["HR"] >= 40 and c["SB"] >= 40),
        ("2020", "20 HR / 20 SB season", "bat", lambda c, s: c["HR"] >= 20 and c["SB"] >= 20),
        ("triple3", ".300 / 30 HR / 100 RBI season", "bat",
         lambda c, s: qualifies_bat(c, s) and avg(c) >= 0.2995 and c["HR"] >= 30 and c["RBI"] >= 100),
        ("w25", "Won 25+ games in a season", "pit", lambda c, s: c["W"] >= 25),
        ("w20", "Won 20+ games in a season", "pit", lambda c, s: c["W"] >= 20),
        ("l20", "Lost 20+ games in a season", "pit", lambda c, s: c["L"] >= 20),
        ("so300", "Struck out 300+ batters in a season", "pit", lambda c, s: c["SO"] >= 300),
        ("so250", "Struck out 250+ batters in a season", "pit", lambda c, s: c["SO"] >= 250),
        ("sv50", "Saved 50+ games in a season", "pit", lambda c, s: c["SV"] >= 50),
        ("sv45", "Saved 45+ games in a season", "pit", lambda c, s: c["SV"] >= 45),
        ("sv40", "Saved 40+ games in a season", "pit", lambda c, s: c["SV"] >= 40),
        ("era2", "Sub-2.00 ERA in a season (qualified)", "pit",
         lambda c, s: qualifies_pit(c, s) and era(c) < 2.0),
        ("era2live", "Sub-2.00 ERA in a season since 1920 (qualified)", "pit", None),
        ("cg25", "Threw 25+ complete games in a season", "pit", lambda c, s: c["CG"] >= 25),
        ("sho8", "Threw 8+ shutouts in a season", "pit", lambda c, s: c["SHO"] >= 8),
        ("pg80", "Pitched in 80+ games in a season", "pit", lambda c, s: c["G"] >= 80),
    ]
    for key, text, kind, pred in SEASON:
        ans = {}
        for p in players:
            src = p["bat_season"] if kind == "bat" else p["pit_season"]
            if key == "era2live":
                ys = [y for y, c in src.items() if y >= 1920 and qualifies_pit(c, sched.get(y, 154)) and era(c) < 2.0]
            else:
                ys = [y for y, c in src.items() if pred(c, sched.get(y, 154))]
            if ys:
                ans[p["id"]] = season_bonus(len(ys)) * recent_bonus(ys)
        sub = "Regular season, all teams that year combined"
        if "qualified" in text:
            sub = "Qualified: 3.1 PA per team game" if kind == "bat" else "Qualified: 1 IP per team game"
            text = text.replace(" (qualified)", "")
        bank.add(f"s-{key}", text, sub, "season", ans, min_n=6)

    # ---- 7. Awards --------------------------------------------------------------
    AWARDS = [
        ("mvp", "Most Valuable Player", "Won an MVP award", "Incl. Chalmers (1911–14) and League Awards (1922–29)"),
        ("cy", "Cy Young Award", "Won a Cy Young Award", "1956–present"),
        ("roy", "Rookie of the Year", "Won Rookie of the Year", "1947–present"),
        ("wsmvp", "World Series MVP", "Won World Series MVP", "1955–present"),
        ("lcsmvp", ("ALCS MVP", "NLCS MVP"), "Won an ALCS or NLCS MVP", "1977–present"),
        ("asgmvp", "All-Star Game MVP", "Won All-Star Game MVP", "1962–present"),
        ("gg", "Gold Glove", "Won a Gold Glove", "1957–present"),
        ("gg5", "Gold Glove", "Won 5+ Gold Gloves", "1957–present"),
        ("ss", "Silver Slugger", "Won a Silver Slugger", "1980–present"),
        ("ss5", "Silver Slugger", "Won 5+ Silver Sluggers", "1980–present"),
        ("cpoy", ("Comeback Player of the Year", "TSN Comeback Player of the Year"),
         "Won a Comeback Player of the Year award", "MLB or Sporting News version"),
        ("aaron", "Hank Aaron Award", "Won the Hank Aaron Award", "Top hitter in each league, 1999–present"),
        ("clemente", "Roberto Clemente Award", "Won the Roberto Clemente Award", "1971–present"),
        ("reliever", ("Rolaids Relief Man Award", "Reliever of the Year Award", "Reliever of the Year",
                      "TSN Fireman of the Year", "TSN Reliever of the Year"),
         "Won a Reliever of the Year / Fireman award", "Rolaids, MLB or Sporting News versions"),
        ("tc", ("Triple Crown", "Pitching Triple Crown"), "Won a Triple Crown (batting or pitching)",
         "Led his league in AVG/HR/RBI or W/ERA/K"),
        ("mvp2", "Most Valuable Player", "Won 2+ MVP awards", "Incl. pre-1931 versions"),
        ("cy2", "Cy Young Award", "Won 2+ Cy Young Awards", None),
        ("plat", "Platinum Glove", "Won a Platinum Glove", "2011–present"),
    ]
    for key, award, text, sub in AWARDS:
        names = award if isinstance(award, tuple) else (award,)
        need = 5 if key in ("gg5", "ss5") else 2 if key in ("mvp2", "cy2") else 1
        ans = {}
        for p in players:
            n = sum(p["aw"][a] for a in names)
            if n >= need:
                ans[p["id"]] = season_bonus(n)
        bank.add(f"a-{key}", text, sub, "award", ans, min_n=6)

    ans = {p["id"]: 1 for p in players if p["aw"]["Most Valuable Player"] and p["aw"]["Rookie of the Year"]}
    bank.add("a-mvproy", "Won both Rookie of the Year and MVP", "Not necessarily the same season", "award", ans, min_n=6)
    ans = {p["id"]: 1 for p in players
           if p["aw"]["Most Valuable Player"] and p["country"] and p["country"] != "USA"}
    bank.add("a-mvpintl", "MVP winner born outside the U.S.", None, "award", ans, min_n=6)
    ans = {p["id"]: 1 for p in players if p["aw"]["Cy Young Award"] and p["throws"] == "L"}
    bank.add("a-cylefty", "Left-handed Cy Young winner", None, "award", ans, min_n=6)
    ans = {p["id"]: 1 for p in players if p["aw"]["Cy Young Award"] and p["country"] and p["country"] != "USA"}
    bank.add("a-cyintl", "Cy Young winner born outside the U.S.", None, "award", ans, min_n=6)
    ans = {p["id"]: 1 for p in players if p["aw"]["Gold Glove"] and p["pos"]["G_c"] >= 0.5 * p["G"]}
    bank.add("a-ggc", "Gold Glove-winning catcher", "Primarily a catcher", "award", ans, min_n=6)
    ans = {p["id"]: 1 for p in players if p["aw"]["Gold Glove"] and p["pos"]["G_p"] >= 0.5 * p["G"]}
    bank.add("a-ggp", "Gold Glove-winning pitcher", None, "award", ans, min_n=6)

    # All-Stars
    ans = {p["id"]: season_bonus(p["n_allstar"]) for p in players if p["n_allstar"] >= 10}
    bank.add("as-10", "Made 10+ All-Star teams", None, "allstar", ans)
    ans = {p["id"]: season_bonus(p["n_allstar"]) for p in players if p["n_allstar"] >= 5}
    bank.add("as-5", "Made 5+ All-Star teams", None, "allstar", ans)
    ans = {p["id"]: 1 for p in players if p["n_allstar"] == 1}
    bank.add("as-1", "Made exactly one All-Star team", "One-time All-Stars", "allstar", ans)
    for d in range(1930, 2030, 10):
        ans = {}
        for p in players:
            n = len({y for y, _ in p["allstar"] if d <= y <= d + 9})
            if n:
                ans[p["id"]] = season_bonus(n)
        bank.add(f"as-{d}", f"Made an All-Star team in the {d}s", f"Any selection from {d} to {d + 9}",
                 "allstar", ans)
    for d in range(1930, 2030, 10):
        ans = {}
        for p in players:
            n = sum(1 for a, y, f in p["awards"] if a == "Most Valuable Player" and d <= y <= d + 9)
            if n:
                ans[p["id"]] = season_bonus(n)
        bank.add(f"mvp-{d}", f"Won an MVP in the {d}s", None, "award", ans, min_n=8)

    # Hall of Fame
    hofers = [p for p in players if p.get("hof")]
    bank.add("h-all", "Hall of Famer", "Inducted as a player, through the 2026 class", "hof",
             {p["id"]: 1 for p in hofers})
    bank.add("h-p", "Hall of Fame pitcher", "Primarily a pitcher", "hof",
             {p["id"]: 1 for p in hofers if p["pos"]["G_p"] >= 0.5 * p["G"]})
    for col, nm in (("G_c", "catcher"), ("G_ss", "shortstop"), ("G_2b", "second baseman"),
                    ("G_3b", "third baseman"), ("G_1b", "first baseman"), ("G_of", "outfielder")):
        bank.add(f"h-{col[2:]}", f"Hall of Fame {nm}", f"Played most of his games at {nm.replace('man', '')}".replace(" baseman", " base"),
                 "hof", {p["id"]: 1 for p in hofers if p["pos"][col] >= 0.5 * p["G"]}, min_n=6)
    bank.add("h-fb", "First-ballot Hall of Famer", "Elected by the BBWAA in his first year on the ballot", "hof",
             {p["id"]: 1 for p in hofers if p.get("first_ballot")})
    bank.add("h-intl", "Hall of Famer born outside the U.S.", None, "hof",
             {p["id"]: 1 for p in hofers if p["country"] and p["country"] != "USA"}, min_n=6)
    bank.add("h-2000", "Hall of Famer who played after 2000", "Appeared in a game in 2000 or later", "hof",
             {p["id"]: 1 for p in hofers if p["y1"] >= 2000})
    bank.add("h-pre1930", "Hall of Famer whose career ended before 1930", None, "hof",
             {p["id"]: 1 for p in hofers if p["y1"] < 1930})
    bank.add("h-lhp", "Left-handed Hall of Fame pitcher", None, "hof",
             {p["id"]: 1 for p in hofers if p["pos"]["G_p"] >= 0.5 * p["G"] and p["throws"] == "L"}, min_n=6)
    bank.add("h-nows", "Hall of Famer who never won a World Series", "Never on a championship roster", "hof",
             {p["id"]: 1 for p in hofers if not p["ws"]})

    # World Series / postseason
    bank.add("ws-any", "Won a World Series", "Played for a champion during its title season", "postseason",
             {p["id"]: season_bonus(p["n_ws"]) for p in players if p["n_ws"]})
    bank.add("ws-5", "Won 5+ World Series", None, "postseason",
             {p["id"]: season_bonus(p["n_ws"]) for p in players if p["n_ws"] >= 5})
    bank.add("ws-2fr", "Won World Series titles with two different franchises", None, "postseason",
             {p["id"]: 1 for p in players if len({f for _, f in p["ws"]}) >= 2})
    bank.add("ws-hr", "Homered in a World Series game", None, "postseason",
             {p["id"]: season_bonus(p["post"]["WS_HR"]) for p in players if p["post"]["WS_HR"] > 0})
    bank.add("ws-w", "Won a World Series game as a pitcher", "Credited with the win", "postseason",
             {p["id"]: season_bonus(p["post"]["WS_W"]) for p in players if p["post"]["WS_W"] > 0})
    bank.add("ws-sv", "Saved a World Series game", None, "postseason",
             {p["id"]: 1 for p in players if p["post"]["WS_SV"] > 0})
    bank.add("post-hr10", "Hit 10+ career postseason home runs", None, "postseason",
             {p["id"]: season_bonus(p["post"]["HR"] / 5) for p in players if p["post"]["HR"] >= 10})
    bank.add("ws-never", "Played 15+ seasons and never won a World Series", None, "postseason",
             {p["id"]: 1 for p in players if p["seasons"] >= 15 and not p["ws"]})

    # ---- 8. Birthplaces ---------------------------------------------------------
    intl = [p for p in players if p["country"] and p["country"] != "USA"]
    bank.add("b-intl", "Born outside the United States", "Puerto Rico counts as outside the 50 states", "birth",
             {p["id"]: 1 for p in intl})
    for code, name in COUNTRIES.items():
        bank.add(f"b-{re.sub('[^a-z]', '', ascii_fold(code).lower())}", f"Born in {name}", None, "birth",
                 {p["id"]: 1 for p in players if p["country"] == code}, min_n=6)
    for st, name in STATES.items():
        bank.add(f"b-st-{st.lower()}", f"Born in {name}", "U.S. birth state", "birth",
                 {p["id"]: 1 for p in players if p["state"] == st}, min_n=10)
    cities = Counter((p["city"], p["state"] or p["country"]) for p in players if p["city"])
    for (city, region), n in cities.most_common():
        if n < 40:
            break
        label = city
        if region in STATES and city not in ("New York", "Chicago", "Philadelphia", "Los Angeles", "Boston"):
            label = f"{city}, {STATES[region].replace(' State', '')}"
        elif region in COUNTRIES:
            label = f"{city}, {COUNTRIES[region].replace('the ', '')}"
        bank.add(f"b-city-{re.sub('[^a-z]+', '-', ascii_fold(city + ' ' + region).lower()).strip('-')}",
                 f"Born in {label}", "Birth city", "birth",
                 {p["id"]: 1 for p in players if p["city"] == city and (p["state"] or p["country"]) == region})
    bank.add("b-2000s", "Born in 2000 or later", None, "birth",
             {p["id"]: 1 for p in players if p["byear"] and p["byear"] >= 2000})
    for (m, d, label) in ((12, 25, "Christmas Day"), (7, 4, "the Fourth of July"), (1, 1, "New Year's Day"),
                          (10, 31, "Halloween"), (2, 14, "Valentine's Day"), (2, 29, "Leap Day (Feb. 29)"),
                          (3, 17, "St. Patrick's Day"), (4, 1, "April Fools' Day")):
        bank.add(f"b-day-{m}-{d}", f"Born on {label}", None, "birthday",
                 {p["id"]: 1 for p in players if p["bmonth"] == m and p["bday"] == d})

    # ---- 9. Body + handedness ------------------------------------------------
    bank.add("x-tall", "Listed at 6'8\" or taller", None, "body",
             {p["id"]: 1 for p in players if (p["height"] or 0) >= 80})
    bank.add("x-short", "Listed at 5'6\" or shorter", "Since 1950", "body",
             {p["id"]: 1 for p in players if 0 < (p["height"] or 99) <= 66 and p["y1"] >= 1950})
    bank.add("x-heavy", "Listed at 260+ pounds", None, "body",
             {p["id"]: 1 for p in players if (p["weight"] or 0) >= 260})
    bank.add("x-switch-hr", "Switch-hitter with 200+ career home runs", None, "hand",
             {p["id"]: 1 for p in players if p["bats"] == "B" and p["bat"]["HR"] >= 200})
    bank.add("x-switch-as", "Switch-hitting All-Star", None, "hand",
             {p["id"]: 1 for p in players if p["bats"] == "B" and p["n_allstar"]})
    bank.add("x-lefty-c", "Left-handed thrower who caught a game", "Threw left, appeared at catcher", "hand",
             {p["id"]: 1 for p in players if p["throws"] == "L" and p["pos"]["G_c"] > 0}, min_n=6)
    bank.add("x-lefty-inf", "Left-handed thrower who played 2B, SS or 3B", "Since 1950", "hand",
             {p["id"]: 1 for p in players if p["throws"] == "L" and p["y1"] >= 1950 and
              (p["pos"]["G_2b"] + p["pos"]["G_ss"] + p["pos"]["G_3b"]) > 0}, min_n=6)
    bank.add("x-lhp-200w", "Left-handed pitcher with 200+ career wins", None, "hand",
             {p["id"]: 1 for p in players if p["throws"] == "L" and p["pit"]["W"] >= 200})
    bank.add("x-lhp-sv200", "Left-handed pitcher with 150+ career saves", None, "hand",
             {p["id"]: 1 for p in players if p["throws"] == "L" and p["pit"]["SV"] >= 150}, min_n=6)
    bank.add("x-twoway", "Pitched 10+ games and hit 10+ HR as a position player", "Two-way players, in some sense",
             "misc", {p["id"]: 1 for p in players if p["pos"]["G_p"] >= 10 and
                      sum(p["pos"][c] for c in ("G_c", "G_1b", "G_2b", "G_3b", "G_ss", "G_of", "G_dh")) >= 50
                      and p["bat"]["HR"] >= 10}, min_n=6)
    bank.add("x-teen", "Debuted at age 18 or younger", None, "misc",
             {p["id"]: 1 for p in players if p["byear"] and p["y0"] - p["byear"] <= 18 and p["y0"] >= 1900})
    bank.add("x-old", "Played in the majors at age 45 or older", "By birth year", "misc",
             {p["id"]: 1 for p in players if p["byear"] and p["y1"] - p["byear"] >= 45})

    # ---- 10. Names -----------------------------------------------------------
    def folded_last(p):
        return ascii_fold(p["last"])

    for L in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        ans = {p["id"]: 1 for p in players if folded_last(p).upper().startswith(L)}
        if 8 <= len(ans):
            bank.add(f"n-last-{L}", f"Last name starts with {L}", None, "names", ans)
    for L in "IOQUVXYZ":
        ans = {p["id"]: 1 for p in players if ascii_fold(p["first"]).upper().startswith(L)}
        bank.add(f"n-first-{L}", f"First name starts with {L}", "The name he went by", "names", ans)
    bank.add("n-allit", "Alliterative name", "First and last names start with the same letter (Mickey Mantle)",
             "names", {p["id"]: 1 for p in players if p["first"] and p["last"] and
                       ascii_fold(p["first"])[0].upper() == ascii_fold(p["last"])[0].upper()})
    bank.add("n-short", "Last name of three letters or fewer", "e.g. Ott, Cey", "names",
             {p["id"]: 1 for p in players if 0 < len(re.sub(r"[^A-Za-z]", "", folded_last(p))) <= 3})
    bank.add("n-long", "Last name of 11+ letters", "Spaces and punctuation don't count", "names",
             {p["id"]: 1 for p in players if len(re.sub(r"[^A-Za-z]", "", folded_last(p))) >= 11})
    bank.add("n-z", "Last name contains a Z", None, "names",
             {p["id"]: 1 for p in players if "z" in folded_last(p).lower()})
    bank.add("n-x", "Name contains an X", "First or last name", "names",
             {p["id"]: 1 for p in players if "x" in ascii_fold(p["name"]).lower()})
    bank.add("n-double", "Last name has a double letter", "e.g. Boggs, Puckett", "names",
             {p["id"]: 1 for p in players if re.search(r"(.)\1", folded_last(p).lower())})
    bank.add("n-jr-mc", "Last name starts with Mc or Mac", None, "names",
             {p["id"]: 1 for p in players if re.match(r"(Mc|Mac)[A-Z]", p["last"])})
    bank.add("n-space", "Two-word last name", "e.g. De La Cruz, Van Slyke", "names",
             {p["id"]: 1 for p in players if " " in p["last"]})
    for key, (text, sub, words) in WORD_LISTS.items():
        ans = {p["id"]: 1 for p in players if p["last"] in words}
        bank.add(f"n-w-{key}", text, sub, "names", ans)
    for label, variants in FIRST_NAMES:
        vs = {ascii_fold(v) for v in variants}
        ans = {}
        for p in players:
            first_tok = ascii_fold(p["first"].split(" ")[0]) if p["first"] else ""
            given_tok = ascii_fold(p["given"].split(" ")[0]) if p["given"] else ""
            if first_tok in vs or (given_tok in vs and len(p["first"].split(" ")[0]) > 1):
                ans[p["id"]] = 1
        bank.add("n-f-" + re.sub("[^a-z]+", "-", label.lower()).strip("-"), f"First name: {label}",
                 "The name he went by, or his given first name", "names", ans)
    shared = Counter(p["last"] for p in players)
    bank.add("n-unique", "Only player in MLB history with his last name", None, "names",
             {p["id"]: 1 for p in players if shared[p["last"]] == 1})
    hof_last = {p["last"] for p in hofers}
    bank.add("n-hoflast", "Shares a last name with a Hall of Famer (but isn't one)",
             "e.g. any non-Hall of Fame Ruth, Mays or Aaron", "names",
             {p["id"]: 1 for p in players if p["last"] in hof_last and not p.get("hof")})
    return bank


# --------------------------------------------------------------------------
# Rarity tiers
# --------------------------------------------------------------------------

def assign_tiers(bank, P, too_cute_ids):
    out = []
    for pr in bank.prompts:
        items = []
        for pid, m in pr["answers"].items():
            p = P[pid]
            items.append((p["fame"] / SOFTMAX_TAU + ASSOC_GAMMA * math.log(max(m, 1e-3)), pid))
        items.sort(key=lambda x: (-x[0], P[x[1]]["fame_rank"]))
        mx = items[0][0]
        ws = [math.exp(s - mx) for s, _ in items]
        tot = sum(ws)
        tiers = []
        top_share = ws[0] / tot
        for i, ((s, pid), w) in enumerate(zip(items, ws)):
            share = w / tot
            if share >= SHARE_BUNT or share >= 0.75 * top_share:
                t = T_BUNT
            elif share >= SHARE_SINGLE:
                t = T_SINGLE
            elif share >= SHARE_DOUBLE:
                t = T_DOUBLE
            elif share >= SHARE_TRIPLE:
                t = T_TRIPLE
            else:
                t = T_HR
            p = P[pid]
            # Absolute obscurity floor: in a small pool of unknowns the softmax
            # spreads shares evenly, but naming any of them is still rare.
            if p["fame_rank"] > 10000:
                t = max(t, T_TRIPLE)
            elif p["fame_rank"] > 5000:
                t = max(t, T_DOUBLE)
            if t >= T_DOUBLE:
                famous_cameo = (pr["team"] and p["fame_rank"] <= 150 and
                                min(p["fr_G"][f] for f in pr["team"]) < 0.12 * p["G"])
                if pid in too_cute_ids or famous_cameo:
                    t = T_CUTE
            tiers.append((pid, t, share))
        pr["ranked"] = tiers
        out.append(pr)
    return out


def difficulty(pr, P):
    """1 = easy, 2 = medium, 3 = hard. Based on how many well-known answers exist."""
    fames = sorted((P[pid]["fame"] for pid, _, _ in pr["ranked"]), reverse=True)
    fifth = fames[min(4, len(fames) - 1)]
    if fifth >= 66 or len(fames) >= 400:
        return 1
    if fifth >= 52:
        return 2
    return 3


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", help="Directory with Lahman .parquet files (default: pylahman's bundled data)")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "data", "moonshot-data.js"))
    ap.add_argument("--report", action="store_true", help="Print a calibration report")
    args = ap.parse_args()

    P, people, sched = build(find_data_dir(args.data))

    too_cute = set()
    for first, last in TOO_CUTE_NAMES:
        for p in P.values():
            if p["first"] == first and p["last"] == last:
                too_cute.add(p["id"])

    bank = build_prompts(P, sched)
    prompts = assign_tiers(bank, P, too_cute)

    # Drop prompts with no realistic path to an answer: need some recognizable names.
    kept = []
    for pr in prompts:
        known = sum(1 for pid, _, _ in pr["ranked"] if P[pid]["fame_rank"] <= 4000)
        if known < 3:
            continue  # nobody could name one
        deep = sum(1 for _, t, _ in pr["ranked"] if t >= T_DOUBLE)
        if deep < 3:
            continue  # no room for a rare answer
        pr["diff"] = difficulty(pr, P)
        kept.append(pr)

    # Player table: every player who appears in any answer list or ranks in the
    # fame table, sorted by fame so autocomplete can break ties cheaply.
    order = sorted(P.values(), key=lambda p: p["fame_rank"])
    idx = {p["id"]: i for i, p in enumerate(order)}
    players_out = [[p["name"], p["y0"], p["y1"], p["poslabel"]] for p in order]

    prompts_out = []
    total_answers = 0
    for pr in kept:
        a = [idx[pid] * 8 + t for pid, t, _ in pr["ranked"]]
        total_answers += len(a)
        o = {"id": pr["id"], "t": pr["text"], "c": pr["cat"], "d": pr["diff"], "a": a}
        sub = pr["sub"] or ""
        for fr in pr["team"] or []:  # always say which old team names count
            note = FRANCHISES.get(fr, (None, None))[1]
            if note and note not in sub and pr["cat"] != "era":
                sub = f"{sub} · {note}" if sub else note
        if sub:
            o["s"] = sub
        if pr["team"]:
            o["tm"] = pr["team"]
        prompts_out.append(o)

    meta = {
        "built": date.today().isoformat(),
        "through": max(p["y1"] for p in P.values()),
        "players": len(players_out),
        "prompts": len(prompts_out),
        "answers": total_answers,
        "source": "Lahman Baseball Database (SABR), CC BY-SA 3.0 — via the pylahman package",
    }
    payload = {"meta": meta, "tiers": [{"key": k, "label": l, "pts": pts} for k, l, pts in TIERS],
               "players": players_out, "prompts": prompts_out}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write("/* Generated by tools/build_data.py — do not edit by hand.\n"
                "   Data: Lahman Baseball Database (SABR), licensed CC BY-SA 3.0. */\n")
        f.write("window.MOONSHOT_DATA=")
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
        f.write(";\n")
    print(json.dumps(meta, indent=1))
    print("bytes:", os.path.getsize(args.out))

    if args.report:
        report(kept, P)


REPORT_IDS = ["team-NYY", "pair-BOS-NYY", "c-w300", "s-hr60", "s-hr50", "ts-hr30-CHC", "b-japan",
              "n-w-animal", "tb-dr-NYM", "dec-LAD-1950", "team-FLA", "tp-c-NYM", "a-mvp", "h-all",
              "b-st-wy", "n-last-Q", "pair-CHC-CHW", "ta-cy-ATL", "b-day-12-25", "c-hr500"]


def report(prompts, P):
    cats = Counter(pr["cat"] for pr in prompts)
    print("\nPrompts by category:", dict(cats))
    print("Difficulty:", Counter(pr["diff"] for pr in prompts))
    tier_tot = Counter(t for pr in prompts for _, t, _ in pr["ranked"])
    print("Tier totals:", {TIERS[k][1]: v for k, v in sorted(tier_tot.items())})
    top = sorted(P.values(), key=lambda p: p["fame_rank"])[:60]
    print("\nTop fame:", ", ".join(f'{p["name"]}({p["fame"]:.0f})' for p in top))
    for pid in REPORT_IDS:
        pr = next((x for x in prompts if x["id"] == pid), None)
        if not pr:
            print("\n(missing)", pid)
            continue
        print(f'\n{pr["id"]} — {pr["text"]} — n={len(pr["ranked"])} d={pr["diff"]}')
        by = defaultdict(list)
        for pid2, t, sh in pr["ranked"]:
            by[t].append(f'{P[pid2]["name"]}({sh*100:.1f})')
        for t in range(6):
            if by[t]:
                print(f"  {TIERS[t][1]:>8} [{len(by[t])}]: " + ", ".join(by[t][:14]))


if __name__ == "__main__":
    main()
