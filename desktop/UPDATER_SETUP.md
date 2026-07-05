# Tauri Updater Setup Guide

## 1. Generate Tauri Signing Keys

Tauri updates require signing with a private RSA key. Generate one:

```bash
# Install the tauri CLI if not already installed
npm install -g @tauri-apps/cli

# Generate signing keys
npx tauri signer generate -w ~/.tauri/leadgen.key
```

This creates:
- `~/.tauri/leadgen.key` — private key (KEEP SECRET, never commit)
- The public key printed to stdout — copy this

Set the private key as an environment variable for builds:

```bash
# PowerShell
$env:TAURI_PRIVATE_KEY = Get-Content -Raw ~/.tauri/leadgen.key
$env:TAURI_KEY_PASSWORD = "your-key-password"

# Or set them permanently in your profile
```

Copy the public key into `src-tauri/tauri.conf.json`:
```json
"updater": {
  "active": true,
  "dialog": true,
  "endpoints": ["https://your-domain.com/updates/desktop/{{target}}/{{current_version}}"],
  "pubkey": "---BEGIN PUBLIC KEY---..."
}
```

## 2. Build with Updater Support

```bash
# Build for production (Windows)
$env:TAURI_PRIVATE_KEY = Get-Content -Raw ~/.tauri/leadgen.key
$env:TAURI_KEY_PASSWORD = "your-key-password"
npm run tauri build

# The signed MSI/NSIS installer will be in src-tauri/target/release/bundle/
```

## 3. Host Update Manifests

Place the JSON update manifest at the URL matching your endpoint pattern:

```
https://your-domain.com/updates/desktop/windows-x86_64/1.0.0
```

### JSON Manifest Format

```json
{
  "version": "1.1.0",
  "notes": "Bug fixes and performance improvements",
  "pub_date": "2025-01-15T12:00:00Z",
  "platforms": {
    "windows-x86_64": {
      "signature": "dW50cnVzdGVkIGNvbW1lbnQ...",
      "url": "https://your-domain.com/releases/LeadGenPro_1.1.0_x64-setup.msi"
    },
    "darwin-x86_64": {
      "signature": "dW50cnVzdGVkIGNvbW1lbnQ...",
      "url": "https://your-domain.com/releases/LeadGenPro_1.1.0_x64.dmg"
    },
    "darwin-aarch64": {
      "signature": "dW50cnVzdGVkIGNvbW1lbnQ...",
      "url": "https://your-domain.com/releases/LeadGenPro_1.1.0_aarch64.dmg"
    },
    "linux-x86_64": {
      "signature": "dW50cnVzdGVkIGNvbW1lbnQ...",
      "url": "https://your-domain.com/releases/LeadGenPro_1.1.0_amd64.AppImage"
    }
  }
}
```

### Getting the Signature

After each build, the updater artifact includes a `.sig` file alongside the installer. Use this content as the `signature` value in the manifest.

```bash
# The signature is generated during build when TAURI_PRIVATE_KEY is set
# The .sig file will be next to your installer in the release/bundle directory
```

## 4. Hosting Recommendations

- **Static file server**: Any CDN, S3 bucket, or GitHub Releases
- **GitHub Releases**: Upload the installer + `.sig` file to a release, then point the manifest URL at a raw JSON file
- **Content-Type**: Serve the manifest as `application/json`
- **CORS**: Ensure your server allows cross-origin requests from the app

## 5. Update Flow

1. App launches → calls `check_update` command
2. Tauri fetches manifest from endpoint URL
3. Compares remote version with local version (`package.version` in tauri.conf.json)
4. If newer → user clicks Install → `install_update` downloads and applies
5. App requires restart after update
