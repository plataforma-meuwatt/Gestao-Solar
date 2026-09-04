/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import path from 'node:path'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  // O portal é um serviço próprio (`appgestao` no Railway) e vive na raiz do domínio dele.
  // O painel já pagou o preço de um `base` diferente de `/` quando morava sob o BFF: os
  // assets apontam para uma pasta que não existe e a tela fica branca sem erro visível.
  base: '/',
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  server: {
    // 5180 é do painel; os dois sobem juntos na máquina de quem desenvolve.
    port: 5181,
    // Em desenvolvimento o portal fala com o BFF por proxy, e não por CORS. A origem é a
    // mesma, `window.__GS_API__` fica vazio, e o caminho exercitado é o de produção:
    // `/api/v1/...` relativo à base.
    proxy: {
      '/api': { target: 'http://localhost:8100', changeOrigin: true },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.{ts,tsx}'],
  },
})
