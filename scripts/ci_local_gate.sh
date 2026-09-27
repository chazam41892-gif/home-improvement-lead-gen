#!/usr/bin/env bash
# Reproduce the CI release gate on this box, in a clean virtualenv, from
# requirements.txt only. This is the closest local proxy to a GitHub runner:
# same pins, no .env, no global site-packages.
#
# The point is to catch what a clean runner would hit -- a missing dependency,
# an import that only resolves because of something installed globally, or a
# test that depends on a local secret. Every one of those passed locally before
# this existed, because my shell already had all of it.
set -euo pipefail

REPO="C:/Users/chaza/leviathan/home-improvement-lead-gen"
# Use a NATIVE path: MSYS maps /tmp to C:/tmp, so a venv created from the
# literal string "/tmp/..." lands somewhere the shell cannot see, and the
# interpreter probe then fails for a reason that has nothing to do with the
# code under test.
VENV="$LOCALAPPDATA/Temp/lgg-ci-venv"
cd "$REPO"

echo "== 1. fresh venv (no global site-packages) =="
rm -rf "$VENV"
py -3.14 -m venv "$VENV"
# Windows venvs use Scripts/, POSIX uses bin/. Probe rather than assume, or the
# script dies on whichever platform you did not test it on.
VPY="$VENV/Scripts/python.exe"
[ -x "$VPY" ] || VPY="$VENV/bin/python"
[ -x "$VPY" ] || { echo "no interpreter in $VENV"; exit 1; }
echo "   interpreter: $VPY"

echo "== 2. install exactly what CI installs =="
"$VPY" -m pip install --quiet --upgrade pip
"$VPY" -m pip install --quiet -r requirements.txt
"$VPY" -m pip install --quiet pytest pytest-cov pytest-asyncio ruff mypy starlette

echo "== 3. no .env on a runner: export only what the suite needs =="
# Physically hide .env, not just decline to read it. A previous version of this
# script exported the vars but left .env in place, and load_dotenv() picked it
# up -- which is exactly why a test that depends on a real secret kept passing
# here while failing on CI. The .env is restored on exit.
ENVFILE="$REPO/.env"
STASH="$LOCALAPPDATA/Temp/lgg-env-stash"
restore_env() { [ -f "$STASH" ] && mv "$STASH" "$ENVFILE" && echo "   (.env restored)"; }
trap restore_env EXIT
[ -f "$ENVFILE" ] && mv "$ENVFILE" "$STASH" && echo "   (.env hidden for this run)"
export LEADGEN_TESTING=1
export JWT_SECRET="ci-only-not-a-real-secret"

echo "== 4. ruff format --check =="
"$VPY" -m ruff format --check engine/ main.py

echo "== 5. ruff check =="
"$VPY" -m ruff check engine/ main.py

echo "== 6. mypy =="
"$VPY" -m mypy engine/ main.py

echo "== 7. pytest with coverage gate =="
"$VPY" -m pytest \
  --cov=engine --cov=main --cov-branch \
  --cov-report=term:skip-covered \
  -p no:cacheprovider -q

echo
echo "== LOCAL CI SIMULATION PASSED =="
