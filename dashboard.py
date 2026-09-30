"""
Dashboard do projeto — visualiza os dados já salvos pelo main.py no PostgreSQL.

Uso:
    streamlit run dashboard.py

Não roda a detecção nem o tracking — só lê o que já está no banco. Rode o
main.py primeiro (ver README.md) para ter dados para visualizar.
"""

import numpy as np
import pandas as pd
import streamlit as st

import db
import dashboard_queries as dq
from config import MIN_FRAMES_PRESENCA_MOTO

st.set_page_config(page_title="Dashboard — Detecção de Motos", layout="wide")
st.title("🏍️ Dashboard — Detecção e Análise de Risco de Motocicletas")


@st.cache_resource
def get_conn():
    return db.conectar()


try:
    conn = get_conn()
except RuntimeError as e:
    st.error(f"Erro ao conectar no banco: {e}")
    st.info("Configure DB_HOST, DB_NAME, DB_USER, DB_PASSWORD antes de rodar o dashboard.")
    st.stop()

kpis = dq.kpis_gerais(conn, MIN_FRAMES_PRESENCA_MOTO)

if kpis["total_deteccoes"] == 0:
    st.warning(
        "Nenhum dado encontrado no banco ainda. Rode o main.py em algum vídeo "
        "primeiro (ver README.md) para popular as tabelas."
    )
    st.stop()

# ==== KPIs principais ====
col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Total de detecções", f"{kpis['total_deteccoes']:,}".replace(",", "."))
col2.metric("Veículos únicos rastreados", kpis["total_veiculos_unicos"])
col3.metric(f"Motos confirmadas (≥{MIN_FRAMES_PRESENCA_MOTO} frames)", kpis["total_motos_confirmadas"])
col4.metric("Eventos de risco", kpis["total_eventos"])
col5.metric("Eventos de risco ALTO", kpis["eventos_alto_risco"])

if kpis["velocidade_media_kmh"] is not None:
    st.metric("Velocidade média estimada", f"{kpis['velocidade_media_kmh']:.1f} km/h")
else:
    st.info("Sem velocidade estimada — rode com --calib-p1/--calib-p2/--calib-dist para calcular.")

st.divider()

# ==== Gráficos ====
col_a, col_b = st.columns(2)

with col_a:
    st.subheader("Distribuição de nível de risco")
    dados_risco = dq.distribuicao_risco(conn)
    if dados_risco:
        df_risco = pd.DataFrame(dados_risco).set_index("risk_level")
        # ordena baixo/medio/alto, não alfabético
        ordem = [n for n in ["baixo", "medio", "alto"] if n in df_risco.index]
        st.bar_chart(df_risco.loc[ordem])
    else:
        st.caption("Sem dados de análise de risco ainda.")

with col_b:
    st.subheader("Eventos por tipo")
    dados_eventos = dq.eventos_por_tipo(conn)
    if dados_eventos:
        df_eventos = pd.DataFrame(dados_eventos).set_index("event_type")
        st.bar_chart(df_eventos)
    else:
        st.caption("Nenhum evento de risco registrado ainda.")

st.subheader("Detecções por tipo de veículo")
dados_veiculos = dq.deteccoes_por_tipo_veiculo(conn)
if dados_veiculos:
    df_veiculos = pd.DataFrame(dados_veiculos).set_index("vehicle_type")
    st.bar_chart(df_veiculos)

st.subheader("Evolução dos eventos de risco ao longo do tempo")
try:
    dados_serie = dq.serie_temporal_eventos(conn)
    if dados_serie:
        df_serie = pd.DataFrame(dados_serie).set_index("periodo")
        st.line_chart(df_serie)
    else:
        st.caption("Sem eventos suficientes ainda para mostrar evolução no tempo.")
except Exception as e:
    st.caption(f"Não foi possível montar a série temporal: {e}")

st.subheader("Mapa de calor — onde as motos mais aparecem no quadro")
posicoes = dq.posicoes_para_mapa_calor(conn, vehicle_type="motorcycle")
if posicoes:
    df_pos = pd.DataFrame(posicoes)
    # histograma 2D simples: mais denso = mais detecções naquela região da imagem
    heatmap, xedges, yedges = np.histogram2d(df_pos["x"], df_pos["y"], bins=30)
    st.caption(
        "Cada célula representa uma região da imagem; quanto mais forte, mais "
        "detecções de moto passaram por ali. Eixo Y invertido (0 = topo da imagem)."
    )
    st.bar_chart(pd.DataFrame(heatmap))
else:
    st.caption("Sem posições de moto registradas ainda.")

st.divider()
st.caption(
    "Este dashboard só lê dados já processados — para gerar novos dados, rode "
    "`python main.py --source ...` (ver README.md) e recarregue esta página."
)
