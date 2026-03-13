// MIT License -- see LICENSE-MIT
import { app, BrowserWindow, ipcMain, safeStorage } from "electron";
import path from "path";
import fs from "fs";

const isDev = !app.isPackaged;

// ---------------------------------------------------------------------------
// Secure token storage using Electron's safeStorage API.
//
// Tokens are encrypted via the OS keychain (macOS Keychain, Windows DPAPI,
// Linux Secret Service / libsecret) and persisted to disk in the app's
// userData directory.
// ---------------------------------------------------------------------------

function getTokenPath(key: string): string {
  const safeKey = key.replace(/[^a-zA-Z0-9_-]/g, "_");
  return path.join(app.getPath("userData"), `token_${safeKey}.enc`);
}

function registerSecureTokenHandlers(): void {
  // Store encrypted token
  ipcMain.handle(
    "secure-token:set",
    async (_event, key: string, value: string) => {
      if (!safeStorage.isEncryptionAvailable()) {
        throw new Error("Encryption is not available on this system");
      }
      const encrypted = safeStorage.encryptString(value);
      const filePath = getTokenPath(key);
      fs.writeFileSync(filePath, encrypted);
    },
  );

  // Retrieve and decrypt token
  ipcMain.handle("secure-token:get", async (_event, key: string) => {
    const filePath = getTokenPath(key);
    if (!fs.existsSync(filePath)) {
      return null;
    }
    if (!safeStorage.isEncryptionAvailable()) {
      throw new Error("Encryption is not available on this system");
    }
    const encrypted = fs.readFileSync(filePath);
    return safeStorage.decryptString(encrypted);
  });

  // Delete token
  ipcMain.handle("secure-token:delete", async (_event, key: string) => {
    const filePath = getTokenPath(key);
    if (fs.existsSync(filePath)) {
      fs.unlinkSync(filePath);
    }
  });
}

// ---------------------------------------------------------------------------
// Window creation
// ---------------------------------------------------------------------------

function createWindow(): void {
  const mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 800,
    minHeight: 600,
    title: "RenderTrust Creator",
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, "preload.js"),
    },
  });

  if (isDev) {
    // In development, load from Vite dev server
    mainWindow.loadURL("http://localhost:5173");
    mainWindow.webContents.openDevTools();
  } else {
    // In production, load the built files
    mainWindow.loadFile(path.join(__dirname, "..", "dist", "index.html"));
  }
}

// ---------------------------------------------------------------------------
// App lifecycle handlers
// ---------------------------------------------------------------------------

app.whenReady().then(() => {
  registerSecureTokenHandlers();
  createWindow();

  app.on("activate", () => {
    // macOS: re-create window when dock icon is clicked and no windows exist
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on("window-all-closed", () => {
  // Quit on all platforms except macOS
  if (process.platform !== "darwin") {
    app.quit();
  }
});
