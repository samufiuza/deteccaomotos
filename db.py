"""
Acesso ao PostgreSQL.

Schema desta etapa (detecção + tracking). As tabelas de eventos e
análise de risco serão adicionadas quando essas etapas forem implementadas.
"""

import psycopg2
from config import DB_CONFIG

CREATE_DETECCOES_SQL = """
CREATE TABLE IF NOT EXISTS deteccoes (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP NOT NULL,
    origem_video VARCHAR(255),
    track_id INTEGER,
    vehicle_type VARCHAR(20),
    confidence FLOAT,
    x FLOAT,
    y FLOAT,
    speed_estimated FLOAT,
    nearest_distance FLOAT
);
"""

# ADD COLUMN IF NOT EXISTS é suportado pelo PostgreSQL (9.6+), então quem já
# tinha a tabela da etapa anterior (sem essas colunas) é atualizado automaticamente.
ALTER_DETECCOES_SQL = """
ALTER TABLE deteccoes ADD COLUMN IF NOT EXISTS speed_estimated FLOAT;
ALTER TABLE deteccoes ADD COLUMN IF NOT EXISTS nearest_distance FLOAT;
"""


CREATE_EVENTOS_SQL = """
CREATE TABLE IF NOT EXISTS eventos (
    id SERIAL PRIMARY KEY,
    track_id INTEGER,
    event_type VARCHAR(50) NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    severity VARCHAR(10),
    speed_estimated FLOAT,
    distance FLOAT,
    zona VARCHAR(50)
);
"""


def conectar():
    """Abre e retorna uma conexão com o banco. Lança exceção se falhar."""
    if not DB_CONFIG["password"]:
        raise RuntimeError(
            "DB_PASSWORD não definido. Configure a variável de ambiente antes de rodar."
        )
    conn = psycopg2.connect(**DB_CONFIG)
    return conn


def garantir_schema(conn):
    """Cria as tabelas caso não existam, e adiciona colunas novas se faltarem."""
    with conn.cursor() as cur:
        cur.execute(CREATE_DETECCOES_SQL)
        cur.execute(ALTER_DETECCOES_SQL)
        cur.execute(CREATE_EVENTOS_SQL)
    conn.commit()


def salvar_eventos(conn, eventos):
    """
    Insere um lote de eventos de risco.

    `eventos` é uma lista de dicts:
    {"track_id": int, "event_type": str, "timestamp": datetime,
     "severity": str|None, "speed_estimated": float|None,
     "distance": float|None, "zona": str|None}
    """
    if not eventos:
        return
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO eventos
                (track_id, event_type, timestamp, severity, speed_estimated, distance, zona)
            VALUES (%(track_id)s, %(event_type)s, %(timestamp)s, %(severity)s,
                    %(speed_estimated)s, %(distance)s, %(zona)s)
            """,
            eventos,
        )
    conn.commit()


def salvar_deteccoes(conn, origem, deteccoes):
    """
    Insere um lote de detecções.

    `deteccoes` é uma lista de dicts:
    {"timestamp": datetime, "track_id": int|None, "vehicle_type": str,
     "confidence": float, "x": float, "y": float,
     "speed_estimated": float|None, "nearest_distance": float|None}
    """
    if not deteccoes:
        return
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO deteccoes
                (timestamp, origem_video, track_id, vehicle_type, confidence, x, y,
                 speed_estimated, nearest_distance)
            VALUES (%(timestamp)s, %(origem)s, %(track_id)s, %(vehicle_type)s,
                    %(confidence)s, %(x)s, %(y)s, %(speed_estimated)s, %(nearest_distance)s)
            """,
            [{**d, "origem": origem} for d in deteccoes],
        )
    conn.commit()
