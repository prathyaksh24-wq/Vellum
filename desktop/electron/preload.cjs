const {contextBridge, ipcRenderer} = require('electron');

// No IPC object, filesystem access, or arbitrary channel names cross this seam.
const commands = new Set(['backend_health', 'open_vellum_window', 'open_conversation_window', 'set_overlay']);
contextBridge.exposeInMainWorld('VellumDesktop', Object.freeze({
  runtime: 'electron',
  browser: Object.freeze({
    mount(data) { return ipcRenderer.invoke('vellum:browser-mount', data); },
    subscribe(callback) {
      const handler=(_event,data)=>callback(data);
      ipcRenderer.on('vellum:browser-event',handler);
      return ()=>ipcRenderer.removeListener('vellum:browser-event',handler);
    },
  }),
  invoke(command, args = {}) {
    if (!commands.has(command)) return Promise.reject(new Error('Unknown desktop command.'));
    return ipcRenderer.invoke('vellum:desktop', command, args);
  },
}));
