#!/usr/bin/env node
// Start the FastAPI sidecar with the project venv when one exists.
//
// `npm run dev:full` used to spawn bare `python`, which on this machine is the
// system 3.13 with drifted packages (numpy 2.x, no madmom). The pinned stack
// lives in `.venv` (uv, Python 3.11, see docs/ANALYSIS_HANDOVER.md) and had to
// be activated by hand in every shell — cmd, PowerShell and Git Bash each with
// a different incantation. This resolves the interpreter once, here.
//
// Order: $LMS_PYTHON > .venv/Scripts/python.exe | .venv/bin/python > python.
import { existsSync } from "node:fs";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");

function resolvePython() {
  if (process.env.LMS_PYTHON) return process.env.LMS_PYTHON;
  const candidates =
    process.platform === "win32"
      ? [join(root, ".venv", "Scripts", "python.exe")]
      : [join(root, ".venv", "bin", "python")];
  return candidates.find(existsSync) ?? "python";
}

const python = resolvePython();
const args = process.argv.length > 2 ? process.argv.slice(2) : ["-m", "app.main"];
console.log(`[run-backend] ${python} ${args.join(" ")}`);

const child = spawn(python, args, { cwd: root, stdio: "inherit" });
for (const sig of ["SIGINT", "SIGTERM"]) process.on(sig, () => child.kill(sig));
child.on("exit", (code, signal) => process.exit(code ?? (signal ? 1 : 0)));
child.on("error", (err) => {
  console.error(`[run-backend] failed to start ${python}: ${err.message}`);
  process.exit(1);
});
