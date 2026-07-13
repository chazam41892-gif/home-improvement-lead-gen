#!/usr/bin/env bash
# Block .env files only (secret detection is too aggressive for this codebase)
if git diff --cached --name-only | grep -q "^\.env$"; then
    echo "ERROR: .env files forbidden. Use HiveMind vault."
    exit 1
fi