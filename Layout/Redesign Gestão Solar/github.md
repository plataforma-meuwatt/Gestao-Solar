repo: plataforma-meuwatt/Gestao-Solar
branch: main
path: portal/

## Last sync

date: 2026-09-12T01:41:54Z

### Updated in this project

- Treze telas redesenhadas em dois turnos, com identidade própria (marca GS, régua de comparação, veredito em texto antes do dado).
- Navegação decidida: trilho lateral. Marca decidida: selo cheio.
- Pacote de handoff para o Claude Code em `design_handoff_portal_gestao_solar/`.
- `marca-meuwatt.svg` importada de `Claude Designer/referencias/` e aplicada nos cartões de conexão.

## Screen map

| Tela no projeto | Arquivos do repositório |
|---|---|
| 1p · Premissas, tokens e mapa de componentes | `portal/tailwind.config.js`, `portal/src/index.css`, `portal/src/components/base.tsx`, `portal/src/lib/tons.ts` |
| 1a · Marca GS | novo — comparada a `Claude Designer/referencias/marca-meuwatt.svg` (importada) |
| 1b / 1c · Visão geral | `portal/src/features/visao-geral/Pagina.tsx`, `portal/src/shell/Layout.tsx`, `portal/src/shell/menu.ts` |
| 1d · Painel da usina | `portal/src/features/energia/Mes.tsx`, `portal/src/features/energia/Pagina.tsx` |
| 1e · Manutenção | `portal/src/features/cronograma/FitaDosMeses.tsx`, `portal/src/features/ordens/Pagina.tsx`, `portal/src/features/pendencias/Pagina.tsx` |
| 1f · Relatórios | `portal/src/features/relatorios/Pagina.tsx` |
| 2a · Paradas | `portal/src/features/paradas/Pagina.tsx` |
| 2b · Baixar dados | `portal/src/features/dados/Pagina.tsx` |
| 2c · Comparar · Geração | `portal/src/features/comparar/Energia.tsx` |
| 2d · Comparar · Manutenção | `portal/src/features/comparar/Manutencao.tsx` |
| 2e · Entrar | `portal/src/features/entrar/Pagina.tsx`, `docs/DECISAO_IDENTIDADE.md` (apelido, não e-mail) |
| 2f · Minha conta · Conexões | `portal/src/features/conta/Pagina.tsx`, `docs/DECISAO_IDENTIDADE.md` (tokens, camadas, histórico) |
