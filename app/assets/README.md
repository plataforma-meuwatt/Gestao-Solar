# Assets

Arquivos que ainda faltam para o build (Fase 8 — publicação):

| Arquivo | Tamanho | Observação |
|---|---|---|
| `icon.png` | 1024 × 1024 | Ícone do app. Fundo `#02061A`, marca em âmbar `#FFC315`. |
| `splash.png` | 1284 × 2778 | Splash. Logo centralizado sobre o fundo com halo. |
| `adaptive-icon.png` | 1024 × 1024 | Android: só o primeiro plano, com margem de segurança. |

## Fontes

As faces precisam ser adicionadas em `assets/fonts/` e registradas no `expo-font`:

- **Figtree** — Regular, Medium, SemiBold, Bold (interface)
- **IBM Plex Mono** — Regular, Medium (números, horas, séries)

São as mesmas seis faces que o meuWatt embute no motor de PDF vetorial
(`mw-fe/src/assets/fonts/`) — usar exatamente elas mantém o app e o relatório impresso
com a mesma letra.
