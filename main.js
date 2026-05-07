const { app, BrowserWindow } = require('electron');
const { spawn } = require('child_process');
const path = require('path');

let flaskProcess = null;

function startFlask() {
  const isPackaged = app.isPackaged;
  const workDir = isPackaged 
    ? process.resourcesPath 
    : __dirname;
  
  // Use system Python 3.9 for better compatibility
  const pythonCmd = '/usr/bin/python3';
  
  flaskProcess = spawn(pythonCmd, ['web_app.py'], {
    cwd: workDir,
    detached: true,
    stdio: 'ignore'
  });
  
  flaskProcess.unref();
  
  flaskProcess.on('error', (err) => {
    console.error('Flask spawn error:', err);
  });
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1200,
    height: 800,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false
    }
  });

  win.loadURL('http://localhost:5001');
  
  // Only load URL once
  win.webContents.on('did-finish-load', () => {
    // Page loaded
  });
}

app.whenReady().then(() => {
  startFlask();
  
  // Wait a bit for Flask to start
  setTimeout(() => {
    createWindow();
  }, 2000);
});

app.on('window-all-closed', () => {
  if (flaskProcess) {
    process.kill(-flaskProcess.pid, 'SIGTERM');
  }
  app.quit();
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    startFlask();
    setTimeout(createWindow, 2000);
  }
});
