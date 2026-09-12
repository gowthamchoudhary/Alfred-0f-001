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
        // Alfred editorial palette (from the landing design system)
        alfred: {
          bg: "#D3D2CD",
          surface: "#F1F0EC",
          main: "#F9F8F6",
          secondary: "#F0EFEB",
          warm: "#F1EFEC",
          neutral: "#F9F9F6",
          border: "#E1DFDC",
          bordersubtle: "#EAE9E6",
          text: "#3C3C3B",
        },
      },
      fontFamily: {
        sans: [
          "Inter",
          "Geist",
          "Helvetica Neue",
          "Arial",
          "ui-sans-serif",
          "system-ui",
          "sans-serif",
        ],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};
