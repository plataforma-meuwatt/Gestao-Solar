/**
 * A ponte entre a tela (sandbox) e o processo principal.
 *
 * O que passa por aqui é só o que a tela NÃO PODE fazer sozinha: guardar a sessão em disco,
 * notificar o Windows, desenhar o contador no ícone e abrir link no navegador. Rede, conversa
 * e estado ficam no renderer — a superfície exposta é pequena de propósito.
 */
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('talkSolar', {
  info: () => ipcRenderer.invoke('app-info'),
  //: a sessão mora em disco, fora do alcance do JavaScript da página
  lerSessao: () => ipcRenderer.invoke('sessao-ler'),
  gravarSessao: (dados) => ipcRenderer.invoke('sessao-gravar', dados),
  notificar: (dados) => ipcRenderer.invoke('notificar', dados),
  badge: (n) => ipcRenderer.invoke('badge', n),
  abrirExterno: (url) => ipcRenderer.invoke('abrir-externo', url),
  //: clicar na notificação do Windows abre o canal certo
  aoAbrirCanal: (cb) => ipcRenderer.on('abrir-canal', (_e, cid) => cb(cid)),
});
