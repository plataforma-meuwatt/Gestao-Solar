/**
 * Talk Solar — processo principal.
 *
 * App SEPARADO do "meuPlano Ferramentas de Campo" de propósito: são duas ferramentas com
 * ciclos de vida diferentes. O de campo é aberto quando se vai analisar ensaio; este fica
 * ABERTO O DIA INTEIRO, mora na bandeja e precisa avisar. Misturar os dois faria fechar a
 * análise fechar o mensageiro da empresa.
 *
 * O que o processo principal faz — e que o renderer, em sandbox, não pode fazer:
 *
 * · BANDEJA e "fechar não fecha": clicar no X esconde. Um mensageiro que some quando alguém
 *   fecha a janela sem querer para de receber, e a pessoa só descobre horas depois.
 * · NOTIFICAÇÃO NATIVA do Windows, com clique que traz a conversa certa para a frente.
 * · CONTADOR no ícone da barra de tarefas (overlay), que é o aviso que se vê sem ler nada.
 * · GUARDA A SESSÃO em disco (userData), fora do alcance do JavaScript da tela.
 * · Auto-update pelo mesmo servidor de sempre, num caminho próprio (/conversa).
 */
const {
  app, BrowserWindow, Menu, Notification, Tray, dialog, ipcMain, nativeImage, nativeTheme,
  shell,
} = require('electron');
const path = require('path');
const fs = require('fs');

let win = null;
let tray = null;
let saindoDeVerdade = false;

const ARQUIVO_SESSAO = () => path.join(app.getPath('userData'), 'sessao.json');

// ---------------------------------------------------------------- instância única
// Duas cópias do mensageiro abertas significam dois WebSockets, duas notificações do mesmo
// recado e um contador que nunca zera. A segunda cópia só traz a primeira para a frente.
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => mostrarJanela());
}

function icone() {
  const p = path.join(__dirname, '..', 'Assets', 'icone.ico');
  return fs.existsSync(p) ? p : undefined;
}

function criarJanela() {
  nativeTheme.themeSource = 'dark';
  win = new BrowserWindow({
    width: 1180,
    height: 780,
    minWidth: 900,
    minHeight: 560,
    backgroundColor: '#0B0E14',
    autoHideMenuBar: true,
    icon: icone(),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  win.setMenuBarVisibility(false);
  win.loadFile(path.join(__dirname, '..', 'app', 'index.html'));

  // link do sistema abre no navegador — a janela do mensageiro não vira browser
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:/.test(url)) shell.openExternal(url);
    return { action: 'deny' };
  });

  // FECHAR ESCONDE. É a diferença entre "fechei a janela" e "saí do mensageiro" — e só o
  // menu da bandeja faz a segunda coisa.
  win.on('close', (e) => {
    if (!saindoDeVerdade) {
      e.preventDefault();
      win.hide();
    }
  });
}

function mostrarJanela() {
  if (!win) return criarJanela();
  if (win.isMinimized()) win.restore();
  win.show();
  win.focus();
}

function criarBandeja() {
  const img = icone();
  tray = new Tray(img ? nativeImage.createFromPath(img) : nativeImage.createEmpty());
  tray.setToolTip('Talk Solar');
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: 'Abrir', click: () => mostrarJanela() },
    { type: 'separator' },
    { label: 'Sair', click: () => { saindoDeVerdade = true; app.quit(); } },
  ]));
  tray.on('click', () => (win && win.isVisible() ? win.hide() : mostrarJanela()));
}

// ---------------------------------------------------------------- sessão em disco
function lerSessao() {
  try {
    return JSON.parse(fs.readFileSync(ARQUIVO_SESSAO(), 'utf8'));
  } catch {
    return null;
  }
}

function gravarSessao(dados) {
  try {
    if (dados === null) fs.rmSync(ARQUIVO_SESSAO(), { force: true });
    else fs.writeFileSync(ARQUIVO_SESSAO(), JSON.stringify(dados), 'utf8');
    return true;
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------- atualização
function configurarAtualizacoes() {
  if (!app.isPackaged) return;
  let autoUpdater;
  try {
    ({ autoUpdater } = require('electron-updater'));
  } catch {
    return;
  }
  autoUpdater.autoDownload = true;
  autoUpdater.on('update-downloaded', async () => {
    const r = await dialog.showMessageBox(win, {
      type: 'info',
      buttons: ['Reiniciar agora', 'Depois'],
      defaultId: 0,
      title: 'Atualização pronta',
      message: 'Uma versão nova do Talk Solar foi baixada.',
    });
    if (r.response === 0) {
      saindoDeVerdade = true;
      autoUpdater.quitAndInstall();
    }
  });
  autoUpdater.checkForUpdates().catch(() => {});
  setInterval(() => autoUpdater.checkForUpdates().catch(() => {}), 60 * 60 * 1000);
}

app.whenReady().then(() => {
  criarJanela();
  criarBandeja();
  configurarAtualizacoes();
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) criarJanela();
  });
});

// no Windows o app VIVE na bandeja: fechar a última janela não encerra
app.on('window-all-closed', (e) => { e.preventDefault(); });
app.on('before-quit', () => { saindoDeVerdade = true; });

// ---------------------------------------------------------------- ponte com a tela
ipcMain.handle('sessao-ler', () => lerSessao());
ipcMain.handle('sessao-gravar', (_e, dados) => gravarSessao(dados));
ipcMain.handle('app-info', () => ({
  versao: app.getVersion(), nome: app.getName(), empacotado: app.isPackaged,
}));

/** Notificação nativa. Clicar traz a janela E leva ao canal certo. */
ipcMain.handle('notificar', (_e, { titulo, corpo, canalId }) => {
  if (!Notification.isSupported()) return false;
  const n = new Notification({ title: titulo, body: corpo, icon: icone(), silent: false });
  n.on('click', () => {
    mostrarJanela();
    if (win && canalId) win.webContents.send('abrir-canal', canalId);
  });
  n.show();
  return true;
});

/** O CONTADOR no ícone da barra de tarefas: o aviso que se vê sem ler nada.
 *  Desenhado aqui porque overlay de ícone é coisa do processo principal. */
ipcMain.handle('badge', (_e, n) => {
  if (!win) return false;
  if (!n) {
    win.setOverlayIcon(null, '');
    return true;
  }
  const txt = n > 9 ? '9+' : String(n);
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32">
    <circle cx="16" cy="16" r="15" fill="#ef4444"/>
    <text x="16" y="22" font-size="17" font-family="Segoe UI, sans-serif" font-weight="bold"
          text-anchor="middle" fill="#fff">${txt}</text></svg>`;
  const img = nativeImage.createFromDataURL(
    'data:image/svg+xml;base64,' + Buffer.from(svg).toString('base64'));
  win.setOverlayIcon(img, `${n} não lidas`);
  return true;
});

ipcMain.handle('abrir-externo', (_e, url) => {
  if (/^https?:/.test(url || '')) shell.openExternal(url);
});
