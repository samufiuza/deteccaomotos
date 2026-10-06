import sqlite3

import pytest

import dashboard_queries as dq

SCHEMA = """
CREATE TABLE deteccoes (
    id INTEGER PRIMARY KEY,
    timestamp TEXT,
    origem_video TEXT,
    track_id INTEGER,
    vehicle_type TEXT,
    confidence REAL,
    x REAL,
    y REAL,
    speed_estimated REAL,
    nearest_distance REAL
);
CREATE TABLE eventos (
    id INTEGER PRIMARY KEY,
    track_id INTEGER,
    event_type TEXT,
    timestamp TEXT,
    severity TEXT,
    speed_estimated REAL,
    distance REAL,
    zona TEXT,
    origem_video TEXT
);
CREATE TABLE analise_risco (
    id INTEGER PRIMARY KEY,
    track_id INTEGER,
    timestamp TEXT,
    risk_score INTEGER,
    risk_level TEXT,
    origem_video TEXT
);
"""


@pytest.fixture
def conn():
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA)
    yield conn
    conn.close()


def _inserir_deteccao(conn, track_id, vehicle_type, speed=None, nearest=None, x=0, y=0, origem=None):
    conn.execute(
        "INSERT INTO deteccoes (timestamp, origem_video, track_id, vehicle_type, confidence, x, y, "
        "speed_estimated, nearest_distance) "
        "VALUES ('2026-01-01 00:00:00', ?, ?, ?, 0.9, ?, ?, ?, ?)",
        (origem, track_id, vehicle_type, x, y, speed, nearest),
    )


def test_kpis_com_banco_vazio(conn):
    kpis = dq.kpis_gerais(conn, min_frames_presenca_moto=3)
    assert kpis["total_deteccoes"] == 0
    assert kpis["total_motos_confirmadas"] == 0
    assert kpis["velocidade_media_kmh"] is None


def test_kpis_conta_deteccoes_e_veiculos(conn):
    _inserir_deteccao(conn, 1, "motorcycle")
    _inserir_deteccao(conn, 2, "car")
    conn.commit()
    kpis = dq.kpis_gerais(conn, min_frames_presenca_moto=3)
    assert kpis["total_deteccoes"] == 2
    assert kpis["total_veiculos_unicos"] == 2


def test_kpis_filtra_motos_por_presenca_minima():
    # reproduz o padrão real observado no vídeo: alguns IDs sólidos, alguns de ruído
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA)
    presencas = {17: 122, 74: 1, 140: 1, 146: 114, 196: 1}
    for tid, n in presencas.items():
        for _ in range(n):
            _inserir_deteccao(conn, tid, "motorcycle")
    conn.commit()

    kpis = dq.kpis_gerais(conn, min_frames_presenca_moto=3)
    assert kpis["total_motos_confirmadas"] == 2  # só 17 e 146 (mesmo caso já validado em state.py)
    conn.close()


def test_kpis_velocidade_media_ignora_nulos(conn):
    _inserir_deteccao(conn, 1, "motorcycle", speed=10.0)
    _inserir_deteccao(conn, 1, "motorcycle", speed=20.0)
    _inserir_deteccao(conn, 1, "motorcycle", speed=None)  # sem calibração nesse registro
    conn.commit()
    kpis = dq.kpis_gerais(conn, min_frames_presenca_moto=3)
    assert kpis["velocidade_media_kmh"] == pytest.approx(15.0)


def test_distribuicao_risco(conn):
    for nivel, n in [("baixo", 5), ("medio", 2), ("alto", 1)]:
        for _ in range(n):
            conn.execute(
                "INSERT INTO analise_risco (track_id, timestamp, risk_score, risk_level) VALUES (1, '2026-01-01', 0, ?)",
                (nivel,),
            )
    conn.commit()
    dist = {d["risk_level"]: d["total"] for d in dq.distribuicao_risco(conn)}
    assert dist == {"baixo": 5, "medio": 2, "alto": 1}


def test_eventos_por_tipo(conn):
    for tipo, n in [("proximidade_perigosa", 181), ("velocidade_elevada", 3)]:
        for _ in range(n):
            conn.execute(
                "INSERT INTO eventos (track_id, event_type, timestamp) VALUES (1, ?, '2026-01-01')",
                (tipo,),
            )
    conn.commit()
    eventos = {e["event_type"]: e["total"] for e in dq.eventos_por_tipo(conn)}
    assert eventos == {"proximidade_perigosa": 181, "velocidade_elevada": 3}


def test_deteccoes_por_tipo_veiculo(conn):
    _inserir_deteccao(conn, 1, "motorcycle")
    _inserir_deteccao(conn, 2, "motorcycle")
    _inserir_deteccao(conn, 3, "car")
    conn.commit()
    resultado = {d["vehicle_type"]: d["total"] for d in dq.deteccoes_por_tipo_veiculo(conn)}
    assert resultado == {"motorcycle": 2, "car": 1}


def test_posicoes_para_mapa_calor(conn):
    _inserir_deteccao(conn, 1, "motorcycle", x=10, y=20)
    _inserir_deteccao(conn, 2, "motorcycle", x=30, y=40)
    _inserir_deteccao(conn, 3, "car", x=99, y=99)
    conn.commit()
    posicoes = dq.posicoes_para_mapa_calor(conn, vehicle_type="motorcycle")
    assert len(posicoes) == 2
    assert {(p["x"], p["y"]) for p in posicoes} == {(10, 20), (30, 40)}


# ---- filtro por origem (vídeo) ----

def _popular_dois_videos(conn):
    for _ in range(3):
        _inserir_deteccao(conn, 1, "motorcycle", speed=10.0, origem="congestionamento.mp4")
        _inserir_deteccao(conn, 1, "motorcycle", speed=50.0, origem="avenida.mp4")  # mesmo track_id, outro vídeo
    _inserir_deteccao(conn, 2, "car", origem="avenida.mp4")
    conn.execute("INSERT INTO eventos (track_id, event_type, timestamp, origem_video) "
                 "VALUES (1, 'proximidade_perigosa', '2026-01-01', 'congestionamento.mp4')")
    conn.execute("INSERT INTO eventos (track_id, event_type, timestamp, origem_video) "
                 "VALUES (1, 'velocidade_elevada', '2026-01-01', 'avenida.mp4')")
    conn.execute("INSERT INTO analise_risco (track_id, timestamp, risk_score, risk_level, origem_video) "
                 "VALUES (1, '2026-01-01', 70, 'alto', 'avenida.mp4')")
    conn.execute("INSERT INTO analise_risco (track_id, timestamp, risk_score, risk_level, origem_video) "
                 "VALUES (1, '2026-01-01', 0, 'baixo', 'congestionamento.mp4')")
    conn.commit()


def test_listar_origens(conn):
    _popular_dois_videos(conn)
    assert dq.listar_origens(conn) == ["avenida.mp4", "congestionamento.mp4"]


def test_kpis_filtrados_por_origem(conn):
    _popular_dois_videos(conn)
    kpis = dq.kpis_gerais(conn, min_frames_presenca_moto=3, origem="congestionamento.mp4")
    assert kpis["total_deteccoes"] == 3
    assert kpis["total_motos_confirmadas"] == 1
    assert kpis["total_eventos"] == 1
    assert kpis["eventos_alto_risco"] == 0
    assert kpis["velocidade_media_kmh"] == pytest.approx(10.0)


def test_motos_confirmadas_nao_misturam_track_id_de_videos_diferentes(conn):
    _popular_dois_videos(conn)
    kpis = dq.kpis_gerais(conn, min_frames_presenca_moto=3)
    assert kpis["total_motos_confirmadas"] == 2  # moto #1 de cada vídeo


def test_graficos_filtrados_por_origem(conn):
    _popular_dois_videos(conn)
    eventos = {e["event_type"]: e["total"] for e in dq.eventos_por_tipo(conn, origem="avenida.mp4")}
    assert eventos == {"velocidade_elevada": 1}
    risco = {d["risk_level"]: d["total"] for d in dq.distribuicao_risco(conn, origem="avenida.mp4")}
    assert risco == {"alto": 1}
    veiculos = {d["vehicle_type"]: d["total"] for d in dq.deteccoes_por_tipo_veiculo(conn, origem="avenida.mp4")}
    assert veiculos == {"motorcycle": 1, "car": 1}
    posicoes = dq.posicoes_para_mapa_calor(conn, origem="congestionamento.mp4")
    assert len(posicoes) == 3
