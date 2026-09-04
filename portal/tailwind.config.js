/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      // Os tokens de `app/src/theme/tokens.ts`, com os mesmos nomes em português. Fonte
      // única de cor do portal: nenhum hexadecimal fora deste arquivo — o `grep` por
      // `#RRGGBB` em `src/components` tem de voltar vazio.
      colors: {
        fundo: '#02061A',
        superficie: 'rgba(255,255,255,0.04)',
        'superficie-alta': 'rgba(255,255,255,0.08)',
        'superficie-destacada': 'rgba(255,255,255,0.12)',
        afundado: 'rgba(0,0,0,0.25)',
        // Fundo de modal, drawer e popover: opaco o bastante para o texto de trás não
        // atravessar, e um pouco mais claro que o fundo para a caixa se destacar.
        painel: 'rgba(9,14,38,0.97)',
        borda: 'rgba(255,255,255,0.08)',
        'borda-fraca': 'rgba(255,255,255,0.06)',
        'borda-forte': 'rgba(255,255,255,0.12)',
        ambar: '#FFC315',
        'ambar-texto': '#FFD75E',
        forte: '#F5FDFF',
        corpo: '#DDE2F6',
        rotulo: '#D6C4AC',
        fraco: '#94A3B8',
        // Os seis tons de status, com as MESMAS chaves que o BFF escreve em `tom`
        // (`parado|alerta|multiplos|tempoRuim|ok|semDados`): a tela faz `text-tom-${tom}`
        // a partir do que o servidor mandou, sem tabela de tradução no meio. Não existe
        // sétimo tom — cor nova é cor que o cliente não sabe ler.
        tom: {
          parado: '#F87171',
          alerta: '#FBBF24',
          multiplos: '#FB923C',
          tempoRuim: '#7DD3FC',
          ok: '#34D399',
          semDados: '#94A3B8',
        },
      },
      fontFamily: {
        sans: ['Figtree', 'system-ui', '-apple-system', 'Segoe UI', 'sans-serif'],
        mono: ['IBM Plex Mono', 'ui-monospace', 'Cascadia Mono', 'Menlo', 'monospace'],
      },
      // Os raios de `app/src/theme/tokens.ts` (`raio`). `chip` e `barra` não são enfeite:
      // `Selo` e `Barra` já os usavam e, sem a entrada aqui, o Tailwind não emite a classe —
      // o selo saía quadrado e a barra de progresso, com a quina viva.
      borderRadius: { card: '16px', campo: '12px', chip: '12px', barra: '3px' },
    },
  },
  // As classes de tom são montadas a partir do valor que vem do servidor; o Tailwind não
  // as enxerga no fonte e as descartaria do CSS. A lista abaixo garante cada uma.
  safelist: [
    { pattern: /^(text|bg|border|fill|stroke)-tom-(parado|alerta|multiplos|tempoRuim|ok|semDados)$/ },
    { pattern: /^(bg|border)-tom-(parado|alerta|multiplos|tempoRuim|ok|semDados)\/(10|20|30|40)$/ },
  ],
  plugins: [],
}
