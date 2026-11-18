# Moonshot

A daily baseball trivia game built on Krillion's structure, with Immaculate Grid–style prompts. It has seven innings, each with one prompt and one answer. Name any MLB player who fits, but the rarer your correct answer, the farther it flies.

```
Moonshot Daily #1 · 485 ft
⬜🟦🟩🟧❌🟨🟪
Upper deck
```

## How it plays

| Result | Feet | Meaning |
| --- | ---: | --- |
| Bunt | 10 | Everybody's first thought |
| Too Cute | 15 | A "clever" pick that everybody else thought of too (Eddie Gaedel, Bo Jackson, Mike Piazza's 5 games as a Marlin) |
| Single | 30 | Popular, but not the obvious one |
| Double | 60 | A real fan's answer |
| Triple | 85 | A deep cut |
| Home Run | 100 | Almost nobody names this one |
| Strikeout | 0 | Wrong player, a repeat, or the 30-second pitch clock ran out |

- **7 prompts**, one answer each, with a 30-second pitch clock. A perfect game is 700 ft.
- **Daily**: everyone gets the same seven prompts, and a new game starts at local midnight. Game #1 is Nov 18, 2026.
- **Unlimited**: a fresh random game whenever you want one.
- A player can be used only once per game. Autocomplete covers all 24,000+ players, with position and years to tell namesakes apart (Ken Griffey Sr. and Jr.).
- After each inning you see your answer's rank, the most common answers and the home runs you could have hit. The final box score lists every valid answer for each prompt.
- Stats (streak, average, best, tier distribution) are kept in your browser.

## The bank

| | |
| --- | ---: |
| Prompts | **2,410** |
| Valid prompt–player answers | **422,101** |
| Players | **24,011** (all MLB, plus the Negro Leagues that MLB now recognizes) |
| Data through | 2025 season (Hall of Fame through the 2026 class) |

Prompt families:

- **Franchises**: played for a team, both of two teams (all 435 pairs), a team in a given decade, a historical team (Brooklyn Dodgers, Montreal Expos, Seattle Pilots…), or a team's 2025 roster.
- **Franchise ×**: single-season feats (30 HR, 20 W, .300, 30 SV…), awards (MVP, Cy Young, ROY, Gold Glove, Silver Slugger, All-Star, World Series), positions, birthplaces, career milestones, debut team, one-franchise lifers.
- **League-wide**: career milestones (500 HR, 3,000 K, 300/300 club…), single-season feats (50 HR, 40/40, .400…), awards, All-Stars by decade, Hall of Fame cuts, postseason heroics.
- **Origins and oddities**: birth country, state, city and holiday birthdays; height, handedness and played-all-nine-positions; name games (last name is an animal, a color, a job or a president's name; alliterative names; initials).

Franchise prompts count the whole franchise history, so Expos seasons count for the Nationals and Brooklyn seasons for the Dodgers. Every prompt that touches a relocated franchise says so.

## How rarity works

Krillion ranks answers by how many players actually typed them. Moonshot has no crowd yet, so it estimates each answer's *pick share*:

1. **Fame** for every player comes from All-Star selections, MVP/Cy Young/ROY and other awards, the Hall of Fame, milestones and career totals, weighted toward recent players. A short editorial list of icons covers cultural fame the box score can't see (Ruth, Jackie Robinson, Ichiro, Ohtani…).
2. **Association** measures how strongly a player belongs to the prompt: share of career spent with the team, number of qualifying seasons, how recent the feat was.
3. A softmax over `fame / τ + γ·ln(association)` gives each valid answer an estimated share of all fans' guesses. Tiers are cut from those shares (Bunt ≥ 3%, Single ≥ 0.8%, Double ≥ 0.2%, Triple ≥ 0.04%, else Home Run). Truly obscure players get a floor, and famous names on brief stints are flagged **Too Cute**.

Prompts are kept only if at least a few answers are well known (so the prompt is answerable) and at least three are deep cuts (so a big hit is possible).

## Running it

It's a static site, so open `index.html` or serve the folder:

```sh
python3 -m http.server 8000
# then visit http://localhost:8000
```

## Rebuilding the data

```sh
pip install pylahman pyarrow
python tools/build_data.py            # writes data/moonshot-data.js
python tools/build_data.py --report   # plus a calibration report
```

All prompt templates, word lists, the icon list and the tier thresholds live at the top of `tools/build_data.py`.

## Files

```
index.html             page shell
assets/style.css       scoreboard look, light and dark themes
assets/app.js          game logic: daily seeding, pitch clock, autocomplete, scoring, sharing, stats
data/moonshot-data.js  generated prompt and answer bank
tools/build_data.py    data pipeline
```

## Credits

Player data comes from the [Lahman Baseball Database](https://sabr.org/lahman-database/) (SABR), licensed under [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/), via the `pylahman` package. `data/moonshot-data.js` is derived from it and is shared under the same license.
