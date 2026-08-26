from state import calcular_riscos


def test_score_e_calculado_por_track():
    objetos = [{"track_id": 1}, {"track_id": 2}]
    velocidades = {1: 80, 2: 20}  # 1 acima do limiar (60), 2 não
    distancias = {1: 10, 2: 10}
    zonas_atuais = {1: None, 2: None}
    estado = {}

    analises, _ = calcular_riscos(objetos, velocidades, distancias, zonas_atuais, estado)
    por_track = {a["track_id"]: a for a in analises}

    assert por_track[1]["risk_score"] == 30  # só velocidade_elevada
    assert por_track[1]["risk_level"] == "medio"
    assert por_track[2]["risk_score"] == 0
    assert por_track[2]["risk_level"] == "baixo"


def test_track_id_none_e_ignorado():
    objetos = [{"track_id": None}]
    analises, eventos = calcular_riscos(objetos, {None: 80}, {None: 1}, {None: None}, {})
    assert analises == []
    assert eventos == []


def test_evento_velocidade_gerado_so_na_entrada():
    objetos = [{"track_id": 1}]
    zonas_atuais = {1: None}
    estado = {}

    # frame 1: velocidade acima do limiar -> evento
    _, eventos1 = calcular_riscos(objetos, {1: 80}, {1: 10}, zonas_atuais, estado)
    assert len(eventos1) == 1
    assert eventos1[0]["event_type"] == "velocidade_elevada"

    # frame 2: continua acima do limiar -> NÃO deve duplicar
    _, eventos2 = calcular_riscos(objetos, {1: 85}, {1: 10}, zonas_atuais, estado)
    assert len(eventos2) == 0

    # frame 3: volta a ficar abaixo do limiar
    _, eventos3 = calcular_riscos(objetos, {1: 40}, {1: 10}, zonas_atuais, estado)
    assert len(eventos3) == 0

    # frame 4: sobe de novo -> nova entrada, novo evento
    _, eventos4 = calcular_riscos(objetos, {1: 90}, {1: 10}, zonas_atuais, estado)
    assert len(eventos4) == 1


def test_evento_proximidade_gerado_so_na_entrada():
    objetos = [{"track_id": 1}]
    zonas_atuais = {1: None}
    estado = {}

    _, eventos1 = calcular_riscos(objetos, {1: 30}, {1: 1.0}, zonas_atuais, estado)
    assert len(eventos1) == 1
    assert eventos1[0]["event_type"] == "proximidade_perigosa"

    _, eventos2 = calcular_riscos(objetos, {1: 30}, {1: 1.5}, zonas_atuais, estado)
    assert len(eventos2) == 0  # ainda perigoso (<=2.0), não é entrada nova


def test_score_combina_velocidade_e_proximidade():
    objetos = [{"track_id": 1}]
    analises, eventos = calcular_riscos(objetos, {1: 90}, {1: 0.5}, {1: None}, {})
    assert analises[0]["risk_score"] == 55  # 30 + 25
    assert analises[0]["risk_level"] == "medio"
    tipos = {e["event_type"] for e in eventos}
    assert tipos == {"velocidade_elevada", "proximidade_perigosa"}


def test_zona_entra_no_score_mas_nao_gera_evento_por_aqui():
    # zona é tratada por atualizar_zonas, não por calcular_riscos —
    # aqui só verificamos que ela entra na SOMA do score
    objetos = [{"track_id": 1}]
    analises, eventos = calcular_riscos(objetos, {1: 0}, {1: 100}, {1: "cruzamento"}, {})
    assert analises[0]["risk_score"] == 15
    assert eventos == []  # calcular_riscos não gera evento de zona (isso é papel de atualizar_zonas)
