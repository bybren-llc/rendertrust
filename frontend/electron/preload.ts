// MIT License -- see LICENSE-MIT
//
// Preload script for Electron renderer process.
// This file runs in a sandboxed context with contextIsolation enabled.
// Use contextBridge.exposeInMainWorld() to expose APIs to the renderer.
//
// Example:
//   import { contextBridge, ipcRenderer } from "electron";
//   contextBridge.exposeInMainWorld("electronAPI", {
//     sendMessage: (channel: string, data: unknown) =>
//       ipcRenderer.send(channel, data),
//   });

export {};
