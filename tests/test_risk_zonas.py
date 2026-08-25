from risk import checar_zona, _ponto_dentro_poligono

QUADRADO = [(0, 0), (10, 0), (10, 10), (0, 10)]

# "L" côncavo: um quadrado 10x10 com um pedaço 5x5 cortado no canto superior direito
L_CONCAVO = [(0, 0), (10, 0), (10, 5), (5, 5), (5, 10), (0, 10)]


# ---- _ponto_dentro_poligono (forma pura) ----

def test_ponto_claramente_dentro():
    assert _ponto_dentro_poligono(5, 5, QUADRADO) is True


def test_ponto_claramente_fora():
    assert _ponto_dentro_poligono(20, 20, QUADRADO) is False


def test_ponto_fora_mas_proximo():
    assert _ponto_dentro_poligono(-1, 5, QUADRADO) is False


def test_poligono_concavo_ponto_na_reentrancia_fica_fora():
    # (7, 7) está na área "cortada" do L -> fora do polígono, mesmo estando
    # dentro do quadrado 10x10 que o contém
    assert _ponto_dentro_poligono(7, 7, L_CONCAVO) is False


def test_poligono_concavo_ponto_na_parte_cheia_fica_dentro():
    assert _ponto_dentro_poligono(2, 2, L_CONCAVO) is True


# ---- checar_zona (usa nomes, várias zonas) ----

def test_checar_zona_sem_zonas_retorna_none():
    assert checar_zona(5, 5, []) is None


def test_checar_zona_identifica_zona_correta():
    zonas = [
        {"nome": "faixa_pedestre", "poligono": QUADRADO},
    ]
    assert checar_zona(5, 5, zonas) == "faixa_pedestre"


def test_checar_zona_fora_de_todas_retorna_none():
    zonas = [
        {"nome": "faixa_pedestre", "poligono": QUADRADO},
    ]
    assert checar_zona(100, 100, zonas) is None


def test_checar_zona_prioriza_primeira_em_sobreposicao():
    # duas zonas sobrepostas no mesmo ponto: a ordem da lista decide
    zonas = [
        {"nome": "zona_a", "poligono": QUADRADO},
        {"nome": "zona_b", "poligono": [(0, 0), (20, 0), (20, 20), (0, 20)]},
    ]
    assert checar_zona(5, 5, zonas) == "zona_a"


def test_checar_zona_multiplas_zonas_nao_sobrepostas():
    zonas = [
        {"nome": "zona_a", "poligono": QUADRADO},
        {"nome": "zona_b", "poligono": [(100, 100), (110, 100), (110, 110), (100, 110)]},
    ]
    assert checar_zona(105, 105, zonas) == "zona_b"
    assert checar_zona(5, 5, zonas) == "zona_a"
