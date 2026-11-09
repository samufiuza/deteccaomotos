"""Score ajustado com o gabarito dos vídeos A, B, S e L (ver config.PESOS_RISCO)."""
import pytest

import state
from config import PESOS_RISCO
from risk import calcular_score
from state import calcular_riscos

MOTO = {"track_id": 1, "vehicle_type": "motorcycle"}
INFORMATIVOS_PADRAO = ("velocidade_elevada", "mudanca_brusca")


@pytest.fixture
def padrao_producao(monkeypatch):
    """Regra padrão do sistema: velocidade e mudança brusca não geram registro de evento."""
    monkeypatch.setattr(state, "EVENTOS_INFORMATIVOS", INFORMATIVOS_PADRAO)


def test_pesos_do_gabarito():
    assert PESOS_RISCO["velocidade_elevada"] == 0
    assert PESOS_RISCO["proximidade_prevista"] > 0
    assert PESOS_RISCO["mudanca_brusca"] < PESOS_RISCO["aproximacao_rapida"] < PESOS_RISCO["proximidade_perigosa"]


def test_niveis():
    assert calcular_score(["proximidade_prevista"], PESOS_RISCO) == (30, "medio")
    assert calcular_score(["proximidade_perigosa"], PESOS_RISCO) == (40, "medio")
    assert calcular_score(["proximidade_perigosa", "aproximacao_rapida"], PESOS_RISCO)[1] == "alto"
    assert calcular_score(["velocidade_elevada"], PESOS_RISCO) == (0, "baixo")
    assert calcular_score(["mudanca_brusca"], PESOS_RISCO)[1] == "baixo"


def test_velocidade_sozinha_nao_gera_evento_nem_score(padrao_producao):
    analises, eventos = calcular_riscos([MOTO], {1: 90.0}, {1: None}, {}, {})
    assert analises[0]["risk_score"] == 0
    assert eventos == []


def test_proximidade_continua_gerando_evento_mesmo_com_velocidade_alta(padrao_producao):
    analises, eventos = calcular_riscos([MOTO], {1: 90.0}, {1: 0.8}, {}, {})
    assert {e["event_type"] for e in eventos} == {"proximidade_perigosa"}
    assert analises[0]["risk_score"] == PESOS_RISCO["proximidade_perigosa"]


def test_mudanca_brusca_soma_no_score_mas_nao_gera_evento(padrao_producao):
    analises, eventos = calcular_riscos([MOTO], {1: 30.0}, {1: None}, {}, {}, tendencias={1: {"mudanca_brusca": True}})
    assert eventos == []
    assert analises[0]["risk_score"] == PESOS_RISCO["mudanca_brusca"]


def test_informativos_vazio_volta_a_registrar(monkeypatch):
    monkeypatch.setattr(state, "EVENTOS_INFORMATIVOS", ())
    _, eventos = calcular_riscos([MOTO], {1: 90.0}, {1: None}, {}, {})
    assert {e["event_type"] for e in eventos} == {"velocidade_elevada"}
