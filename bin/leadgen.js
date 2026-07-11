#!/usr/bin/env node
"use strict";

const { spawn } = require("child_process");
const path = require("path");
const fs = require("fs");

const pkgRoot = path.resolve(__dirname, "..");
const runPy = path.join(pkgRoot, "run.py");

if (!fs.existsSync(runPy)) {
  console.error("leadgen-pro: run.py not found at", runPy);
  process.exit(1);
}

const pythonCmd = process.platform === "win32" ? "python" : "python3";

const child = spawn(pythonCmd, [runPy], {
  cwd: pkgRoot,
  stdio: "inherit",
  shell: true,
});

child.on("error", (err) => {
  console.error("leadgen-pro: failed to start Python:", err.message);
  console.error("Make sure Python 3.12+ is installed and on your PATH.");
  process.exit(1);
});

child.on("exit", (code) => {
  process.exit(code || 0);
});
