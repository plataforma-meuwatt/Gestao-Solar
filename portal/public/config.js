// Endereço da API, resolvido em tempo de execução.
//
// Substituído quando o contêiner sobe (ver `entrypoint.sh`), a partir da variável `API_URL`
// do serviço. É o que permite ao MESMO artefato de build servir homologação e produção —
// trocar de ambiente é trocar uma variável, não reconstruir.
//
// Vazio aqui de propósito: em desenvolvimento o Vite faz proxy de `/api` para o BFF local
// (ver `vite.config.ts`), então a origem relativa é a correta.
window.__GS_API__ = ''
