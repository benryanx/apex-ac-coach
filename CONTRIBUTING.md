# Contributing to Apex

Use Windows and Python 3.11 or newer for the complete telemetry and native-window
checks. Node.js 22 or newer runs the dashboard tests; no npm install is needed.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
node --check web/app.js
$testFiles = (Get-ChildItem tests -Filter '*.test.mjs').FullName
node --test @testFiles
.\'Launch Apex.cmd' --demo
```

Use the demo or synthetic fixtures for development. Tests mock OpenAI requests
and do not need a key or start paid voice sessions. Try a separate `--port` and
`--data-dir` when developing beside an existing running app.

Keep analysis based on raw telemetry; display smoothing belongs in the frontend.
Qualify inferred handling, pass and contact events and keep unobserved facts
unknown. Keep engineer calls brief and consistent with the normal personality.

For a pull request, describe the changed behavior and the checks you ran. Include
a small reproducible example for telemetry issues. Keep API keys, personal paths,
recordings and local `data/` files out of commits and issue attachments.

Contributions are provided under this project's MIT License.
