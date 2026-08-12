/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      // Mesma paleta do app e da marca. Nomes em português para o código do painel
      // ficar legível em uma língua só.
      colors: {
        fundo: '#02061A',
        superficie: 'rgba(255,255,255,0.04)',
        'superficie-alta': 'rgba(255,255,255,0.08)',
        afundado: 'rgba(0,0,0,0.25)',
        borda: 'rgba(255,255,255,0.08)',
        'borda-forte': 'rgba(255,255,255,0.12)',
        ambar: '#FFC315',
        'ambar-texto': '#FFD75E',
        forte: '#F5FDFF',
        corpo: '#DDE2F6',
        rotulo: '#D6C4AC',
        fraco: '#94A3B8',
        // Os seis tons de status, os mesmos do app.
        parado: '#F87171',
        alerta: '#FBBF24',
        multiplos: '#FB923C',
        'tempo-ruim': '#7DD3FC',
        ok: '#34D399',
        'sem-dados': '#94A3B8',
      },
      fontFamily: {
        sans: ['Figtree', 'system-ui', '-apple-system', 'Segoe UI', 'sans-serif'],
        mono: ['IBM Plex Mono', 'ui-monospace', 'Cascadia Mono', 'Menlo', 'monospace'],
      },
      borderRadius: { card: '16px', campo: '12px' },
    },
  },
  plugins: [],
}
