// MIT License -- see LICENSE-MIT
//
// Preload script for Electron renderer process.
// Exposes secure token storage via contextBridge using IPC channels
// backed by Electron's safeStorage API in the main process.

import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("electronAPI", {
  /**
   * Store a value in Electron's safeStorage (encrypted at rest).
   */
  setSecureToken: (key: string, value: string): Promise<void> =>
    ipcRenderer.invoke("secure-token:set", key, value),

  /**
   * Retrieve a value from Electron's safeStorage.  Returns null if not found.
   */
  getSecureToken: (key: string): Promise<string | null> =>
    ipcRenderer.invoke("secure-token:get", key),

  /**
   * Delete a value from Electron's safeStorage.
   */
  deleteSecureToken: (key: string): Promise<void> =>
    ipcRenderer.invoke("secure-token:delete", key),
});
