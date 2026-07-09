import { create } from "zustand";

// Zustand owns ephemeral client/UI state only — never a copy of server data (blueprint §11.1).
// Server data lives in TanStack Query; this store holds selection, view, and safety-UI flags.
interface UiState {
  // The global safety indicator: automation paused by the user's kill switch (blueprint §13.1).
  automationPaused: boolean;
  setAutomationPaused: (paused: boolean) => void;
}

export const useUiStore = create<UiState>((set) => ({
  automationPaused: false,
  setAutomationPaused: (paused) => set({ automationPaused: paused }),
}));
