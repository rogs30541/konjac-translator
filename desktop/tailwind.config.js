/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#12141a",
        panel: "#1b1e27",
        panel2: "#232734",
        line: "#2e3342",
        tx: "#e8eaf0",
        tx2: "#9aa1b4",
        tx3: "#6b7288",
        brand: "#ff8fa3",
        "brand-deep": "#e5637e",
        ok: "#5ad08a",
      },
    },
  },
  plugins: [],
};
