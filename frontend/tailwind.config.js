/** JETPOS Tailwind yapılandırması — çıktı: backend/apps/web/static/web/app.css */
module.exports = {
  darkMode: "class",
  content: ["../backend/apps/web/templates/**/*.html", "../backend/apps/web/static/web/js/**/*.js"],
  theme: {
    extend: {
      colors: {
        ink: { DEFAULT: "#252936", 50: "#F5F6F8", 100: "#E7E9EE", 200: "#C9CDD8", 300: "#9AA0B1", 400: "#6B7286", 500: "#4A5062", 600: "#363B4B", 700: "#2D3140", 800: "#252936", 900: "#1A1D27", 950: "#12141B" },
        jet: { DEFAULT: "#F28C28", 50: "#FEF4EA", 100: "#FDE4CB", 200: "#FAC68F", 300: "#F7A85A", 400: "#F28C28", 500: "#DB7514", 600: "#B65E0F", 700: "#8F4A0F", 800: "#6B3810", 900: "#4A270C" },
      },
      fontFamily: { sans: ["Segoe UI", "Inter", "system-ui", "-apple-system", "Roboto", "Arial", "sans-serif"] },
      boxShadow: { card: "0 1px 2px rgba(16,18,27,.06), 0 1px 3px rgba(16,18,27,.08)" },
    },
  },
  plugins: [],
};
