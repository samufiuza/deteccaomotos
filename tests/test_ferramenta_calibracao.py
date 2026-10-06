import json
import math

import cv2
import numpy as np
import pytest

import ferramenta_calibracao as ft
from calibration import salvar_calibracao, carregar_calibracao


def _camera(h=8.0, theta_deg=35.0, f=1000.0, cx=640.0, cy=360.0):
    t = math.radians(theta_deg)
    c, s = math.cos(t), math.sin(t)
    return np.array([
        [f, cx * c, cx * h * s],
        [0, cy * c - f * s, cy * h * s + f * h * c],
        [0, c, h * s],
    ])


H_MI = _camera()


def m2i(X, Y):
    v = H_MI @ np.array([X, Y, 1.0])
    return int(round(v[0] / v[2])), int(round(v[1] / v[2]))


# P1 perto-esq, P2 perto-dir, P3 longe-dir, P4 longe-esq (pista de 3,5 m x 20 m)
PONTOS_IMG = [m2i(-1.75, 8), m2i(1.75, 8), m2i(1.75, 28), m2i(-1.75, 28)]


@pytest.fixture(autouse=True)
def estado_limpo():
    """Zera o estado global do módulo antes e depois de cada teste."""
    def zerar():
        ft.pontos_calibracao.clear()
        ft.zonas.clear()
        ft.poligono_atual.clear()
        ft.pontos_chao.clear()
        ft.medidas.clear()
        ft.ponto_medida.clear()
        ft.homografia = None
        ft.mostrar_grade = False
        ft.modo = None
    zerar()
    yield
    zerar()


# ---- quadrilatero_valido ----

def test_quadrilatero_na_ordem_certa_e_valido():
    assert ft.quadrilatero_valido(PONTOS_IMG) is True


def test_quadrilatero_com_lados_cruzados_e_invalido():
    p = PONTOS_IMG
    cruzado = [p[0], p[2], p[1], p[3]]  # ordem embaralhada -> lados se cruzam
    assert ft.quadrilatero_valido(cruzado) is False


def test_pontos_colineares_sao_invalidos():
    assert ft.quadrilatero_valido([(0, 0), (10, 0), (20, 0), (30, 0)]) is False


def test_numero_errado_de_pontos_e_invalido():
    assert ft.quadrilatero_valido(PONTOS_IMG[:3]) is False


# ---- finalizar_homografia / medir_no_chao ----

def test_homografia_recupera_dimensoes_do_retangulo():
    H, mundo = ft.finalizar_homografia(PONTOS_IMG, 3.5, 20.0)
    assert mundo == [(0.0, 0.0), (3.5, 0.0), (3.5, 20.0), (0.0, 20.0)]
    assert ft.medir_no_chao(H, PONTOS_IMG[0], PONTOS_IMG[1]) == pytest.approx(3.5, abs=0.02)
    assert ft.medir_no_chao(H, PONTOS_IMG[1], PONTOS_IMG[2]) == pytest.approx(20.0, abs=0.05)


def test_validacao_com_outra_distancia_conhecida():
    # distância que NÃO foi usada na calibração: 2 m, lado a lado, no meio do trecho
    H, _ = ft.finalizar_homografia(PONTOS_IMG, 3.5, 20.0)
    a, b = m2i(-1.0, 18), m2i(1.0, 18)
    assert ft.medir_no_chao(H, a, b) == pytest.approx(2.0, abs=0.05)


def test_finalizar_ordem_errada_levanta_erro():
    p = PONTOS_IMG
    with pytest.raises(ValueError):
        ft.finalizar_homografia([p[0], p[2], p[1], p[3]], 3.5, 20.0)


@pytest.mark.parametrize("largura,comprimento", [(0, 20), (3.5, 0), (-1, 5)])
def test_finalizar_medidas_invalidas_levanta_erro(largura, comprimento):
    with pytest.raises(ValueError):
        ft.finalizar_homografia(PONTOS_IMG, largura, comprimento)


# ---- desenhar_grade ----

def test_desenhar_grade_desenha_linhas():
    H, mundo = ft.finalizar_homografia(PONTOS_IMG, 3.5, 20.0)
    frame = np.zeros((720, 1280, 3), dtype="uint8")
    ft.desenhar_grade(frame, H, mundo)
    assert frame.sum() > 0


# ---- salvar_zonas ----

def test_salvar_zonas_preserva_homografia(tmp_path):
    H, mundo = ft.finalizar_homografia(PONTOS_IMG, 3.5, 20.0)
    arq = str(tmp_path / "cal.json")
    salvar_calibracao(arq, H, PONTOS_IMG, mundo, (1280, 720))
    ft.salvar_zonas(arq, [{"nome": "cruzamento", "poligono": [(1, 2), (3, 4), (5, 6)]}])
    dados = json.loads(open(arq, encoding="utf-8").read())
    assert "homografia" in dados
    assert dados["zonas"][0]["nome"] == "cruzamento"
    H2, res = carregar_calibracao(arq)  # continua carregável
    assert res == (1280, 720)


def test_salvar_zonas_em_arquivo_novo(tmp_path):
    arq = str(tmp_path / "z.json")
    ft.salvar_zonas(arq, [{"nome": "a", "poligono": [(0, 0), (1, 0), (1, 1)]}])
    assert json.loads(open(arq, encoding="utf-8").read())["zonas"][0]["nome"] == "a"


# ---- fluxo de cliques (simulado, sem janela) ----

def _clicar(x, y):
    ft.clique(cv2.EVENT_LBUTTONDOWN, x, y, 0, None)


def test_fluxo_completo_homografia_e_validacao(monkeypatch):
    ft.modo = "homografia"
    for (x, y) in PONTOS_IMG:
        _clicar(x, y)
    assert ft.pontos_chao == PONTOS_IMG

    respostas = iter(["3,5", "20"])  # vírgula decimal, como se digita no Brasil
    monkeypatch.setattr("builtins.input", lambda _msg="": next(respostas))
    assert ft.confirmar_homografia() is True
    assert ft.homografia is not None and ft.mostrar_grade is True

    ft.modo = "validar"
    a, b = m2i(-1.0, 18), m2i(1.0, 18)
    _clicar(*a)
    _clicar(*b)
    assert len(ft.medidas) == 1
    assert ft.medidas[0][2] == pytest.approx(2.0, abs=0.05)
    assert ft.ponto_medida == []  # pronto para a próxima medida


def test_validar_sem_homografia_nao_quebra(capsys):
    ft.modo = "validar"
    _clicar(10, 10)
    assert ft.medidas == []
    assert "Confirme a homografia" in capsys.readouterr().out


def test_confirmar_com_pontos_na_ordem_errada_nao_define_homografia(monkeypatch):
    p = PONTOS_IMG
    ft.modo = "homografia"
    for (x, y) in [p[0], p[2], p[1], p[3]]:
        _clicar(x, y)
    respostas = iter(["3.5", "20"])
    monkeypatch.setattr("builtins.input", lambda _msg="": next(respostas))
    assert ft.confirmar_homografia() is False
    assert ft.homografia is None


def test_confirmar_com_texto_nao_numerico_nao_quebra(monkeypatch):
    ft.modo = "homografia"
    for (x, y) in PONTOS_IMG:
        _clicar(x, y)
    respostas = iter(["abc", "20"])
    monkeypatch.setattr("builtins.input", lambda _msg="": next(respostas))
    assert ft.confirmar_homografia() is False


def test_mais_de_quatro_cliques_sao_ignorados():
    ft.modo = "homografia"
    for (x, y) in PONTOS_IMG + [(5, 5)]:
        _clicar(x, y)
    assert len(ft.pontos_chao) == 4


def test_redesenhar_com_tudo_ligado_nao_quebra(monkeypatch):
    ft.modo = "homografia"
    for (x, y) in PONTOS_IMG:
        _clicar(x, y)
    respostas = iter(["3.5", "20"])
    monkeypatch.setattr("builtins.input", lambda _msg="": next(respostas))
    ft.confirmar_homografia()
    ft.medidas.append((PONTOS_IMG[0], PONTOS_IMG[1], 3.5))
    ft.zonas.append({"nome": "z", "poligono": [(1, 1), (50, 1), (50, 50)]})
    quadro = ft.redesenhar(np.zeros((720, 1280, 3), dtype="uint8"))
    assert quadro.shape == (720, 1280, 3) and quadro.sum() > 0
