# E2E Interaction Workflows

Two channels for driving the app like a real user.

| Channel | Drives | Native APIs work? | Best for |
|---|---|---|---|
| **A — Web Preview** (`mcp__Claude_Preview__*`) | Vite dev server in headless browser | No (Tauri shims absent) | UI / state / `axios` calls / FastAPI integration |
| **B — Tauri WebDriver** (`tauri-driver` + `msedgedriver`) | Real Tauri WebView2 window | Yes (full `@tauri-apps/*` works) | Native dialogs, OAuth, file FS, audio engine |

---

## A — Web Preview (fast, no build)

### One-time setup
`.claude/launch.json` already configures two named servers:

| Name | Cmd | Port |
|---|---|---|
| `backend` | `python -m app.main` | 8000 |
| `frontend` | `npm run dev --prefix frontend` | 5173 |

### Driving the UI
From a Claude turn:

```text
preview_start("backend")              # FastAPI :8000
preview_start("frontend")             # Vite :5173
preview_screenshot(<frontend_id>)     # check layout
preview_console_logs(<frontend_id>)   # runtime errors
preview_click(<frontend_id>, "text=Rekordbox Live")
preview_fill(<frontend_id>, "input[name=search]", "deadmau5")
preview_eval(<frontend_id>, "window.location.pathname")
```

### Limits
- `window.__TAURI__` is **undefined** → `invoke()`, `dialog.open()`, `fs.writeBinaryFile()` all throw.
- Components that branch on `isTauri()` will take the fallback path (usually a browser file picker or a console warning).
- Native OS dialogs cannot be tested here — use channel B.

---

## B — Tauri WebDriver (real native window)

### One-time setup (done)
- `tauri-driver` installed → `%USERPROFILE%\.cargo\bin\tauri-driver.exe` (`cargo install tauri-driver --locked`)
- `msedgedriver` v147.0.3912.98 → `%USERPROFILE%\.tauri-webdriver\msedgedriver.exe` (matches installed WebView2 runtime)
- E2E project scaffolded under `tests/e2e/`

### Required: build the app once
```powershell
npm run tauri build           # produces src-tauri/target/release/Music Library Manager.exe
```
Re-build whenever Rust/Tauri code changes. Frontend-only changes don't require a rebuild — but the WebView **does** load the bundled `frontend/dist`, not the dev server, so you must run `npm run build` (or full `tauri build`) for React changes to show up.

### Driving the app
Two terminals.

**Terminal 1 — driver (keep running):**
```powershell
npm run e2e:driver
# Equivalent to: tauri-driver --port 4444 --native-driver <msedgedriver path>
```

**Terminal 2 — tests:**
```powershell
npm run e2e:install     # once: installs mocha + selenium-webdriver
npm run e2e:test        # runs tests/e2e/smoke.test.js
```

The smoke test connects to `http://127.0.0.1:4444`, asks the driver to launch the app via the `tauri:options.application` capability, and drives it via standard Selenium 4 APIs.

### Selenium cheatsheet (inside tests)
```javascript
import { By, until } from "selenium-webdriver";

await driver.findElement(By.css("button.primary")).click();
await driver.findElement(By.xpath("//*[contains(text(),'Rekordbox Live')]")).click();
await driver.findElement(By.css("input[name=query]")).sendKeys("phonk");
await driver.wait(until.elementLocated(By.css(".track-row")), 10_000);
await driver.executeScript("return window.localStorage.getItem('app-state')");
```

### Known caveats
- Native OS dialogs (`@tauri-apps/plugin-dialog`) bypass the WebView, so WebDriver cannot click them. Mock or stub the dialog plugin in test mode — see Tauri docs "WebDriver Mock Mode".
- The splash window (`label: "splashscreen"`) flashes briefly. The driver attaches to the first window — typically the main one once it becomes visible. If a test races the splash, add `await driver.wait(...)` on a main-window-only selector.

---

## Picking a channel

```
question: needs a native dialog / file picker / OAuth callback?
  ├── yes → channel B (tauri-driver)
  └── no  → channel A (preview)  ← cheaper, faster, no build step
```
