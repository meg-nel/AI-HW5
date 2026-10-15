import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The board runs on http://localhost:5173 and calls the FastAPI backend at http://localhost:8000
// (see src/config.ts). The backend allows this origin with CORS.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true },
});
