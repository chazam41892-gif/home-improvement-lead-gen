const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('leadforge', {
  getServerUrl: () => {
    return ipcRenderer.sendSync('get-server-url');
  },
  setServerUrl: (url) => {
    ipcRenderer.send('set-server-url', url);
  },
  getVersion: () => {
    return ipcRenderer.sendSync('get-version');
  }
});
