"""
Consultas do dashboard — separadas de dashboard.py de propósito, para
poderem ser testadas sem Streamlit e sem depender de um Postgres real
rodando (testes usam sqlite como substituto nas consultas portáveis).

Todas as funções recebem uma conexão (psycopg2 ou compatível com DB-API)
e retornam list[dict], nunca objetos específicos do driver.
"""


def _para_dicts(cursor):
    """Converte o resultado de um cursor (qualquer driver DB-API) em list[dict]."""
    colunas = [col[0] for col in cursor.description]
    return [dict(zip(colunas, linha)) for linha in cursor.fetchall()]


def kpis_gerais(conn, min_frames_presenca_moto):
    """
    Retorna um dict com os indicadores principais:
    total_deteccoes, total_veiculos_unicos, total_motos_confirmadas,
    total_eventos, eventos_alto_risco, velocidade_media_kmh.
    """
    cur = conn.cursor()

    cur.execute("SELECT count(*) FROM deteccoes")
    total_deteccoes = cur.fetchone()[0]

    cur.execute("SELECT count(DISTINCT track_id) FROM deteccoes WHERE track_id IS NOT NULL")
    total_veiculos_unicos = cur.fetchone()[0]

    placeholder = "?" if _e_sqlite(conn) else "%s"
    cur.execute(
        f"""
        SELECT count(*) FROM (
            SELECT track_id
            FROM deteccoes
            WHERE vehicle_type = 'motorcycle' AND track_id IS NOT NULL
            GROUP BY track_id
            HAVING count(*) >= {placeholder}
        ) motos_confirmadas
        """,
        (min_frames_presenca_moto,),
    )
    total_motos_confirmadas = cur.fetchone()[0]

    cur.execute("SELECT count(*) FROM eventos")
    total_eventos = cur.fetchone()[0]

    cur.execute("SELECT count(*) FROM analise_risco WHERE risk_level = 'alto'")
    eventos_alto_risco = cur.fetchone()[0]

    cur.execute("SELECT avg(speed_estimated) FROM deteccoes WHERE speed_estimated IS NOT NULL")
    resultado = cur.fetchone()[0]
    velocidade_media_kmh = float(resultado) if resultado is not None else None

    return {
        "total_deteccoes": total_deteccoes,
        "total_veiculos_unicos": total_veiculos_unicos,
        "total_motos_confirmadas": total_motos_confirmadas,
        "total_eventos": total_eventos,
        "eventos_alto_risco": eventos_alto_risco,
        "velocidade_media_kmh": velocidade_media_kmh,
    }


def _e_sqlite(conn):
    return type(conn).__module__.startswith("sqlite3")


def distribuicao_risco(conn):
    """Retorna list[dict] com risk_level e count, da tabela analise_risco."""
    cur = conn.cursor()
    cur.execute("SELECT risk_level, count(*) as total FROM analise_risco GROUP BY risk_level")
    return _para_dicts(cur)


def eventos_por_tipo(conn):
    """Retorna list[dict] com event_type e count, da tabela eventos."""
    cur = conn.cursor()
    cur.execute("SELECT event_type, count(*) as total FROM eventos GROUP BY event_type")
    return _para_dicts(cur)


def deteccoes_por_tipo_veiculo(conn):
    """Retorna list[dict] com vehicle_type e contagem de track_ids distintos."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT vehicle_type, count(DISTINCT track_id) as total
        FROM deteccoes
        WHERE track_id IS NOT NULL
        GROUP BY vehicle_type
        ORDER BY total DESC
        """
    )
    return _para_dicts(cur)


def posicoes_para_mapa_calor(conn, vehicle_type="motorcycle", limite=5000):
    """
    Retorna list[dict] com x, y de detecções de um tipo de veículo — insumo
    para o mapa de calor de regiões com mais eventos/detecções.
    """
    cur = conn.cursor()
    placeholder = "?" if _e_sqlite(conn) else "%s"
    cur.execute(
        f"SELECT x, y FROM deteccoes WHERE vehicle_type = {placeholder} LIMIT {int(limite)}",
        (vehicle_type,),
    )
    return _para_dicts(cur)


def serie_temporal_eventos(conn):
    """
    Retorna list[dict] com periodo (hora) e total de eventos — para o gráfico
    de evolução ao longo do tempo. Usa date_trunc, específico do PostgreSQL
    (não portável para sqlite — só testado sintaticamente, não em unit test).
    """
    cur = conn.cursor()
    cur.execute(
        """
        SELECT date_trunc('hour', timestamp) as periodo, count(*) as total
        FROM eventos
        GROUP BY periodo
        ORDER BY periodo
        """
    )
    return _para_dicts(cur)
