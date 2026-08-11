import { create } from 'zustand';

interface AppState {
  apiUrl: string;
  apiKey: string;
  operatorKey: string;
  tenantId?: string;
  setApiUrl: (url: string) => void;
  setApiKey: (key: string) => void;
  setOperatorKey: (key: string) => void;
  setTenantId: (tenantId?: string) => void;
}

const defaultApiKey =
  process.env.NEXT_PUBLIC_API_KEY ||
  process.env.NEXT_PUBLIC_RUN_KEY ||
  'development-key';

export const useAppStore = create<AppState>((set) => ({
  apiUrl: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000',
  apiKey: defaultApiKey,
  operatorKey: process.env.NEXT_PUBLIC_OPERATOR_KEY || 'dev-operator-key',
  tenantId: process.env.NEXT_PUBLIC_TENANT_ID || undefined,
  setApiUrl: (url) => set({ apiUrl: url }),
  setApiKey: (key) => set({ apiKey: key }),
  setOperatorKey: (key) => set({ operatorKey: key }),
  setTenantId: (tenantId) => set({ tenantId }),
}));
