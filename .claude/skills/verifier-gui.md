# verifier-gui — taxmanager GUI verifier

Launches the taxmanager app in a headless Chromium browser via Playwright and takes screenshots so the reviewer can see what changed.

## Setup

```bash
# Start a local HTTP server for the app (port 8787)
pkill -f "python3 -m http.server 8787" 2>/dev/null; true
cd /home/user/taxmanager && python3 -m http.server 8787 &>/tmp/taxmanager-server.log &
sleep 1
echo "Server PID: $!"
```

## Capture a screenshot

Use the Node.js helper script `/home/user/taxmanager/.claude/skills/screenshot.mjs` to take screenshots:

```bash
# Full-page screenshot of a specific tab
node /home/user/taxmanager/.claude/skills/screenshot.mjs <tab> <output-path> [extra-js]

# Examples:
node /home/user/taxmanager/.claude/skills/screenshot.mjs dashboard /tmp/dashboard.png
node /home/user/taxmanager/.claude/skills/screenshot.mjs clients /tmp/clients.png
node /home/user/taxmanager/.claude/skills/screenshot.mjs fees /tmp/fees.png
node /home/user/taxmanager/.claude/skills/screenshot.mjs julgae /tmp/julgae.png
node /home/user/taxmanager/.claude/skills/screenshot.mjs closure /tmp/closure.png
```

Tab names: `dashboard`, `clients`, `julgae`, `fees`, `closure`

## Teardown

```bash
pkill -f "python3 -m http.server 8787" 2>/dev/null; true
```

## Evidence delivery

Use `SendUserFile` to send screenshots to the user — they can't open local paths from this remote environment.

## Notes

- The app uses Firebase Auth. The screenshot script bypasses auth by injecting a mock user into localStorage before the page loads.
- `G` state is available at `window.G` in the browser context.
- To interact with specific UI elements, pass extra JS as the 4th argument (URL-encoded or as a file path).
