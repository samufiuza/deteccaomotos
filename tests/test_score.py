import pytest

from risk import detectar_eventos_ativos, calcular_score

LIMIAR_VEL = 60
LIMIAR_DIST = 2.0

PESOS = {
    "velocidade_elevada": 30,
    "proximidade_perigosa": 25,
    "zona_risco": 15,
}


# ---- detectar_eventos_ativos ----

def test_nenhuma_condicao_ativa():
    eventos = detectar_eventos_ativos(velocidade=40, distancia=10, zona=None,
                                       limiar_velocidade=LIMIAR_VEL, limiar_distancia=LIMIAR_DIST)
    assert eventos == []


def test_velocidade_elevada_ativa_no_limiar_exato():
    eventos = detectar_eventos_ativos(velocidade=60, distancia=10, zona=None,
                                       limiar_velocidade=LIMIAR_VEL, limiar_distancia=LIMIAR_DIST)
    assert "velocidade_elevada" in eventos


def test_velocidade_abaixo_do_limiar_nao_ativa():
    eventos = detectar_eventos_ativos(velocidade=59.9, distancia=10, zona=None,
                                       limiar_velocidade=LIMIAR_VEL, limiar_distancia=LIMIAR_DIST)
    assert "velocidade_elevada" not in eventos


def test_proximidade_perigosa_no_limiar_exato():
    eventos = detectar_eventos_ativos(velocidade=40, distancia=2.0, zona=None,
                                       limiar_velocidade=LIMIAR_VEL, limiar_distancia=LIMIAR_DIST)
    assert "proximidade_perigosa" in eventos


def test_distancia_acima_do_limiar_nao_ativa():
    eventos = detectar_eventos_ativos(velocidade=40, distancia=2.1, zona=None,
                                       limiar_velocidade=LIMIAR_VEL, limiar_distancia=LIMIAR_DIST)
    assert "proximidade_perigosa" not in eventos


def test_zona_ativa_quando_tem_nome():
    eventos = detectar_eventos_ativos(velocidade=40, distancia=10, zona="cruzamento",
                                       limiar_velocidade=LIMIAR_VEL, limiar_distancia=LIMIAR_DIST)
    assert "zona_risco" in eventos


def test_valores_none_nao_geram_evento():
    # sem calibração: velocidade None, distância None -> não pode afirmar risco
    eventos = detectar_eventos_ativos(velocidade=None, distancia=None, zona=None,
                                       limiar_velocidade=LIMIAR_VEL, limiar_distancia=LIMIAR_DIST)
    assert eventos == []


def test_todas_condicoes_simultaneas():
    eventos = detectar_eventos_ativos(velocidade=80, distancia=1.0, zona="cruzamento",
                                       limiar_velocidade=LIMIAR_VEL, limiar_distancia=LIMIAR_DIST)
    assert set(eventos) == {"velocidade_elevada", "proximidade_perigosa", "zona_risco"}


# ---- calcular_score ----

def test_score_sem_eventos_e_zero_baixo():
    score, nivel = calcular_score([], PESOS)
    assert score == 0
    assert nivel == "baixo"


def test_score_um_evento():
    score, nivel = calcular_score(["zona_risco"], PESOS)
    assert score == 15
    assert nivel == "baixo"


def test_score_soma_eventos_distintos():
    score, nivel = calcular_score(["zona_risco", "velocidade_elevada"], PESOS)
    assert score == 45  # 15 + 30
    assert nivel == "medio"


def test_score_todos_eventos():
    score, nivel = calcular_score(["zona_risco", "velocidade_elevada", "proximidade_perigosa"], PESOS)
    assert score == 70  # 15 + 30 + 25
    assert nivel == "alto"


def test_score_nao_duplica_peso_de_evento_repetido():
    # mesmo evento listado 2x (não deveria acontecer normalmente, mas a função
    # precisa ser resiliente a isso) -> conta o peso uma única vez
    score, _ = calcular_score(["zona_risco", "zona_risco"], PESOS)
    assert score == 15


def test_score_limitado_a_100():
    pesos_exagerados = {"a": 60, "b": 60}
    score, nivel = calcular_score(["a", "b"], pesos_exagerados)
    assert score == 100
    assert nivel == "alto"


@pytest.mark.parametrize("score_bruto,nivel_esperado", [
    (0, "baixo"),
    (29, "baixo"),
    (30, "medio"),
    (59, "medio"),
    (60, "alto"),
    (100, "alto"),
])
def test_classificacao_nas_fronteiras_das_faixas(score_bruto, nivel_esperado):
    # monta um peso artificial que produz exatamente o score desejado
    pesos_artificiais = {"evento_teste": score_bruto}
    score, nivel = calcular_score(["evento_teste"], pesos_artificiais)
    assert score == score_bruto
    assert nivel == nivel_esperado
