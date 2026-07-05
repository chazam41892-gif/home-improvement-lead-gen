# Application Icons

The Tauri bundle requires these icon files in this directory:

- `32x32.png`
- `128x128.png`
- `128x128@2x.png`
- `icon.ico`

## Generate icons

**Option 1:** Use the Tauri CLI to generate them from a source PNG (recommended):

1. Place a 1024x1024 PNG source image named `app-icon.png` in this directory
2. Run: `npx @tauri-apps/cli icon` from the `desktop/` directory

**Option 2:** Use an online generator like https://icon.kitchen

**Option 3:** Manually create placeholder icons (the app will work in dev mode without them, but builds will fail).

Current icons: none — generate them before running `npm run tauri build`.
