/**
 * Tauri WebDriver smoke test.
 *
 * Drives the real Tauri WebView via `tauri-driver` (which proxies to
 * `msedgedriver`). Verifies the app boots, the main window renders, and
 * basic DOM elements are present.
 *
 * Prereqs:
 *   1. Built Tauri app exists at `src-tauri/target/release/Music Library Manager.exe`
 *      → run `npm run tauri build` (or `cargo tauri build`) once.
 *   2. `tauri-driver.exe` on PATH (`cargo install tauri-driver --locked`).
 *   3. `msedgedriver.exe` at `%USERPROFILE%\.tauri-webdriver\msedgedriver.exe`
 *      (version must match the installed WebView2 runtime).
 *
 * Run:
 *   .\run-driver.ps1                # in one terminal: starts tauri-driver
 *   npm test                        # in another:     runs this test
 *
 * Or one-shot:
 *   npm run test                    # if you've started the driver elsewhere
 *
 * See docs/e2e-testing.md for the full workflow.
 */
import { strict as assert } from "node:assert";
import { spawn } from "node:child_process";
import { Builder, By, Capabilities, until } from "selenium-webdriver";
import { fileURLToPath } from "node:url";
import path from "node:path";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Resolve the built Tauri binary. Caller can override via env.
const APP_BIN =
    process.env.TAURI_APP_BIN ||
    path.resolve(
        __dirname,
        "..",
        "src-tauri",
        "target",
        "release",
        "Music Library Manager.exe",
    );

const DRIVER_URL = process.env.TAURI_DRIVER_URL || "http://127.0.0.1:4444";

describe("Music Library Manager — smoke", function () {
    /** @type {import('selenium-webdriver').WebDriver | null} */
    let driver = null;

    before(async function () {
        // Tauri's WebDriver shim is reached via Capabilities. The `tauri:options`
        // payload tells tauri-driver which native binary to launch.
        const caps = new Capabilities();
        caps.set("browserName", "wry");
        caps.set("tauri:options", { application: APP_BIN });

        driver = await new Builder()
            .usingServer(DRIVER_URL)
            .withCapabilities(caps)
            .build();
    });

    after(async function () {
        if (driver) {
            try {
                await driver.quit();
            } catch (err) {
                console.error("[e2e] driver.quit failed:", err?.message);
            }
        }
    });

    it("loads the main window and renders Select Mode screen", async function () {
        if (!driver) throw new Error("driver not initialized");

        // Splash screen flashes — give the main window time to appear.
        await driver.wait(until.elementLocated(By.css("body")), 15_000);

        // The boot screen has the text "Select Mode" (see App.jsx mode picker).
        const found = await driver.wait(async () => {
            const body = await driver.findElement(By.css("body"));
            const text = await body.getText();
            return text.includes("Select Mode") ? text : null;
        }, 30_000);

        assert.ok(found.includes("Select Mode"), "Expected Select Mode UI");
        assert.ok(
            found.includes("Rekordbox Live") || found.includes("XML Snapshot"),
            "Expected mode-picker cards",
        );
    });

    it("can click Rekordbox Live and reach the next screen", async function () {
        if (!driver) throw new Error("driver not initialized");

        const card = await driver.wait(
            until.elementLocated(By.xpath("//*[contains(text(),'Rekordbox Live')]")),
            10_000,
        );
        await card.click();

        // Allow the next view to mount. We don't assert on a specific element here
        // because the post-pick screen depends on whether master.db is available.
        await new Promise((r) => setTimeout(r, 2_000));

        const body = await driver.findElement(By.css("body"));
        const text = await body.getText();
        assert.ok(
            !text.includes("Select Mode") || text.includes("master.db"),
            "Expected to leave Select Mode screen after picking Rekordbox Live",
        );
    });
});
