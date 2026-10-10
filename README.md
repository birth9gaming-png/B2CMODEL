# Football Model Lab

An editable academic NFL and CFB score model, a searchable Streamlit dashboard,
and explicit-refresh data connectors. Python 3.11 or 3.12 is recommended.

## Start here

Start the Streamlit app locally or update your existing deployment as described
below. It starts with the **11-game, October 10, 2026 research snapshot**, now
supplemented with dated FEI ratings and prior NFL meetings.
Changing weights recomputes every loaded game. Select a matchup for its math,
all quoted markets, FEI/roster/history contributions, and injury/weather/line scenarios. Use **Data & setup** to
edit any team statistic or the complete input JSON. Export keeps your settings.

The earlier private web dashboard computes the original model in your browser;
it does not implement the new Streamlit FEI, roster, history, schedule-context or calibration terms.
It does **not** automatically
download new statistics or odds. Its JSON import accepts larger slates exported
by this Python application, but its calculations use the original formula.
Use this Streamlit version for the expanded model.

## Update an existing Streamlit deployment

Extract the updated ZIP. In GitHub, open the folder containing your current
`app.py` and upload the **contents** of the extracted `football_dashboard` folder
there. Replace the existing files and include `cfb_metrics.py`, `matchup_history.py`,
`calibration.py` and the new `schedule_context.py`. Commit on the deployed branch;
Streamlit loads the update. The version display should read **Prototype 04**.
The theme contrast fix is included. Keep `.streamlit/config.toml` at the repository
root if you want the custom green theme.

## FEI, returning starters and transfer portal ratings

CFB uses separate offensive and defensive FEI ratings, not ranks or an overall
FEI value added on top of those ratings. Positive OFEI is a better offense;
positive DFEI is a better defense. The source units are scoring advantage per
non-garbage possession. With original efficiency forecast `C`, pace factor `F`,
baseline per-team points `q`, and reference possessions `D0`:

```text
FEI forecast_i = F*q + F*D0*(OFEI_i - DFEI_opponent)
Blended forecast_i = (1-w)*C_i + w*FEI forecast_i
d_i = 2^(-games_played_i / half_life)
Returning adjustment_i = bStarter * [d_i*(off_starters_i-reference)
                                    - d_opponent*(def_starters_opponent-reference)]
Portal away adjustment = bPortal * (d_away*net_away - d_home*net_home)/(2*portal_scale)
Portal home adjustment = -Portal away adjustment
```

Defaults are **instructional priors**: 25% FEI blend, 12 reference possessions,
0.20 points per extra returning starter relative to six per unit, one portal
point per five native rating units, and a four-game roster half-life. A roster
term has 100% weight at zero games, 50% at four, and 25% at eight. Adjust these
in the CFB sidebar. These values are not claimed to improve historical accuracy.
The FEI conversion is a modeling assumption bridging non-garbage ratings and
final scores; validate the possession scale and baseline on held-out games.

- Weekly CFB refresh downloads the public BCF Toys FEI table. Its season and
  through-week must be identifiable. Ratings newer than the feature cutoff are
  rejected. Missing or mismatched team ratings disable the game's FEI blend.
- The bundled October 10 example includes actual public OFEI/DFEI values for
  its ten CFB teams, through week 5, with source metadata. It contains no
  invented returning-starter counts or transfer ratings.
- **Returning starters:** enter separate verified offense/defense counts, each
  0–11, under **Edit FEI and roster inputs**. Returning production and returning
  starters are different quantities; the app does not convert one into the other.
- **Portal:** the CFBD key loads `/player/portal`. The app sums native individual
  ratings incoming minus outgoing for dated, confirmed, immediately eligible
  transfers before the first regular-season game. Duplicates and withdrawn
  entries are excluded. A missing rating, transfer date or unresolved eligibility
  makes the affected team's aggregate unavailable; partial totals are not used.
  This is a talent proxy, not a fitted player-impact or position-specific score.
- Automatic feeds supply games played where statistics are complete. You can
  override that count. Roster season must match the forecast season; missing
  games played skips roster adjustments. Both teams need a portal rating.
- **Data & setup** shows input coverage and supports a separate team-keyed CFB
  JSON import/template. Full snapshot export keeps all inputs and overrides.
  Blank/null template fields preserve existing values; the team editor can clear
  a field explicitly.
  Manual starter/portal overrides survive same-season slate refreshes. Games
  played advances with the new statistics, and other-season overrides expire.
  Manual FEI overrides keep their through-week until explicitly refreshed.

FEI overlaps with the original efficiency metrics, and its preseason priors may
already incorporate roster information. The blend and fading roster residuals
limit unrestrained duplication but do not eliminate it; fit the features jointly
and test whether roster terms add information beyond FEI.

Sources: <https://bcftoys.com/2026-fei>,
<https://bcftoys.com/glossary>,
<https://api.collegefootballdata.com/api/players>.

## Head-to-head history and underdog concentration

Schedule refresh loads completed meetings from up to five prior seasons plus
eligible earlier games in the current season. NFL uses public nflverse schedules;
CFB uses the CFBD `/games` endpoint and key. Only meetings before the forecast
game are eligible. Games are reoriented to the current away team and their margins
approximately adjusted for historical home field. New rosters and coaches limit
how much these older meetings can tell us about the next game.

Age weights use a two-year half-life. Their summed weight `n` is shrunk by
`n/(n+8)`. Default history contribution is only 10% of the difference between
the age-weighted historical forecast and the current forecast, capped at ten
points before blending. It can adjust margin and total. Missing history contributes
zero, and coverage is shown. The initial example has 20 verified prior NFL meetings;
CFB history is populated with a CFBD refresh.

The original 11-game example had **seven underdog spread leans**. Model margin
standard deviations were 5.55 versus market 7.05 in CFB, and 4.28 versus 5.66 in
NFL. This is a compression diagnostic on a tiny slate, not proof that every
underdog signal is wrong or that an arbitrary larger scale is correct.

The explorer now has favorite/underdog filters and a minimum conditional EV
threshold; it does not force a favorite into the rankings. **Calibration
diagnostics** shows side counts, quote-specific selections, and model-versus-market
margin spread. Scores and individual metric contributions remain visible for
every game, even when no market clears the threshold.

For a supported correction, use **Archive current pregame forecasts** before
kickoff. Combine those archive JSON files into one `forecasts` array. After games
finish, refresh the relevant dates and import the archive; available results are
joined by league/game ID. Missing results can be filled from verified final scores.
The calibration tool requires at least 80 distinct completed games per league,
matching model settings, and timestamps proving predictions precede kickoff.

It fits margin/total scale and intercept to older games using least squares,
then evaluates the later 25% of games, with kickoff groups kept together and at
least 50 training plus 20 holdout games. Postgame forecasts and mismatched settings
are excluded. Only corrections reducing later-game RMSE can be applied. Market
lines are not a training target. Known venue/rest/injury/weather adjustments retain
their point units; calibration scales team-strength/efficiency terms. This prevents
the app from merely changing weights until favorites appear. Repeated use of the
same validation set can overfit it; keep a final untouched test set as well.

Historical results alone are not archived pregame predictions. The package
does not reconstruct past features from current season-end data to manufacture
a backtest. The current sample is too small to fit or validate these corrections.

## Look-ahead, major wins and road losses followed by home games

Schedule refresh retains current-season schedules/results for the loaded teams.
NFL uses its public schedule feed; CFB uses the same CFBD key. The frozen example
has no current-game kickoff timestamps, so refresh schedules for automatic flags.
The model identifies the immediate previous and next game, not a selected earlier
win or a major game several fixtures ahead. Only completed prior results at or
before the feature-week cutoff are used. Future scores never enter these signals.

- **Look-ahead:** the next game is major, within ten calendar days, and the
  current opponent is below the major threshold. A current major game blocks the
  automatic flag. Games after a bye usually fall outside this default window.
- **Major win:** the immediately preceding completed game was a win over a
  major opponent within the same window. Winning margin, opponent and venue
  are shown. A tie/loss cannot be automatically treated as a major win.
- **Road loss then home:** the immediately preceding completed game was a loss
  at the opponent's home venue, and the current game is at home within the window.
  Neutral-site games and longer gaps do not receive the automatic boost.

The automatic major-opponent proxy is neutral strength above an average team
at reference pace: `shrink * [bY*(y-dy)+bS*(s-ds)+bX*(x-dx)]/2`. For CFB it blends
that value with `reference possessions * (OFEI+DFEI)` when the dated FEI inputs
are eligible. Default major thresholds are 4 points for NFL and 8 for CFB.
This is a frozen statistical proxy, not a published ranking or proof of game
importance. Newer opponent features are rejected. Rivalries and other important
matchups can be tagged explicitly with `major_game: true` in schedule JSON, or
handled with the per-game manual flags in **Edit schedule context**.

With signals `L` (look-ahead), `W` (major win), and `R` (road loss then home):

```text
ΔMargin = clip(bL*(Laway-Lhome) + bW*(Waway-Whome) + bR*(Raway-Rhome), -cap, cap)
ΔTotal = clip(tL*(Laway+Lhome) + tW*(Waway+Whome), -cap, cap)
Away score adjustment = (ΔMargin+ΔTotal)/2
Home score adjustment = (ΔTotal-ΔMargin)/2
```

The road-loss return-home coefficient starts at **+0.5 margin points** at your
request. That adds 0.25 to the home score and removes 0.25 from the away score;
it leaves the total unchanged and is separate from normal home field. This is
a provisional scenario assumption, not a historically established bounce effect.
Look-ahead and major-win margin/total weights start at zero. Negative margin
effects test a penalty/letdown; positive ones test improved performance. Separate
total coefficients avoid assuming every situational margin effect changes the
total. Each combined effect is capped at two points by default.

Adjust the league's weights, importance threshold, time window and cap in the
sidebar. The slate and matchup breakdown show flags, dates, opponents, sources
and exact score contributions. Unknown context is displayed and contributes zero.
Manual On/Off overrides and notes are retained in the full JSON export. Known
previous losses cannot be overridden as wins. Schedule-context points are not
multiplied by margin/total calibration slopes. Keep pregame archives and validate
whether these signals add information after home field, rest and team efficiency.

Sources: <https://nflreadr.nflverse.com/reference/load_schedules.html>,
<https://api.collegefootballdata.com/api/games>.

## Run the Python dashboard

Extract this ZIP into a folder. Open a terminal in that folder and run:

```bash
python -m venv .venv
```

Activate it on Windows:

```powershell
.venv\Scripts\Activate.ps1
```

Or on macOS/Linux:

```bash
source .venv/bin/activate
```

Install and launch:

```bash
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Open the local address printed by Streamlit. This is an application, so do not
upload `app.py` through Colab's **Upload notebook** menu. That menu expects JSON
in an `.ipynb` file; a Python script beginning with `#!` produces the reported
JSON parsing error.

## Host it without running your laptop

1. Create a GitHub repository and upload the extracted project files. Preserve
   the folder structure; do not upload only the ZIP.
2. At <https://share.streamlit.io/>, select **Create app** and your repository.
3. Set the entrypoint to `app.py` if the files are at the repository root, or
   `football_dashboard/app.py` if you uploaded the whole folder. Choose Python
   3.12, then deploy.
4. Set the application's audience/access settings for your intended viewers.
5. Add provider keys in Streamlit's **Advanced settings → Secrets**, or enter
   them in the dashboard's password fields for the current session.

Secret names:

```toml
CFBD_API_KEY = "your CollegeFootballData key"
ODDS_API_KEY = "your The Odds API key"
```

Use a local `.streamlit/secrets.toml` when running locally. That file and the
cache are ignored by Git. Do not put real keys in the repository, exported
snapshots, or browser dashboard JSON. The data pipeline never exports keys.

Official deployment instructions:
<https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy>

### Display theme

The interface follows Streamlit's selected theme, including dark mode. Custom
CSS adjusts spacing and borders without forcing foreground or background colors.
This keeps headings, captions, metrics, sidebar controls, and tables readable.

The included `.streamlit/config.toml` supplies a green light theme. For Community
Cloud, put `.streamlit/config.toml` at the **repository root**, even when `app.py`
is in `football_dashboard/`. Configuration next to a nested entrypoint is not
loaded by Community Cloud. The app remains readable without this configuration.

This expanded version imports new Python modules. Replace the full application
folder contents as described above, including `app.py`, and commit to the
deployed branch. Community Cloud picks up that commit. Refresh the app;
if necessary, use **Manage app → Reboot app**.

## Load the full date window

In **Data & setup**, choose a season, first and last date, and leagues, then
select **Refresh schedules, statistics and odds**. A first NFL download may
take time. Subsequent pulls reuse cached data. Sliders do not make API calls.

| Source | Purpose | Access |
| --- | --- | --- |
| nflverse | NFL schedules and eligible prior-week play-by-play | Public download; no key |
| CollegeFootballData | CFB schedules, prior-week advanced statistics, team box scores and name aliases | CFBD key; endpoint access/quota depend on your plan |
| The Odds API | NFL/CFB individual book spreads, totals and American odds | Odds API key; access/quota depend on your plan |

The CFBD adapter covers regular-season games involving FBS teams. NFL refresh
covers regular-season schedules. Postseason and a complete FCS-only slate need
additional schedule/filter configuration. A date window can contain completed
games; those remain visible and may have no current quotes. First-week teams
have no current-season sample, so supply preseason inputs rather than treating
them as league-average teams without evidence.

The pipeline uses statistics through the week **before the earliest game week
in the selected window**. This conservative cutoff prevents the forecast
week's outcomes from entering its features. For windows spanning multiple
weeks, later games deliberately use the same earlier cutoff; refresh each week
for newer information.

The window is interpreted in America/New_York. Injury, weather, unusual travel,
and extra-rest point modifiers are manual and are marked unverified on new
data pulls. The current turnover feature is regressed net observed turnovers;
an empirical fumble-luck decomposition is not implemented.

Games with missing team inputs remain in the table. Scores are withheld until
the eight metrics are complete. Games without usable odds can receive a score
projection but no EV ranking. Provider team names are joined using exact
normalized aliases; ambiguous or unmatched names are not guessed. A provider
can omit quotes for some scheduled games.

The multi-book median is a reference line. It is not paired with an invented
price. EV is evaluated on each actual book quote, then the best conditional EV
market per game is used for ranking. Both sides and all books remain in the
matchup detail. Keep quote timestamps and check for stale lines.

The public NFL loader was exercised for October 10–12, 2026: it returned all
14 scheduled games and complete score projections for each. The key-protected
adapters have fixture checks; authenticated CFBD/Odds refresh was not exercised
without your keys. Verify those connections in your deployment. If a provider
changes its schema, the app displays an error or
missing inputs instead of filling them with invented statistics.

Official data documentation:

- <https://nflreadr.nflverse.com/reference/load_schedules.html>
- <https://nflreadr.nflverse.com/reference/load_pbp.html>
- <https://github.com/CFBD/cfbd-python/blob/main/docs/GamesApi.md>
- <https://github.com/CFBD/cfbd-python/blob/main/docs/StatsApi.md>
- <https://the-odds-api.com/liveapi/guides/v4/>

## Refresh from a terminal

With provider keys in environment variables named `CFBD_API_KEY` and
`ODDS_API_KEY`:

```bash
python data_pipeline.py --season 2026 --start 2026-10-10 --end 2026-10-12 --output full_slate.json
```

For NFL only, add `--leagues NFL`. Import exported `full_slate.json` into the
Streamlit dashboard for the expanded calculations. This is an explicit refresh;
unattended scheduling is not configured in this package.

## Edit anything

- Weight controls: YPP, success rate, explosiveness, shrinkage, turnover
  retention/value, baseline, home field, residual sigmas and reference metrics.
- Matchup controls: spread/total, each side's odds, injuries, rest, weather and
  neutral venue. Changing a price creates a clearly labeled manual scenario.
- Team controls: `y`, `dy`, `s`, `ds`, `x`, `dx`, `p`, `t`; changes affect every
  game using that team.
- JSON controls: add teams/games, prices, notes, metadata and parameters.
- Code: `model.py` owns the equations; `data_pipeline.py` owns retrieval and
  feature definitions; `app.py` owns the Python interface.

Exports use the same format as `snapshot.json`. Team keys are arbitrary unique
identifiers. Fresh pulls prefix them with `NFL:` or `CFB:` to prevent collisions.
Every team needs `league` plus the eight numeric metrics before it can be scored.
Success rates and NFL explosive rates are percentage points (44, not .44).
CFB explosiveness uses the CFBD publisher index, not the NFL percentage.

## Make it a scientifically defensible predictive model

Uploading the script creates a running application; it does not automatically
fit the model. The optional calibration tool needs archived pregame forecasts
and later final scores. The original coefficients, adjustment points, and error
sigmas are **instructional priors**, not historical estimates. A high modeled
EV value is not evidence of profitable or more accurate predictions.

Use this staged plan:

1. **Capture pregame data.** Store every snapshot with retrieval time, metric
   cutoff, quote time, provider, venue, sample size, final scores, and a model
   version. Keep old snapshots unchanged. Historical final-season aggregates
   cannot be used as pregame features for earlier weeks.
2. **Construct comparable features.** Use one eligible play set per league,
   account for opponent strength, and shrink small samples toward preseason
   priors. CFB box-score YPP and advanced efficiency still use different play
   filters; harmonizing them from play-by-play is a production improvement.
3. **Fit separate league models.** Start with regularized regressions for
   game margin and total or points per drive plus pace. Fit correlated YPP,
   success and explosiveness jointly. Learn home-field/rest terms, turnover
   skill versus recovery luck, and documented availability effects from data.
4. **Validate chronologically.** Fit on older seasons, tune on subsequent
   seasons, and hold out the most recent season. Roll the training window
   forward. Keep both teams from the same game in the same fold.
5. **Measure prediction error.** Compare margin/total MAE and RMSE with a
   timestamp-matched market baseline and a simple team-strength baseline.
   Report NFL and CFB separately, with uncertainty and sample sizes.
6. **Calibrate probabilities.** Estimate residuals on held-out predictions;
   model football's discrete scoring masses and pushes. Evaluate Brier score,
   log loss and reliability diagrams before interpreting EV.
7. **Validate selection.** Select thresholds on validation data only. Track
   calibration and errors for the selected games, odds movement, sensitivity
   to weight/injury changes, and repeated selection across many games/books.
8. **Operate consistently.** Move immutable inputs/results into a database,
   add scheduled refresh with failure alerts, and keep a changelog. Sliders
   should produce named scenarios alongside a locked validated baseline.

The package implements the editable application, data adapters, matchup history,
schedule context and optional chronological score calibration. Joint fitting of the core features,
opponent adjustment beyond FEI, probability calibration, durable database storage,
automated injury/weather ingestion and unattended refresh are future stages.

## Verification

```bash
python -m unittest discover -s tests -v
```

Checks cover original calculation parity, probability/push arithmetic,
quote-specific EV, feature cutoffs, FEI units and defensive sign, roster decay,
portal completeness, history orientation, manual overrides, and chronological
calibration, schedule chronology, byes, venue conditions, signal overrides and
context caps. Additional development-time checks use Streamlit's AppTest.
