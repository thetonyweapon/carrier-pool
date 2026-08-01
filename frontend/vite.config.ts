import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { "/api": { target: "http://localhost:8000", rewrite: (path) => path.replace(/^\/api/, "") } },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    css: true,
    restoreMocks: true,
    exclude: ["e2e/**", "node_modules/**"],
    coverage: {
      provider: "v8",
      reporter: ["text", "html"],
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/test/**", "**/*.test.{ts,tsx}"],
      thresholds: { statements: 70, branches: 55, functions: 65, lines: 75 },
    },
  },
});
