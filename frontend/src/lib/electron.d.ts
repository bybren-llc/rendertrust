// MIT License -- see LICENSE-MIT
//
// Type declarations for the Electron preload API exposed via contextBridge.

export interface ElectronAPI {
  /** Store a value in Electron's safeStorage (encrypted at rest). */
  setSecureToken: (key: string, value: string) => Promise<void>;
  /** Retrieve a value from Electron's safeStorage. Returns null if not found. */
  getSecureToken: (key: string) => Promise<string | null>;
  /** Delete a value from Electron's safeStorage. */
  deleteSecureToken: (key: string) => Promise<void>;
}

declare global {
  interface Window {
    electronAPI?: ElectronAPI;
  }
}
