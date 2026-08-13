import react from '@vitejs/plugin-react'
import path from 'node:path'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  // O painel é um serviço próprio e vive na raiz do domínio dele. Já viveu sob `/painel`,
  // quando o BFF o servia; hoje quem o serve é o nginx de `painel/Dockerfile`, e um base
  // diferente de `/` faria os assets apontarem para uma pasta que não existe — tela em
  // branco, sem erro visível além de 404 no console.
  base: '/',
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  server: {
    port: 5180,
    // Em desenvolvimento o painel fala com o BFF por proxy, e não por CORS. Assim a
    // origem é a mesma, `window.__GS_API__` fica vazio, e o caminho exercitado localmente
    // é o mesmo de produção: sempre `/api/painel/...`, relativo à base configurada.
    proxy: {
      '/api': { target: 'http://localhost:8100', changeOrigin: true },
    },
  },
  build: {
    // Fica dentro do próprio projeto. O `../bff/app/web/painel` de antes existia porque o
    // BFF servia estes arquivos — com serviços separados, um build que escreve dentro do
    // outro projeto é justamente o acoplamento que a separação desfaz.
    outDir: 'dist',
    emptyOutDir: true,
  },
})
