"""
Consultas do dashboard — separadas de dashboard.py de propósito, para
poderem ser testadas sem Streamlit e sem depender de um Postgres real
rodando (testes usam sqlite como substituto nas consultas portáveis).

Todas as funções recebem uma conexão (psycopg2 ou compatível com DB-API)
e retornam list[dict], nunca objetos específicos do driver.

Filtro por vídeo: todas aceitam `origem` (valor de origem_video). None =
todos os vídeos.
"""


def _para_dicts(cursor):
    """Converte o resultado de um cursor (qualquer driver DB-API) em list[dict]."""
    colunas = [col[0] for col in cursor.description]
    return [dict(zip(colunas, linha)) for linha in cursor.fetchall()]


def _ph(conn):
    """Placeholder de parâmetro do driver: sqlite usa ?, psycopg2 usa %s."""
    return "?" if _e_sqlite(conn) else "%s"


def _filtro_origem(conn, origem, prefixo="WHERE"):
    """
    Monta o trecho SQL + parâmetros do filtro por origem_video.
    prefixo: "WHERE" quando a consulta ainda não tem WHERE, "AND" quando já tem.
    """
    if origem is None:
        return "", ()
    return f" {prefixo} origem_video = {_ph(conn)}", (origem,)


def listar_origens(conn):
    """Lista (ordenada) das origens distintas já salvas, de qualquer tabela."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT DISTINCT origem_video FROM (
            SELECT origem_video FROM deteccoes
            UNION SELECT origem_video FROM eventos
            UNION SELECT origem_video FROM analise_risco
        ) origens
        WHERE origem_video IS NOT NULL
        ORDER BY origem_video
        """
    )
    return [linha[0] for linha in cur.fetchall()]


def kpis_gerais(conn, min_frames_presenca_moto, origem=None):
    """
    Retorna um dict com os indicadores principais:
    total_deteccoes, total_veiculos_unicos, total_motos_confirmadas,
    total_eventos, eventos_alto_risco, velocidade_media_kmh.
    """
    cur = conn.cursor()
    where, params = _filtro_origem(conn, origem, "WHERE")
    e_origem, params_and = _filtro_origem(conn, origem, "AND")

    cur.execute("SELECT count(*) FROM deteccoes" + where, params)
    total_deteccoes = cur.fetchone()[0]

    cur.execute(
        "SELECT count(DISTINCT track_id) FROM deteccoes WHERE track_id IS NOT NULL" + e_origem,
        params_and,
    )
    total_veiculos_unicos = cur.fetchone()[0]

    # track_id é reiniciado a cada execução do main.py: agrupar também por
    # origem evita somar a moto #5 de um vídeo com a moto #5 de outro
    cur.execute(
        f"""
        SELECT count(*) FROM (
            SELECT origem_video, track_id
            FROM deteccoes
            WHERE vehicle_type = 'motorcycle' AND track_id IS NOT NULL{e_origem}
            GROUP BY origem_video, track_id
            HAVING count(*) >= {_ph(conn)}
        ) motos_confirmadas
        """,
        (*params_and, min_frames_presenca_moto),
    )
    total_motos_confirmadas = cur.fetchone()[0]

    cur.execute("SELECT count(*) FROM eventos" + where, params)
    total_eventos = cur.fetchone()[0]

    cur.execute("SELECT count(*) FROM analise_risco WHERE risk_level = 'alto'" + e_origem, params_and)
    eventos_alto_risco = cur.fetchone()[0]

    cur.execute(
        "SELECT avg(speed_estimated) FROM deteccoes WHERE speed_estimated IS NOT NULL" + e_origem,
        params_and,
    )
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


def distribuicao_risco(conn, origem=None):
    """Retorna list[dict] com risk_level e count, da tabela analise_risco."""
    cur = conn.cursor()
    where, params = _filtro_origem(conn, origem)
    cur.execute(
        "SELECT risk_level, count(*) as total FROM analise_risco" + where + " GROUP BY risk_level",
        params,
    )
    return _para_dicts(cur)


def eventos_por_tipo(conn, origem=None):
    """Retorna list[dict] com event_type e count, da tabela eventos."""
    cur = conn.cursor()
    where, params = _filtro_origem(conn, origem)
    cur.execute(
        "SELECT event_type, count(*) as total FROM eventos" + where + " GROUP BY event_type",
        params,
    )
    return _para_dicts(cur)


def deteccoes_por_tipo_veiculo(conn, origem=None):
    """Retorna list[dict] com vehicle_type e contagem de track_ids distintos."""
    cur = conn.cursor()
    e_origem, params = _filtro_origem(conn, origem, "AND")
    cur.execute(
        f"""
        SELECT vehicle_type, count(DISTINCT track_id) as total
        FROM deteccoes
        WHERE track_id IS NOT NULL{e_origem}
        GROUP BY vehicle_type
        ORDER BY total DESC
        """,
        params,
    )
    return _para_dicts(cur)


def posicoes_para_mapa_calor(conn, vehicle_type="motorcycle", limite=5000, origem=None):
    """
    Retorna list[dict] com x, y de detecções de um tipo de veículo — insumo
    para o mapa de calor de regiões com mais eventos/detecções.
    """
    cur = conn.cursor()
    e_origem, params = _filtro_origem(conn, origem, "AND")
    cur.execute(
        f"SELECT x, y FROM deteccoes WHERE vehicle_type = {_ph(conn)}{e_origem} LIMIT {int(limite)}",
        (vehicle_type, *params),
    )
    return _para_dicts(cur)


def serie_temporal_eventos(conn, origem=None):
    """
    Retorna list[dict] com periodo (hora) e total de eventos — para o gráfico
    de evolução ao longo do tempo. Usa date_trunc, específico do PostgreSQL
    (não portável para sqlite — só testado sintaticamente, não em unit test).
    """
    cur = conn.cursor()
    where, params = _filtro_origem(conn, origem)
    cur.execute(
        f"""
        SELECT date_trunc('hour', timestamp) as periodo, count(*) as total
        FROM eventos{where}
        GROUP BY periodo
        ORDER BY periodo
        """,
        params,
    )
    return _para_dicts(cur)
