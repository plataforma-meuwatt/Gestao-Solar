# Talk Solar — app de PC

**Talk Solar, by Gestão Solar.** O mensageiro da equipe, instalado no computador.

> Este app é o CLIENTE. O servidor está em `../server` e o contrato em `../docs/API.md`.

## Por que um app de PC, e não só uma aba do navegador

Ele fica **aberto o dia inteiro**: mora na bandeja, avisa com notificação do Windows e mostra o
contador no ícone da barra de tarefas. Uma aba do navegador some entre outras vinte e ninguém
percebe que chegou recado.

E fica separado do "meuPlano Ferramentas de Campo" pelo mesmo motivo: aquele abre para analisar
um ensaio e fecha; se fossem o mesmo programa, fechar a análise fecharia o mensageiro.

## Entrar

Não existe senha da Talk Solar. Você escolhe **de qual sistema vem a sua identidade** (meuPlano,
Gestão Solar, meuWatt), entra com a senha DAQUELE sistema, e o app troca esse token por uma
sessão aqui. É o que permite desligar alguém em UM lugar.

## Rodar

```bash
npm install
npm start      # abre o app
npm test       # 12 testes, rodam em node, sem Electron
npm run dist   # instalador Windows em dist/
```

Na tela de login, em **Servidores**, dá para apontar para um servidor local durante o
desenvolvimento.

## O que tem dentro

```
electron/main.js      janela, bandeja, notificação, contador no ícone, sessão em disco, update
electron/preload.js   a ponte (pequena de propósito): só o que a tela não pode fazer sozinha
app/js/api.js         entrar (2 passos), renovar sessão, chamadas ao servidor
app/js/ui.js          pedaços de tela — e o `esc()` por onde TUDO passa antes de virar HTML
app/js/conversa.js    a tela: canais, mensagens, anexos, citação, tempo real
testes/talk.js        o que quebra em silêncio: escapada, senha vazando, renovação, formato
```

## Pendências

- **Ícone próprio** (hoje reusa o do app de campo).
- O servidor de atualização precisa servir o caminho `/talksolar` (ou troque a URL no
  `package.json`).
- Rolar para trás no histórico: o servidor já aceita `?antes=`, a tela ainda não chama.
