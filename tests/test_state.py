from state import atualizar_zonas

ZONA_CRUZAMENTO = [{"nome": "cruzamento", "poligono": [(0, 0), (10, 0), (10, 10), (0, 10)]}]


def test_entrada_gera_evento():
    zona_por_track = {}
    atuais, entradas = atualizar_zonas([{"track_id": 1, "x": 5, "y": 5}], ZONA_CRUZAMENTO, zona_por_track)
    assert atuais[1] == "cruzamento"
    assert len(entradas) == 1
    assert entradas[0]["track_id"] == 1
    assert entradas[0]["zona"] == "cruzamento"
    assert entradas[0]["event_type"] == "entrada_zona_risco"


def test_permanencia_nao_duplica_evento():
    zona_por_track = {}
    atualizar_zonas([{"track_id": 1, "x": 5, "y": 5}], ZONA_CRUZAMENTO, zona_por_track)  # entra
    _, entradas = atualizar_zonas([{"track_id": 1, "x": 6, "y": 6}], ZONA_CRUZAMENTO, zona_por_track)  # continua dentro
    assert len(entradas) == 0


def test_saida_nao_gera_evento_de_saida():
    zona_por_track = {}
    atualizar_zonas([{"track_id": 1, "x": 5, "y": 5}], ZONA_CRUZAMENTO, zona_por_track)  # entra
    atuais, entradas = atualizar_zonas([{"track_id": 1, "x": 50, "y": 50}], ZONA_CRUZAMENTO, zona_por_track)  # sai
    assert atuais[1] is None
    assert len(entradas) == 0


def test_reentrada_gera_novo_evento():
    zona_por_track = {}
    atualizar_zonas([{"track_id": 1, "x": 5, "y": 5}], ZONA_CRUZAMENTO, zona_por_track)   # entra
    atualizar_zonas([{"track_id": 1, "x": 50, "y": 50}], ZONA_CRUZAMENTO, zona_por_track)  # sai
    _, entradas = atualizar_zonas([{"track_id": 1, "x": 5, "y": 5}], ZONA_CRUZAMENTO, zona_por_track)  # entra de novo
    assert len(entradas) == 1


def test_multiplos_tracks_simultaneos():
    zona_por_track = {}
    objetos = [{"track_id": 1, "x": 5, "y": 5}, {"track_id": 2, "x": 50, "y": 50}]
    atuais, entradas = atualizar_zonas(objetos, ZONA_CRUZAMENTO, zona_por_track)
    assert atuais == {1: "cruzamento", 2: None}
    assert len(entradas) == 1
    assert entradas[0]["track_id"] == 1


def test_track_id_none_e_ignorado():
    zona_por_track = {}
    atuais, entradas = atualizar_zonas([{"track_id": None, "x": 5, "y": 5}], ZONA_CRUZAMENTO, zona_por_track)
    assert atuais == {}
    assert entradas == []
