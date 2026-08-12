import react from '@vitejs/plugin-react'
import path from 'node:path'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  // O painel vive sob /painel no BFF: sem isto os assets sairiam apontando para a raiz
  // e a página carregaria em branco em produção.
  base: '/painel/',
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  server: {
    port: 5180,
    // Em desenvolvimento o painel roda em porta própria e fala com o BFF por proxy:
    // sem isso o navegador barra a chamada por origem cruzada, e ligar CORS no BFF só
    // para o dev seria afrouxar o servidor por causa da ferramenta.
    proxy: {
      '/api': { target: 'http://localhost:8100', changeOrigin: true },
    },
  },
  build: {
    // O BFF serve os arquivos prontos; ver `app/main.py`.
    outDir: '../bff/app/web/painel',
    emptyOutDir: true,
  },
})
