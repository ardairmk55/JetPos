// Seçili Lucide ikonlarını tek JS dosyasına, IBM Plex Sans (latin + latin-ext) fontlarını statik klasöre kopyalar.
// Çalıştır: npm run assets   (LAN/offline çalışma için CDN kullanılmaz)
import fs from "node:fs";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..", "backend", "apps", "web", "static", "web");
const iconsDir = path.resolve(import.meta.dirname, "node_modules", "lucide-static", "icons");
const fontSrc = path.resolve(import.meta.dirname, "node_modules", "@fontsource", "ibm-plex-sans", "files");

const ICONS = [
  "layout-dashboard", "search", "bell", "layout-grid", "smartphone", "chef-hat", "bell-ring", "circle-check", "receipt",
  "wallet", "credit-card", "trending-up", "chart-column", "book-open", "package", "users", "bike", "calendar-days",
  "id-card", "building-2", "key-round", "plug", "printer", "database-backup", "activity", "settings", "life-buoy",
  "circle-help", "message-square", "globe", "scroll-text", "clock", "menu", "x", "chevron-down", "chevron-right",
  "chevrons-left", "chevrons-right", "sun", "moon", "languages", "log-out", "lock", "user-round", "plus", "pencil",
  "trash-2", "check", "minus", "arrow-left", "ellipsis", "star", "utensils", "banknote", "coins", "split", "percent",
  "qr-code", "maximize", "refresh-cw", "triangle-alert", "circle-alert", "info", "wifi-off", "history", "send",
  "file-text", "download", "inbox", "store", "sliders-horizontal", "panel-left", "hand-coins", "square-check",
  "ban", "shield-check", "ticket", "package-open", "copy", "eye", "flame", "arrow-up", "arrow-down", "calendar",
  "shopping-bag", "monitor", "tablet", "file-down", "upload", "wrench", "tag", "undo-2",
];

const out = {};
const missing = [];
for (const name of ICONS) {
  const f = path.join(iconsDir, `${name}.svg`);
  if (!fs.existsSync(f)) { missing.push(name); continue; }
  const svg = fs.readFileSync(f, "utf8");
  const inner = svg.replace(/^[\s\S]*?<svg[^>]*>/, "").replace(/<\/svg>\s*$/, "").replace(/\s+/g, " ").trim();
  out[name] = inner;
}
if (missing.length) { console.error("Eksik ikon:", missing.join(", ")); process.exit(1); }

const js = `/* Lucide ikonları (ISC lisansı) — frontend/build-assets.mjs ile üretilir, elle düzenlemeyin. */
(function () {
  const PATHS = ${JSON.stringify(out)};
  window.J = window.J || {};
  /** İkon: tek stil (24px ızgara, 2px çizgi, currentColor). size: px. */
  J.icon = (name, size = 18, cls = "") => {
    const p = PATHS[name];
    if (!p) return "";
    return '<svg class="ic ' + cls + '" width="' + size + '" height="' + size + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">' + p + "</svg>";
  };
  J.hasIcon = (name) => !!PATHS[name];
})();
`;
fs.writeFileSync(path.join(root, "js", "icons.js"), js);

const fontsOut = path.join(root, "fonts");
fs.mkdirSync(fontsOut, { recursive: true });
let n = 0;
for (const w of [400, 500, 600]) for (const sub of ["latin", "latin-ext"]) {
  const file = `ibm-plex-sans-${sub}-${w}-normal.woff2`;
  fs.copyFileSync(path.join(fontSrc, file), path.join(fontsOut, file));
  n++;
}
console.log(`icons.js: ${Object.keys(out).length} ikon, ${n} font dosyası`);
