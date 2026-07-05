# Lead Gen Pro Desktop

Desktop wrapper for the Lead Gen Pro lead generation system.

## Prerequisites
- Node.js 18+
- Rust (https://rustup.rs)
- Python 3.11+ with dependencies installed

## Setup
```bash
cd desktop
npm install
cd src-tauri
cargo build
```

## Development
```bash
cd desktop
npm run tauri dev
```

## Build
```bash
cd desktop
npm run tauri build
```

The built installer will be in `src-tauri/target/release/bundle/`.
