/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#0a0f1a",
          900: "#0e1626",
          800: "#16203a",
          700: "#1f2c4d",
        },
        signal: {
          green: "#34d399",
          amber: "#fbbf24",
          orange: "#fb923c",
          red: "#f87171",
          blue: "#60a5fa",
        },
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};
