// Where the board finds the FastAPI backend (backend/main.py).
// Override with VITE_API_BASE if the backend runs somewhere else.
export const API_BASE: string = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

// How often the board refreshes while a ticket is running, and while idle.
export const POLL_RUNNING_MS = 1200;
export const POLL_IDLE_MS = 5000;
