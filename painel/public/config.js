// Endereço da API, resolvido em tempo de execução.
//
// Este arquivo é substituído quando o contêiner sobe (ver `entrypoint.sh`), a partir da
// variável `API_URL` do serviço. É o que permite ao MESMO artefato de build servir
// desenvolvimento, homologação e produção — trocar de ambiente vira trocar uma variável,
// não reconstruir e reimplantar.
//
// A alternativa seria embutir a URL no bundle via `VITE_API_URL`. Ela é mais curta e mais
// frágil: o endereço fica congelado dentro do JavaScript, e mudar o domínio da API — ou
// promover o build de homologação para produção — exige compilar de novo, com o risco de
// o que foi testado não ser exatamente o que subiu.
//
// Vazio aqui de propósito: em desenvolvimento o Vite faz proxy de `/api` para o BFF local
// (ver `vite.config.ts`), então a origem relativa é a correta.
window.__GS_API__ = ''
