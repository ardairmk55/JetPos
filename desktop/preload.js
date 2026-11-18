// Yalnızca sunucu adresi ayarı için sınırlı köprü; sayfaya Node.js erişimi verilmez.
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("jetposDesktop", {
  getConfig: () => ipcRenderer.invoke("jetpos:get-config"),
  saveConfig: (cfg) => ipcRenderer.invoke("jetpos:save-config", cfg),
  isDesktop: true,
});
