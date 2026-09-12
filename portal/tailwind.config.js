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
        // O CROMO — a barra do topo e o trilho da esquerda. Os valores são os MESMOS do
        // meuWatt (`--color-topbar-bg` e `--color-sidebar-bg` do `mw-fe/src/index.css`),
        // e isso é deliberado: o cliente vai e volta entre os dois produtos na mesma
        // reunião, e o casco é a primeira coisa que diz "é a mesma família". Os dois são
        // translúcidos e contam com o `backdrop-blur` por baixo.
        topbar: 'rgba(6,14,44,0.5)',
        trilho: 'rgba(4,10,34,0.5)',
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
  //
  // **Os degraus de alfa são uma escada fechada, e é `lib/tons.ts` quem a nomeia.** Um alfa
  // que não esteja aqui e seja montado a partir do `tom` do servidor (`bg-tom-${tom}/6`) não
  // emite classe nenhuma: o elemento sai SEM fundo, e nada acusa — não há erro de build, de
  // tipo nem de console, só uma faixa transparente na tela. O redesenho de 09/2026 pedia
  // sete alfas diferentes (/5, /6, /7, /16, /28, /32, /35, /55); em vez de safelistar cada
  // capricho, eles foram reduzidos a cinco degraus com nome e papel, declarados em
  // `classesDoTom`. Precisa de um sexto? Ele entra aqui E lá, no mesmo commit.
  safelist: [
    { pattern: /^(text|bg|border|fill|stroke)-tom-(parado|alerta|multiplos|tempoRuim|ok|semDados)$/ },
    {
      pattern:
        /^(bg|border)-tom-(parado|alerta|multiplos|tempoRuim|ok|semDados)\/(6|10|16|20|30|40|55)$/,
    },
  ],
  plugins: [],
}
