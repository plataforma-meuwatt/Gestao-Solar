"""O inventário de usinas.

O defeito que estes testes existem para impedir é o que motivou reescrever `montar`: a
versão anterior percorria só o meuWatt procurando par no meuPlano, e uma usina que existe
**apenas no meuPlano** nunca aparecia na tela. Com 16 usinas lá e 6 no meuWatt, dez
sumiam sem aviso — e manutenção sem monitoramento é um caso normal de negócio, não uma
anomalia a esconder.
"""

from dataclasses import dataclass

from app.services import conciliacao


@dataclass
class LinkFalso:
    """Um `PlantLink` sem banco — `montar` não sabe de SQLAlchemy, e não deve saber."""

    id: int
    nome: str
    mw_plant_slug: str | None = None
    mp_usina_id: int | None = None
    cidade: str | None = None
    uf: str | None = None
    kwp: float | None = None
    ativo: bool = True


MW = [
    {"slug": "porto-ferreira", "name": "Porto Ferreira", "city": "Porto Ferreira", "state": "SP"},
    {"slug": "ibitinga", "name": "Ibitinga", "city": "Ibitinga", "state": "SP"},
]
MP = [
    {"id": 1, "nome": "Porto Ferreira", "cidade": "Porto Ferreira"},
    {"id": 2, "nome": "Ibitinga"},
    {"id": 3, "nome": "Araraquara"},  # só existe no meuPlano
]


def test_usina_so_do_meuplano_aparece():
    """O defeito original. Sem isto, `Araraquara` é invisível no painel."""
    linhas = conciliacao.montar(MW, MP, [])

    so_mp = {l.nome for l in linhas if l.origem == "meuplano"}
    assert "Araraquara" in so_mp

    araraquara = next(l for l in linhas if l.nome == "Araraquara")
    assert araraquara.mp_usina_id == 3 and araraquara.mw_slug is None


def test_usina_nao_casada_aparece_dos_dois_lados_com_o_par_apontado():
    """`Ibitinga` existe nos dois produtos e ninguém casou ainda. As duas linhas ficam:
    o sistema não *sabe* que são a mesma, e esconder uma seria decidir pelo gestor.

    O que ele ganha é o apontamento — a linha do meuPlano diz de quem ela parece ser par,
    para não ser preciso cruzar os dois grupos a olho.
    """
    linhas = conciliacao.montar(MW, MP, [])
    ibitingas = [l for l in linhas if l.nome == "Ibitinga"]

    assert {l.origem for l in ibitingas} == {"meuwatt", "meuplano"}

    do_mp = next(l for l in ibitingas if l.origem == "meuplano")
    assert do_mp.par_provavel_mw == "ibitinga"
    assert do_mp.par_provavel_motivos  # diz por que

    do_mw = next(l for l in ibitingas if l.origem == "meuwatt")
    assert do_mw.candidatos[0].nome == "Ibitinga"


def test_casar_funde_as_duas_linhas_em_uma():
    """O resultado de casar: some a duplicidade, e a usina passa a existir uma vez só."""
    links = [LinkFalso(id=1, nome="Ibitinga", mw_plant_slug="ibitinga", mp_usina_id=2)]

    linhas = conciliacao.montar(MW, MP, links)
    ibitingas = [l for l in linhas if l.nome == "Ibitinga"]

    assert len(ibitingas) == 1 and ibitingas[0].origem == "ambos"


def test_cada_identificador_aparece_uma_vez_so():
    """A ordem de montagem existe por isto: uma usina casada apareceria três vezes — como
    vínculo, como 'só meuWatt' e como 'só meuPlano'."""
    links = [LinkFalso(id=1, nome="Porto Ferreira", mw_plant_slug="porto-ferreira", mp_usina_id=1)]

    linhas = conciliacao.montar(MW, MP, links)

    assert len({l.chave for l in linhas}) == len(linhas)
    assert sum(1 for l in linhas if l.mp_usina_id == 1) == 1
    assert sum(1 for l in linhas if l.mw_slug == "porto-ferreira") == 1


def test_as_tres_origens_sao_distinguidas():
    """Indexado pela chave, e não pelo nome: duas usinas homônimas em produtos diferentes
    são exatamente o caso que existe aqui, e um dicionário por nome esconderia uma delas —
    que é o defeito que esta tela toda existe para não cometer.
    """
    links = [
        LinkFalso(id=1, nome="Porto Ferreira", mw_plant_slug="porto-ferreira", mp_usina_id=1),
        LinkFalso(id=2, nome="Ibitinga", mw_plant_slug="ibitinga"),
    ]

    origens = {l.chave: l.origem for l in conciliacao.montar(MW, MP, links)}

    assert origens == {
        "link:1": "ambos",      # Porto Ferreira, casada
        "link:2": "meuwatt",    # Ibitinga do meuWatt, trazida sem par
        "mp:2": "meuplano",     # a Ibitinga do meuPlano, ainda solta
        "mp:3": "meuplano",     # Araraquara, só existe lá
    }


def test_par_provavel_nao_aponta_para_usina_ja_casada():
    """Apontar uma usina do meuWatt que já tem par seria sugerir um conflito — o servidor
    recusaria a gravação, e o gestor levaria o não depois de clicar."""
    links = [LinkFalso(id=1, nome="Ibitinga", mw_plant_slug="ibitinga", mp_usina_id=2)]

    linhas = conciliacao.montar(MW, MP, links)
    soltas_mp = [l for l in linhas if l.origem == "meuplano"]

    assert all(l.par_provavel_mw != "ibitinga" for l in soltas_mp)


def test_sem_vinculo_nenhuma_usina_esta_no_app():
    """"Existe na plataforma" e "está no aplicativo" são coisas diferentes. Toda usina
    nasce fora — quem decide é o gestor."""
    assert all(not l.no_app for l in conciliacao.montar(MW, MP, []))
    assert all(l.plant_link_id is None for l in conciliacao.montar(MW, MP, []))


def test_vinculo_desligado_continua_na_lista():
    """Desligar não é apagar: a usina some do app, não da tela do gestor — senão religá-la
    exigiria refazer o vínculo."""
    links = [LinkFalso(id=7, nome="Ibitinga", mw_plant_slug="ibitinga", mp_usina_id=2, ativo=False)]

    linha = next(l for l in conciliacao.montar(MW, MP, links) if l.plant_link_id == 7)

    assert not linha.no_app and linha.origem == "ambos"


def test_usina_apagada_no_produto_continua_legivel():
    """O vínculo aponta para uma usina que sumiu do meuWatt. A linha não pode virar um
    registro sem nome — é justamente por ela que o gestor descobre o que aconteceu."""
    links = [LinkFalso(id=9, nome="Usina Antiga", mw_plant_slug="nao-existe-mais")]

    linha = next(l for l in conciliacao.montar(MW, MP, links) if l.plant_link_id == 9)

    assert linha.nome == "Usina Antiga" and linha.mw_nome == "Usina Antiga"


def test_sugestao_so_para_quem_ainda_nao_tem_par():
    links = [LinkFalso(id=1, nome="Porto Ferreira", mw_plant_slug="porto-ferreira", mp_usina_id=1)]

    linhas = [l for l in conciliacao.montar(MW, MP, links)]
    porto = next(l for l in linhas if l.plant_link_id == 1)
    ibitinga_mw = next(l for l in linhas if l.mw_slug == "ibitinga")

    assert porto.candidatos == []  # já casada
    assert ibitinga_mw.candidatos  # ainda precisa decidir
    assert ibitinga_mw.candidatos[0].nome == "Ibitinga"


def test_o_que_esta_no_app_sobe_na_lista():
    """Ordem: no app primeiro, depois as casadas, depois por nome."""
    links = [LinkFalso(id=1, nome="Porto Ferreira", mw_plant_slug="porto-ferreira", mp_usina_id=1)]

    linhas = conciliacao.montar(MW, MP, links)

    assert linhas[0].nome == "Porto Ferreira" and linhas[0].no_app


def test_lado_vazio_nao_quebra():
    """Uma ponte fora do ar devolve lista vazia — a tela precisa abrir mostrando o outro
    lado, e não uma página de erro."""
    so_mp = conciliacao.montar([], MP, [])
    so_mw = conciliacao.montar(MW, [], [])

    assert len(so_mp) == 3 and all(l.origem == "meuplano" for l in so_mp)
    assert len(so_mw) == 2 and all(l.origem == "meuwatt" for l in so_mw)
    # Sem o outro lado não há par possível: nada de sugestão vazia enganando o gestor.
    assert all(not l.par_provavel_mw for l in so_mp)
    assert all(not l.candidatos for l in so_mw)
    assert conciliacao.montar([], [], []) == []
