const { app, BrowserWindow, Tray, Menu, dialog, nativeImage, ipcMain } = require('electron');
const path = require('path');
const fs = require('fs');
const { autoUpdater } = require('electron-updater');

const SETTINGS_DIR = path.join(require('os').homedir(), '.leadforge');
const SETTINGS_FILE = path.join(SETTINGS_DIR, 'settings.json');
const WINDOW_STATE_FILE = path.join(SETTINGS_DIR, 'window-state.json');

let mainWindow = null;
let tray = null;
let isQuitting = false;

function loadSettings() {
  try {
    if (fs.existsSync(SETTINGS_FILE)) {
      return JSON.parse(fs.readFileSync(SETTINGS_FILE, 'utf8'));
    }
  } catch (e) {
    console.error('Failed to load settings:', e);
  }
  return { serverUrl: 'http://localhost:8080/app' };
}

function saveSettings(settings) {
  try {
    if (!fs.existsSync(SETTINGS_DIR)) {
      fs.mkdirSync(SETTINGS_DIR, { recursive: true });
    }
    fs.writeFileSync(SETTINGS_FILE, JSON.stringify(settings, null, 2), 'utf8');
  } catch (e) {
    console.error('Failed to save settings:', e);
  }
}

function loadWindowState() {
  try {
    if (fs.existsSync(WINDOW_STATE_FILE)) {
      return JSON.parse(fs.readFileSync(WINDOW_STATE_FILE, 'utf8'));
    }
  } catch (e) {
    console.error('Failed to load window state:', e);
  }
  return { width: 1200, height: 800 };
}

function saveWindowState() {
  if (!mainWindow) return;
  try {
    const bounds = mainWindow.getBounds();
    const state = { width: bounds.width, height: bounds.height, x: bounds.x, y: bounds.y };
    if (!fs.existsSync(SETTINGS_DIR)) {
      fs.mkdirSync(SETTINGS_DIR, { recursive: true });
    }
    fs.writeFileSync(WINDOW_STATE_FILE, JSON.stringify(state, null, 2), 'utf8');
  } catch (e) {
    console.error('Failed to save window state:', e);
  }
}

function showSettingsDialog() {
  const settings = loadSettings();
  const result = dialog.showMessageBoxSync(mainWindow, {
    type: 'info',
    title: 'LeadForge - Server Configuration',
    message: 'Configure your LeadForge server URL',
    detail: 'Enter the URL of your LeadForge server below.\nDefault: http://localhost:8080/app',
    buttons: ['OK', 'Use Default']
  });

  if (result === 0) {
    const { response } = dialog.showInputBoxSync
      ? dialog.showInputBoxSync(mainWindow, {
          type: 'input',
          title: 'Server URL',
          message: 'LeadForge Server URL:',
          value: settings.serverUrl
        })
      : { response: null };

    if (response) {
      settings.serverUrl = response;
      saveSettings(settings);
    }
  }
}

function createWindow() {
  const state = loadWindowState();
  const settings = loadSettings();

  mainWindow = new BrowserWindow({
    width: state.width || 1200,
    height: state.height || 800,
    minWidth: 900,
    minHeight: 600,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false
    },
    show: false,
    title: 'LeadForge'
  });

  if (state.x !== undefined && state.y !== undefined) {
    mainWindow.setPosition(state.x, state.y);
  }

  mainWindow.loadFile(path.join(__dirname, 'renderer', 'index.html'));

  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
  });

  mainWindow.on('close', (e) => {
    if (!isQuitting) {
      e.preventDefault();
      mainWindow.hide();
    }
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });

  mainWindow.on('resize', saveWindowState);
  mainWindow.on('move', saveWindowState);

  createMenu();
  createTray();

  if (!settings.firstRunDone) {
    settings.firstRunDone = true;
    saveSettings(settings);
    showSettingsDialog();
  }
}

function createMenu() {
  const template = [
    {
      label: 'File',
      submenu: [
        {
          label: 'Settings',
          accelerator: 'CmdOrCtrl+,',
          click: () => showSettingsDialog()
        },
        { type: 'separator' },
        {
          label: 'Quit',
          accelerator: 'CmdOrCtrl+Q',
          click: () => {
            isQuitting = true;
            app.quit();
          }
        }
      ]
    },
    {
      label: 'View',
      submenu: [
        { label: 'Reload', accelerator: 'CmdOrCtrl+R', role: 'reload' },
        { type: 'separator' },
        { label: 'Toggle DevTools', accelerator: 'F12', role: 'toggleDevTools' }
      ]
    },
    {
      label: 'Help',
      submenu: [
        {
          label: 'About LeadForge',
          click: () => {
            dialog.showMessageBox(mainWindow, {
              type: 'info',
              title: 'About LeadForge',
              message: 'LeadForge v' + app.getVersion(),
              detail: 'Home Improvement Lead Generation Platform\nMetanoia Unlimited LLC'
            });
          }
        }
      ]
    }
  ];

  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

function createTray() {
  const iconSize = 16;
  const icon = nativeImage.createEmpty();
  tray = new Tray(icon);
  tray.setToolTip('LeadForge');

  const contextMenu = Menu.buildFromTemplate([
    {
      label: 'Show App',
      click: () => {
        if (mainWindow) {
          mainWindow.show();
          mainWindow.focus();
        }
      }
    },
    {
      label: 'Open DevTools',
      click: () => {
        if (mainWindow) {
          mainWindow.webContents.openDevTools();
        }
      }
    },
    { type: 'separator' },
    {
      label: 'Quit',
      click: () => {
        isQuitting = true;
        app.quit();
      }
    }
  ]);

  tray.setContextMenu(contextMenu);

  tray.on('double-click', () => {
    if (mainWindow) {
      mainWindow.show();
      mainWindow.focus();
    }
  });
}

function setupAutoUpdater() {
  autoUpdater.autoDownload = false;
  autoUpdater.autoInstallOnAppQuit = true;

  autoUpdater.on('update-available', (info) => {
    dialog.showMessageBox(mainWindow, {
      type: 'info',
      title: 'Update Available',
      message: `Version ${info.version} is available.`,
      detail: 'Would you like to download and install the update?',
      buttons: ['Download', 'Later']
    }).then(({ response }) => {
      if (response === 0) {
        autoUpdater.downloadUpdate();
      }
    });
  });

  autoUpdater.on('update-downloaded', () => {
    dialog.showMessageBox(mainWindow, {
      type: 'info',
      title: 'Update Ready',
      message: 'Update downloaded. Restart to install?',
      buttons: ['Restart', 'Later']
    }).then(({ response }) => {
      if (response === 0) {
        autoUpdater.quitAndInstall();
      }
    });
  });

  autoUpdater.on('error', (err) => {
    console.error('Auto-updater error:', err);
  });

  autoUpdater.checkForUpdates();
}

ipcMain.on('get-server-url', (event) => {
  const settings = loadSettings();
  event.returnValue = settings.serverUrl;
});

ipcMain.on('set-server-url', (event, url) => {
  const settings = loadSettings();
  settings.serverUrl = url;
  saveSettings(settings);
});

ipcMain.on('get-version', (event) => {
  event.returnValue = app.getVersion();
});

app.whenReady().then(() => {
  createWindow();
  setupAutoUpdater();
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('activate', () => {
  if (mainWindow === null) {
    createWindow();
  } else {
    mainWindow.show();
  }
});

app.on('before-quit', () => {
  isQuitting = true;
});
