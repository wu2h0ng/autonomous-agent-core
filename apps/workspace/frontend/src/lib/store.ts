import { create } from 'zustand';

interface AppState {
  apiUrl: string;
  runKey: string;
  setApiUrl: (url: string) => void;
  setRunKey: (key: string) => void;
}

export const useAppStore = create<AppState>((set) => ({
  apiUrl: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000',
  runKey: process.env.NEXT_PUBLIC_RUN_KEY || 'development-key',
  setApiUrl: (url) => set({ apiUrl: url }),
  setRunKey: (key) => set({ runKey: key }),
}));
