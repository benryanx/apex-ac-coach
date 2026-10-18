# Apex · Assetto Corsa race engineer

A Windows companion dashboard for the **original Assetto Corsa**. Launch it beside the simulator for live car inputs, lap and sector comparisons, a learned track map, race position, incident estimates, short engineer callouts and end-of-lap debriefs. Voice uses **`gpt-live-1`** over WebRTC, with the project API key kept in the local Python server.

## Get started

Download the [source ZIP](https://github.com/benryanx/apex-ac-coach/archive/refs/heads/main.zip)
and extract it, or clone the repository:

```powershell
git clone https://github.com/benryanx/apex-ac-coach.git
cd apex-ac-coach
```

## Launch

Double-click **Launch Apex.cmd**. Python 3.11+ and Microsoft Edge WebView2 Runtime are required. The launcher creates a local virtual environment and installs dependencies on first launch. It opens a 440-pixel sidebar that stays above other windows. Use **☷ Display** to customize it or switch to an expanded window, and **↥** to toggle always-on-top. Window size and position are remembered when you close it. Use windowed or borderless AC, or put Apex on a second monitor; exclusive fullscreen can cover external apps.

To see it without the simulator, select **Try demo** at the bottom of the dashboard. The demo uses a fictional circuit and 66-second laps, labels all its telemetry as simulated, and stores separate references.

```powershell
# Desktop demo
.\'Launch Apex.cmd' --demo

# Expanded dashboard
.\'Launch Apex.cmd' --wide

# Browser fallback if WebView2/audio is unavailable
.\'Launch Apex.cmd' --browser

# Server only, without opening a window
.\.venv\Scripts\python.exe launch.py --serve --demo
```

The local address is http://127.0.0.1:8765. Use `--port 8766` when another instance already occupies the default port. Close the dedicated window to stop its local server. Browser mode runs until Ctrl+C in its console.

## Make the sidebar fit

The **☷ Display** button in the header opens instant display controls. **Drive**
is the default balanced layout: lap timing, map, nearby drivers, compact car
stats and the lap debrief. **Race** puts the field first, **Minimal** keeps timing
and the map, and **Review** brings forward the profile, notes and lap history.

Switch any panel on or off, choose **Compact** or **Comfortable** spacing, and
open **Fine-tune details** for sector times, reference details, input bars, tyre
temperatures, handling estimates, nearby drivers, the full roster, incident
text, upcoming zones, the radio caption, volume slider and session subtitle.
Each card's arrow folds it into a single heading. The radio connection and mic
controls stay available. Hiding a panel changes the display only; analysis and
voice context continue. The dock reserves its actual height so content remains
reachable by scrolling.

**Transparent background** lets the game show around the cards in the native
Windows app. **HUD opacity** (60–100%) fades the whole window, including text;
100% keeps the cards clearest. Space outside the cards passes through to the game; dialogs and voice connection prompts temporarily use the full window. Use an opaque background if preferred. Browser
mode cannot reveal the game through a normal browser window. Native transparency
uses WebView2, Windows composition and a window region around visible cards; check legibility against your actual AC
scene, running windowed/borderless or on another monitor.

The desktop app uses a black frame and dark title bar instead of the white Windows
frame. Drag the title bar to move it, drag an edge or corner to resize, and use
the title-bar buttons to minimize, maximize/restore or close. Double-clicking the
title bar also toggles maximize. Empty panels use plain status labels such as
“No track map” and “No completed laps.”

Display settings save to `data/display.json`, including switches, folded cards,
preset, spacing and transparency. Window geometry saves to `data/window.json`.
They survive a full restart, independently of the in-memory API key. **Reset**
returns the balanced defaults. Display changes do not require reconnecting voice.

## Connect the game

1. Launch the coach and select **Connect to AC** if demo mode is active.
2. Start an actual driving session in Assetto Corsa. The menu alone does not produce live driving data.
3. The header changes to **AC CONNECTED** once the app reads a live shared-memory feed.
4. Complete a clean observed lap to create the reference. If the coach joined mid-lap, it excludes that partial lap and learns the next full lap.

The reader opens `acpmf_physics`, `acpmf_graphics` and `acpmf_static` using read-only Win32 mappings. No game plugin or game-file edits are needed. It reconnects if mappings disappear or the feed stops changing. Paused and replay feeds do not produce driving cues.

### Race position, passes and incidents

The Race awareness panel shows your game-reported position, field size, flags,
detected passes and incidents. With Apex Bridge active, it also shows the drivers
ahead and behind **in the standings**, their cars, and an expandable **Drivers &
cars** roster. Your row is highlighted. These neighbours are not physical
proximity or measured time gaps. Car labels come from installed AC car metadata
when available; otherwise the raw model identifier is shown. Stable race-position changes create observations such as
“Up one place to fourth in the standings.” Such a change can result from
pitting or disconnection, so it is not called an overtake without opponent data.

Automatic race speech is limited to confirmed passes and lost positions, with
one short acknowledgment and no nearby-driver rundown afterward. Standings-only
gains stay in the dashboard. Single-pass calls use only the surname extracted
from AC's display name (single-word aliases stay as supplied). Quick successive
passes collect into one count rather than a list of drivers. Grouping waits for
2.5 seconds without another pass, up to 6 seconds, and pass summaries are at least
10 seconds apart. Calls still wait for low driver workload; observations older
than 12 seconds expire. A grouped summary may mention only the current next
driver ahead in the standings, by surname, when the fresh roster supports it.
That detail is resolved when the cue is sent, and does not imply a physical gap.
Full identities and car models remain in the dashboard notes. Positions are
spoken as ordinals. Roster details are sent to the voice model
when it delegates a question, instead of streaming neighbours every three seconds.
Ask for names, cars or standings when you want them. Other driving coaching keeps
its existing schedule. A fresh `close_on_track` fact requires
both a race-distance gap and world-coordinate distance within 60 metres, with
neither car in the pits. Only that fact supports saying someone is close ahead
or behind; a standings neighbour alone does not. Distances are approximate and
do not establish closing speed, a time gap or safe clearance to change line.
Proximity information is available for answers to your questions, not unsolicited
nearby-driver calls.

For named on-track pass detection, install the optional [Apex Bridge](ac-plugin/README.md)
in-game Python app. The bridge writes a local roster of names and car models; compatible runtimes also send it over localhost UDP. AC's Python can omit the socket module, so the file transport works independently of it. The included
`install_bridge.py` installs it and can enable its section in `cfg/python.ini`,
backing up any changed files under `data/backups/`. With a fresh compatible feed, the analyzer
looks for a nearby progress-order crossing plus a persistent race-position gain,
excluding pit running, stale data and implausible jumps. It can miss passes when
AC's updates arrive late; the count means **passes detected**, not every pass made.

New raw car-damage values trigger **likely car contact**, following your chosen
assumption. Calls stay short, without an “are you okay?” check-in. If exactly one
stable opponent is within 6 metres, with consistent recent coordinates and lap
progress, the event can name a **possible** contact partner. Other cars within
8 metres make the attribution ambiguous, so no name is supplied. This is a
proximity estimate: AC damage cannot prove car-versus-barrier contact, establish
the collision partner or assign blame. Rapid rotation plus speed loss and grip loss can
trigger a **possible spin**. Initial damage, pit repairs, telemetry gaps and
teleports establish a new baseline and do not create crash calls. Contact without
a damage increase can be missed, especially with damage disabled. Damage values
are not presented as health percentages. Incident laps are excluded from the
reference. These facts also enter the engineer's voice context, so you can ask
“What position am I?”, “Who am I chasing?”, “What car is behind me?”,
“Who is leading?”, “Did I pass anyone?” or “Did I take damage?”

The demo now includes a fictional position gain, pass and damage increase so the
panel can be reviewed without a race. Quiet radio mode still allows incident and
flag alerts. Real race behavior and the optional bridge require live AC testing.

## Connect the engineer

Open **⚙ Settings**, enter an OpenAI project API key with GPT-Live access, save, then select **Connect engineer**. Allow microphone access yourself if Windows or the browser asks. The key entered in Settings lasts until the app closes and is never returned to the dashboard. To configure later launches, copy `.env.example` to `.env` and set `OPENAI_API_KEY`. `.env` is ignored by Git.

Voice sends microphone audio and concise driving measurements to OpenAI. Dashboard telemetry stays local until voice is connected. The app does not record microphone audio. Disconnect the engineer when done; muting the mic or turning the volume down leaves the paid session running. The built-in quiet setting keeps lap summaries and incident/flag alerts, while still allowing spoken questions.

Examples: “How was that sector?”, “Am I quicker than my reference?”, “How much fuel is left?”, “What position am I?”, “Did I take damage?”, “What should I focus on next lap?” The application returns a current measured snapshot when Live delegates a statistics question. This first version uses deterministic analysis rather than a separate reasoning model.

GPT-Live is configured through `POST /v1/live/sessions`, **not** the older Realtime session protocol. Telemetry context uses `session.thinking.append`; spoken cues use `session.commentary.append`. The frontend waits for `session.started`. Disconnect sends `session.close` and waits for `session.closed`; a trusted sideband provides a fallback when the primary data channel is unavailable. Failed finalization is reported so it can be retried.

### Smooth telemetry display

Continuous live readings interpolate over 180 ms: speed, RPM, fuel, pedal and
steering inputs, tyre temperatures, lap time, timing delta, reference speed,
lap progress and upcoming-zone distance. Retargeting starts from the current
animated reading. New sessions, lap resets and changed braking zones snap to
the new baseline. Gears, positions, lap/sector numbers, event counts and completed
results stay immediate. Reduced-motion settings disable interpolation. This is
presentation only; analysis and coaching always use raw, current telemetry.

### Conversation and personality

Apex has one consistent engineer personality: calm, friendly and concise, with
dry wit and occasional light sarcasm. It stays focused during demanding driving,
flags and contact, and leaves room for concentration. There is no personality
selector; the voice selection still offers 31 voices.

Automatic calls normally use one short sentence; lap debriefs allow two. Race
order stays quiet unless asked or a pass/lost place is confirmed. Jokes never
invent crashes, damage, opponents or blame. Unrelated requests get a brief
redirect to driving. Instructions are readable in
[`web/engineer-personality.json`](web/engineer-personality.json).

At connection, Apex introduces itself once using the current session stage.
`web/session.mjs` distinguishes waiting, standby, pause, replay, pits, an estimated
pre-start wait, driving, racing and the chequered flag. A stationary first-lap race
with no running lap clock supports a pre-start estimate. A running lap clock plus
movement, or completed laps, supports an underway estimate. Connecting mid-race
does not generate a new race start. Standard telemetry does not expose the start
lights: Apex never invents a countdown or calls “lights out.” Session transitions
must persist for 1.2 seconds; a pause followed by a stopped feed produces at most
one “Ready when you are,” with no spoken telemetry error. Old queued driving calls
are discarded, and stale session acknowledgments cannot escape after resuming.

Handling hints are limited to once per type per lap and no more than once every
75 seconds. Repeated handling notes are grouped in the dashboard. Unbenchmarked
sector times and changes smaller than a tenth stay visual. Routine automatic
calls wait for a straight or pit running and leave pauses around driver and
engineer speech; stale calls are dropped. These controls do not limit replies to
your own questions. Quiet mode retains meaningful incident/flag alerts.

Rev and missed-shift remarks describe recent observations rather than giving
immediate commands: for example, “Noticed you were stretching that gear a little;
try shifting earlier next time.” They do not assume the previously observed
gear is still engaged when speech arrives. The measured rev-ceiling and sustained
load checks remain the same; the app does not know the car's ideal shift point.

The dashboard applies the engineer instructions after session startup, waits for Live to
acknowledge it, and checks for instruction-file updates every 30 seconds. Save
Settings to reapply it immediately. All 31 documented built-in GPT-Live voices are available in Settings; the selection is remembered locally. A voice change requires saving and reconnection.
For an already-open older dashboard, disconnect the engineer, click the APEX
logo to reload the page and reconnect. Reloading the dashboard keeps the local
server's API key; closing the desktop app clears an in-memory-only key.

These are prompt, observation and scheduling changes; conversational quality still needs a
listening pass with the driver. No prerecorded speech or custom voice is used.

### Volume and driving profile

Engineer playback now defaults to **120%**, a 50% gain increase over the former
80% default. This changes playback gain, not speaking frequency or microphone
sensitivity; perceived loudness also depends on your speakers and system volume.
Use the **− / +** buttons, the **0–200%** slider, or **Mute voice**. The level is
remembered locally. While connected, say “volume up”, “volume down”, “mute
yourself”, “unmute yourself”, or “set your volume to 60 percent”. Ctrl+Shift+Up/Down
also adjusts it while Apex has focus. Boost uses Web Audio with a limiter;
unsupported playback falls back to normal volume and displays a notice.

The black/charcoal dashboard uses red accents. Circuit position combines your
live world coordinates with normalized lap distance. A persistent profile divides
each car/track/layout into **20 sections** and records high-rev holds, possible
missed shifts, handling estimates, detected passes, lost positions and incidents.
Repeated patterns appear on the learned map. Completed observed laps save under
`data/profiles/`; demo and real driving use separate profiles. Partial laps do not
establish section bests. Clean section times, clean lap bests and comparable
high-rev exposure support measured encouragement in the debrief and voice context.

Shift advice requires sustained RPM near AC's reported maximum under load, or
sustained neutral under throttle after a forward gear. Short shifts, pauses, pits
and telemetry gaps do not trigger it. These are estimates: AC's shared feed does
not expose paddle presses, the number of forward gears or the optimal shift RPM.
Apex can identify recurring patterns; it cannot prove a paddle input was missed.
Named overtakes still require the optional opponent bridge. Stable lost positions
produce brief calls, without inventing who passed you or how it happened.

Official OpenAI documentation:

- [Available Live voices](https://developers.openai.com/api/reference/resources/live/methods/create)
- [GPT-Live 1](https://developers.openai.com/api/docs/models/gpt-live-1)
- [WebRTC connection](https://developers.openai.com/api/docs/guides/voice-webrtc)
- [Context and client delegation](https://developers.openai.com/api/docs/guides/live-delegation)
- [Session lifecycle and graceful close](https://developers.openai.com/api/docs/guides/live-conversations)
- [Trusted sideband control](https://developers.openai.com/api/docs/guides/voice-server-controls?api=live)
- [Assetto Corsa SDK shared-memory structures](https://assettocorsamods.net/threads/doc-shared-memory-reference.58/)

## How comparisons and coaching work

- Telemetry is sampled at approximately 20 Hz; the dashboard refreshes at 5 Hz. Local analysis selects events, so raw high-frequency telemetry is not streamed to the model.
- Lap delta compares elapsed time at the **same normalized track position**, interpolated against the best recorded clean observed lap for this car, circuit and layout. A speed difference is also shown at that position.
- Sector timing uses AC's current sector and last completed sector time. Completed sectors are compared against those of the reference lap.
- Track geometry is drawn from your actual X/Z coordinates. Braking zones are learned from the reference lap’s brake input and announced with approximate distance. They are **your previous braking zones**, not guaranteed ideal braking points. No corner names or ideal speeds are invented. A reference lap is required before upcoming-zone cues work.
- Front/rear wheel-slip differences during a sustained turn create **possible understeer/oversteer** estimates. Wheel slip does not provide a definitive handling diagnosis. Thresholds in `coach/engine.py` need calibration with real car/tyre data; the first version does not calculate slip angles, steering geometry or yaw response.
- A reference is excluded if the observed lap includes more than two tyres out, pit running, a penalty, or a telemetry gap. The stable shared-memory prefix does not expose AC’s complete lap-validity state; **clean observed is not a guarantee of official game validity**.
- Callouts have per-event cooldowns and an overall minimum interval, with lap debriefs taking priority. Every selected note is shown, while speech is rate-limited. The voice model’s phrasing and response latency remain variable; this is coaching, not a precise braking alarm.
- Session JSON and reference laps are stored under `data/` (ignored by Git). **Export** downloads the current session’s laps and notes. Previous sessions remain in `data/sessions/`; this version does not include a historical-session browser.

### Clean turn exits and map awareness

AC supplies world X/Z coordinates and normalized lap progress. Apex draws the
line you drove and estimates turn regions from a clean recorded reference;
it does not watch the game screen or load official turn names or an ideal line.
The map heading shows the current learned turn and exit-assessment phase.
Existing coordinate-based references can be reused; without one, drive a full
clean observed lap first. Sharp geometry changes are estimates and can split or
miss linked bends.

A positive exit observation requires coverage from the learned turn entry,
continuous plausible telemetry, sustained steering followed by unwinding,
throttle application and speed building on exit. Sustained detected slip,
new damage, track limits, a penalty, pit running, a pause or a data gap prevent
praise. It means **clean observed exit**, not a perfect apex or optimal driving.
The engineer can mention a measured exit-speed improvement against the reference
at the same position. Automatic praise has at most two opportunities per lap,
at least 45 seconds apart, and still respects the existing routine radio spacing,
corner gating and quiet mode. Lap debriefs include confirmed exit counts.

## Development and validation

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
node --check web/app.js
node --test tests/*.test.mjs
```

The tests cover same-position deltas, reference persistence, partial/incident laps, resets, source isolation, replay/pause gating, sustained-slip detection, learned zones, SDK byte offsets, real private Win32 mappings, standings debounce, named-pass evidence, pit/teleport suppression, damage baselines, spin estimates, roster UDP validation, the Python 3.3-compatible bridge, local API protections, per-track profile persistence, sustained shift estimates, measured encouragement, gain routing, spoken volume controls the full voice catalogue, per-driver car metadata, standings neighbours bounded Unicode roster context, and display preference persistence across app restarts. API tests mock OpenAI; they do not validate account access or generated speech. Desktop expanded and sidebar views have been visually inspected using the demo.

Voice timing, audio quality and telemetry thresholds depend on the car, simulator setup and API access. Automated tests cover analysis and mocked voice requests; they do not replace an end-to-end driving and listening check.

## Layout

```text
launch.py             Desktop window / local server launcher
coach/telemetry.py    Win32 AC reader and isolated demo feed
coach/engine.py       Reference laps, timing, grip estimates, coaching events
coach/race.py         Position changes, conservative pass and incident estimates
coach/profile.py      Persistent section habits, shifting and measured improvement
coach/corners.py      Learned turn geometry and observed clean-exit assessment
coach/opponents.py    Optional local UDP roster receiver
coach/server.py       Local API, event stream and GPT-Live session lifecycle
ac-plugin/            Optional AC Python app and install instructions
web/                  Dashboard, map and WebRTC microphone/audio client
tests/                Analysis and API verification
```

The server binds only to `127.0.0.1`, checks Host/Origin and requires a per-process request token for mutations. It is intended for one local driver and one voice session; it is not a hosted multi-user service.

## Privacy and local files

Each driver supplies their own OpenAI API key. Without voice, telemetry analysis
runs locally. Connecting voice sends microphone audio and selected driving/roster
context to OpenAI. API keys entered in Settings stay in the running server's
memory; an optional `.env` keeps a key for later launches on your own machine.

The repository excludes `.env`, local environments, logs, session exports,
references, driving profiles, window/display preferences and bridge backups.
These files remain local under `data/` or other ignored paths. Do not attach
private keys or unreviewed session exports to issues.

## Contributing and license

See [CONTRIBUTING.md](CONTRIBUTING.md) for the development workflow. Licensed
under the [MIT License](LICENSE). Assetto Corsa and an OpenAI API account are
separate products; this repository includes no game assets or API credentials.
