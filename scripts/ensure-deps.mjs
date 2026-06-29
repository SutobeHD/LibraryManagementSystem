#!/usr/bin/env node
// Self-healing dependency guard.
//
// Wired as predev / predev:full / pretauri in package.json so a fresh clone or
// a new git worktree auto-installs node_modules before the first dev start.
// Fixes the recurring `tauri`/`vite` "command not found" — a fresh worktree has
// no node_modules, and the bins live there. Idempotent: silent + instant on the
// happy path (deps present), installs only what is actually missing.
import { existsSync } from "node:fs";
import { execSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");

/** Install `cmd` only when `probe` (a marker package dir) is absent. */
function ensure(label, probe, cmd) {
  if (existsSync(probe)) return false;
  console.log(`[ensure-deps] ${label} deps missing -> ${cmd}`);
  execSync(cmd, { cwd: root, stdio: "inherit" });
  return true;
}

let installed = false;
// Root: concurrently (dev:full) + @tauri-apps/cli (tauri) come from one install.
if (ensure("root", join(root, "node_modules", "concurrently"), "npm install")) installed = true;
// Frontend: vite + the React toolchain.
if (ensure("frontend", join(root, "frontend", "node_modules", "vite"), "npm install --prefix frontend"))
  installed = true;

if (installed) console.log("[ensure-deps] dependencies ready.");
