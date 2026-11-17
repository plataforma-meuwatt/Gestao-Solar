"""O bot explica de onde veio a perda de cada inversor (o dono, 17/11/2026, sobre o Skid 2 de Porto Ferreira: "De onde
veio esse número" — "preciso de memória para cada cálculo"): a conta de cada dia vem pronta do meuWatt."""

from app.services.assistente_geracao import _conta_da_perda


def test_a_conta_de_cada_dia_vai_ao_bot_e_a_lista_longa_e_cortada():
    texto = ("17/11: 16 pares saudáveis; média da metade de cima (8) 5,2844 kWh/kWp (pares de 5,1075 a 5,3714) × "
             "375,06 kWp = 1.981,97 kWh esperados − 0,00 produzidos = 1.981,97 kWh")
    assert _conta_da_perda([{"dia": "2026-11-17", "kwh": 1981.97, "texto": texto}]) == {
        "como_a_perda_foi_calculada": [texto]}
    longa = [{"texto": f"dia {k}"} for k in range(9)]
    assert _conta_da_perda(longa)["como_a_perda_foi_calculada"][-1] == "… e mais 3 dia(s)"
    assert _conta_da_perda(None) == {} and _conta_da_perda([{"kwh": 1}]) == {}   # meuWatt antigo: nada muda
