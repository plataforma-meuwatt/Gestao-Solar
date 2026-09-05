# Talk Solar

O mensageiro da equipe de O&M solar: conversa em tempo real, com foto e arquivo, **ligada às
usinas, OSs e tarefas** dos sistemas que a empresa já usa.

> ### ⚠ Esta pasta é um PROJETO INDEPENDENTE, hospedado temporariamente aqui
>
> Ela nasceu dentro do repositório do **meuPlano** só porque foi aqui que se descobriu o que
> faltava. **O destino é o repositório do Gestão Solar**, e a mudança é literalmente mover a
> pasta: nada aqui dentro importa uma linha do meuPlano.
>
> - **banco próprio** (o Supabase do Gestão Solar), com migrations próprias;
> - **serviço próprio** no Railway, que sobe e cai sem afetar o meuPlano;
> - **integração só por HTTP**: nem o servidor nem o app de PC conhecem o banco de ninguém.
>
> Como levar: `git mv talkSolar <repo-do-gestao-solar>/` — e apagar daqui. O passo a passo
> completo, com o que criar no Railway e no Supabase, está em **[docs/ENTREGA.md](docs/ENTREGA.md)**.

---

## O desenho em uma frase

O Talk Solar **não tem cadastro de usuário, não tem senha e não sabe o que é uma usina**. Ele é
um mensageiro puro, e **empresta** a identidade e o vocabulário de cada sistema integrado.

```
   meuPlano ────┐                          ┌── (1) de quem é este token?
   meuWatt  ────┼──►  TALK SOLAR  ─────────┼── (2) o que este usuário pode citar?
Gestão Solar ───┘   (banco próprio)        └── (3) como se chama este alvo?

             ◄──────── webhooks: "houve conversa na OS 1016"
```

Três sistemas com login próprio **não podem virar quatro**. Duplicar identidade cria a pergunta
"qual senha é a certa?" e o dia em que alguém desligado no meuPlano continua conversando.

Integrar um sistema novo é implementar **três endpoints** — e só o primeiro é obrigatório.
Contrato completo em **[docs/API.md](docs/API.md)**; o passo a passo com código pronto para
copiar em **[docs/INTEGRACAO.md](docs/INTEGRACAO.md)**.

---

## Estrutura

```
server/       o servidor (FastAPI + Postgres próprio). É ele que vira o serviço no Railway.
desktop/      o app de PC (Electron): bandeja, notificação nativa, colar imagem, citar.
integracoes/  implementação de REFERÊNCIA por sistema — o que o meuPlano expõe hoje.
docs/         API.md (contrato) · INTEGRACAO.md (como plugar) · ENTREGA.md (o que falta)
```

## Rodar

```bash
# servidor
cd server
python -m venv venv && venv\Scripts\activate     # Windows
pip install -r requirements.txt
copy .env.exemplo .env                            # preencha DATABASE_URL e TALK_JWT_SECRET
alembic upgrade head
uvicorn app.main:app --reload --port 8110         # docs em /docs, saúde em /saude

# app de PC
cd desktop
npm install
npm start        # a tela de login pergunta qual sistema e qual servidor
npm test         # roda em node, sem Electron
```

Ou, da raiz do repositório: `.\dev.ps1 -Talk` (sobe o servidor junto com o Gestão Solar).

**A porta é a 8110, não a 8100.** Este projeto veio do repositório do meuPlano, onde a 8100
estava livre; aqui ela é do BFF do Gestão Solar. As outras também têm dono — 5180 painel,
5181 portal, 8081 Metro do Expo. Porta repetida não dá erro claro: ou o segundo servidor
recusa subir, ou quem chama encontra o programa errado atendendo no endereço certo.

⚠ **Os testes exigem o `PYTHONPATH` VAZIO.** Este projeto e o BFF têm, cada um, um pacote
chamado `app`. Com o `PYTHONPATH` do BFF exportado, `testes/test_contrato.py` morre em
`ImportError: cannot import name 'webhooks' from 'app'` — que parece defeito do projeto e
não é.

## Estado

| Parte | Estado |
|---|---|
| Contrato da API | ✅ escrito e implementado |
| Servidor: sessão, canais, mensagens, anexos, citações, tempo real | ✅ |
| Webhooks (saída com HMAC + reenvio, e entrada) | ✅ |
| Integração de referência (meuPlano) | ✅ endpoints prontos neste repositório |
| App de PC | ✅ funcional (falta ícone próprio) |
| meuWatt e Gestão Solar | ⏳ **é o trabalho do próximo programador** — ver ENTREGA.md |
