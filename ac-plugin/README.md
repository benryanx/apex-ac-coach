# Optional Apex race-roster bridge

Copy the `ApexBridge` directory into your original Assetto Corsa installation's
`apps/python/` directory. The result must be:

```text
assettocorsa/apps/python/ApexBridge/ApexBridge.py
```

Enable **Apex Bridge** in Assetto Corsa's Python apps settings (or Content Manager
Settings → Assetto Corsa → Apps), then start a driving session. The app must be
enabled; its small in-game window need not stay open.

Alternatively, use the included installer with your actual game and documents
paths. `--config` enables only ApexBridge and backs up the previous file:

```powershell
.\.venv\Scripts\python.exe install_bridge.py --ac-path "D:\SteamLibrary\steamapps\common\assettocorsa" --config "$([Environment]::GetFolderPath('MyDocuments'))\Assetto Corsa\cfg\python.ini"
```

Start Apex normally. The bridge writes its latest complete roster atomically to
`apps/python/ApexBridge/roster.json`. The installer records this location in
Apex's `data/bridge.json`. This transport requires no extra native Python modules
and works when AC's Python 3.3 runtime lacks `_socket.pyd`. When sockets are
available, it also sends UDP to `127.0.0.1:9876`. Only one Apex instance can own
the UDP port; file transport remains available independently.

The bridge sends connected driver names, car identifiers, readable car model
names, race positions, lap counts, spline positions, pit state, speed and world coordinates to this PC at 5 Hz. It does not
send chat, addresses, server credentials or game-control commands. When voice is
connected, driver questions can supply the current roster to OpenAI. Single-pass
calls use a surname; grouped pass calls summarize the count and may name the
current next driver ahead by surname. Car labels are read once from installed
`content/cars/<model>/ui/ui_car.json`, falling back to AC's identifier when unavailable. Disable/remove the Python app to stop the optional feed. Missing, stale, invalid
or mismatched rosters stay unavailable; Apex shows the reason rather than
inventing names. Restart both Apex and the AC driving session after this update.

Without the bridge, shared memory still provides your position, standings
changes, damage and flags. It cannot confirm who you passed. Even with the
bridge, pass detection is conservative: it requires nearby progress-order
crossing, a persistent race-position gain, and neither car pitting. This can miss
passes when AC updates standings late, skips opponent data or teleports a car.
It does not assign contact blame. A consistently nearby car may be named as a
possible contact partner, without claiming proof of impact.

Bridge parsing and pass logic are tested with synthetic data and mocked AC APIs.
The bridge uses Python 3.3-compatible code and file transport when sockets are
unavailable. Validate the game-to-voice path with your own AC installation.

After updating the bridge, restart the AC driving session so its Python app reloads.
Restart Apex to load companion changes. Older bridge versions still send names;
car models stay unavailable until the bridge is updated.
