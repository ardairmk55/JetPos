// POSHANE Electron kabuğu: yerel ağdaki POSHANE sunucusunu tam ekran/pencere olarak açar.
// Sunucu adresi ilk açılışta sorulur ve kullanıcı veri klasöründe saklanır. --kds ile kiosk (tam ekran) mutfak ekranı.
const { app, BrowserWindow, ipcMain, Menu, shell } = require("electron");
const fs = require("fs");
const path = require("path");

const KDS = process.argv.includes("--kds");
const cfgPath = () => path.join(app.getPath("userData"), "jetpos.json");
const readCfg = () => { try { return JSON.parse(fs.readFileSync(cfgPath(), "utf8")); } catch (e) { return {}; } };
const writeCfg = (c) => fs.writeFileSync(cfgPath(), JSON.stringify(c, null, 2));

let win;
function createWindow() {
  const cfg = readCfg();
  win = new BrowserWindow({
    width: 1366, height: 820, minWidth: 1024, minHeight: 640, backgroundColor: "#252936", title: "POSHANE",
    kiosk: KDS || !!cfg.kiosk, autoHideMenuBar: true,
    webPreferences: { preload: path.join(__dirname, "preload.js"), contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  if (!cfg.server) return win.loadFile(path.join(__dirname, "setup.html"));
  const start = cfg.server.replace(/\/$/, "") + (KDS ? "/kds" : "/");
  win.loadURL(start).catch(() => win.loadFile(path.join(__dirname, "setup.html"), { query: { error: "1" } }));
  // Sunucu dışındaki bağlantılar varsayılan tarayıcıda açılır
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith(cfg.server) || url === "about:blank") return { action: "allow" };
    shell.openExternal(url);
    return { action: "deny" };
  });
  win.webContents.on("did-fail-load", (_e, code, desc, url) => {
    if (url && url.startsWith(cfg.server)) win.loadFile(path.join(__dirname, "setup.html"), { query: { error: desc || String(code) } });
  });
}

ipcMain.handle("jetpos:get-config", () => readCfg());
ipcMain.handle("jetpos:save-config", (_e, cfg) => {
  const clean = { server: String(cfg.server || "").trim(), kiosk: !!cfg.kiosk };
  if (!/^https?:\/\/[^\s]+$/.test(clean.server)) throw new Error("Geçersiz adres");
  writeCfg(clean);
  app.relaunch();
  app.exit(0);
});

Menu.setApplicationMenu(Menu.buildFromTemplate([
  { label: "POSHANE", submenu: [
    { label: "Sunucu ayarı", click: () => win.loadFile(path.join(__dirname, "setup.html")) },
    { label: "Yeniden yükle", accelerator: "F5", role: "reload" },
    { label: "Tam ekran", accelerator: "F11", role: "togglefullscreen" },
    { type: "separator" }, { label: "Çıkış", role: "quit" }] },
]));

app.whenReady().then(createWindow);
app.on("window-all-closed", () => app.quit());
