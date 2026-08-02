import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Tauri dev 固定埠;clearScreen false 保留 Rust 錯誤輸出
export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: { port: 1420, strictPort: true },
  build: { target: "chrome110", outDir: "dist" },
});
