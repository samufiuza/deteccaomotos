"""
Configurações centralizadas do pipeline.

Nenhuma credencial ou caminho fica hardcoded aqui: tudo vem de
variáveis de ambiente ou de argumentos de linha de comando (ver main.py).
"""

import os

# ==== BANCO DE DADOS ====
# Definir antes de rodar, por exemplo:
#   export DB_HOST=localhost
#   export DB_NAME=projeto_motos
#   export DB_USER=postgres
#   export DB_PASSWORD=sua_senha
DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "database": os.environ.get("DB_NAME", "projeto_motos"),
    "user": os.environ.get("DB_USER", "postgres"),
    "password": os.environ.get("DB_PASSWORD"),  # sem valor padrão de propósito
}

# ==== MODELO YOLO ====
# 'yolov8m.pt' -> mais preciso, mais pesado (recomendado, conforme testes do grupo)
# 'yolov8n.pt' -> mais leve, porém com mais falsos negativos em motos
MODEL_PATH = os.environ.get("YOLO_MODEL_PATH", "yolov8m.pt")

# Tracker nativo do Ultralytics (ByteTrack). Não precisamos reimplementar rastreamento.
TRACKER_CONFIG = "bytetrack.yaml"

CONF_THRESHOLD = float(os.environ.get("CONF_THRESHOLD", 0.3))

# Classes do COCO que nos interessam (índice: nome)
# 1=bicycle, 2=car, 3=motorcycle, 5=bus, 7=truck, 0=person
TARGET_CLASSES = {
    0: "pedestrian",
    1: "bicycle",
    2: "car",
    3: "motorcycle",
    5: "bus",
    7: "truck",
}

# Classe principal de estudo do TCC
PRIMARY_CLASS_ID = 3  # motorcycle

# Quantas posições recentes manter por track_id, para suavizar velocidade
# (ver risk.calcular_velocidade). Também define quanto tempo "esquecemos"
# um objeto que sumiu do vídeo (oclusão, saída de cena).
HISTORICO_MAX_POSICOES = 15

# ==== SCORE DE RISCO ====
# Limiares que definem quando uma condição é considerada de risco.
# Valores experimentais — devem ser justificados/ajustados no TCC a partir
# dos testes com vídeos reais (ver seção de avaliação experimental).
LIMIAR_VELOCIDADE_KMH = float(os.environ.get("LIMIAR_VELOCIDADE_KMH", 60))
LIMIAR_DISTANCIA_MINIMA_M = float(os.environ.get("LIMIAR_DISTANCIA_MINIMA_M", 2.0))

# Pesos por tipo de evento ativo (somados para compor o score, máx. 100).
# Espelha a tabela conceitual do prompt mestre do TCC (seção 10).
# Os cinco pesos somam exatamente 100: um veículo com todas as condições
# ativas ao mesmo tempo atinge o score máximo.
PESOS_RISCO = {
    "velocidade_elevada": 30,
    "proximidade_perigosa": 25,
    "zona_risco": 15,
    "mudanca_brusca": 15,
    "aproximacao_rapida": 15,
}

# ==== TENDÊNCIA (mudanca_brusca / aproximacao_rapida) ====
# Ambos analisam a evolução ao longo dos últimos quadros, não só o atual,
# e só são avaliados com calibração (precisam de metros, não pixels).
# Quantos pontos recentes do histórico usar na análise de tendência.
JANELA_TENDENCIA = int(os.environ.get("JANELA_TENDENCIA", 6))
# Mudança de direção (graus) entre a 1ª e a 2ª metade da janela.
LIMIAR_MUDANCA_DIRECAO_GRAUS = float(os.environ.get("LIMIAR_MUDANCA_DIRECAO_GRAUS", 45))
# Variação de velocidade (m/s²) entre as duas metades — freada/arrancada brusca.
# Frenagem forte de moto fica na faixa de 6-8 m/s².
LIMIAR_ACELERACAO_M_S2 = float(os.environ.get("LIMIAR_ACELERACAO_M_S2", 6.0))
# Deslocamento mínimo (m) em cada metade da janela para avaliar direção —
# evita que o "tremor" da bounding box de um veículo quase parado vire curva.
MIN_DESLOCAMENTO_DIRECAO_M = float(os.environ.get("MIN_DESLOCAMENTO_DIRECAO_M", 0.5))
# Velocidade com que a distância ao vizinho mais próximo diminui (m/s).
LIMIAR_APROXIMACAO_M_S = float(os.environ.get("LIMIAR_APROXIMACAO_M_S", 3.0))

# ==== FILTRO DO CÁLCULO DE DISTÂNCIA ====
# Classes que NÃO entram no cálculo de distância/proximidade: pedestres
# (inclui manequins detectados como pessoa) e bicicletas (ex.: estacionadas).
CLASSES_IGNORADAS_DISTANCIA = {"pedestrian", "bicycle"}
# Objetos parados também são ignorados (carro estacionado, veículos travados
# no congestionamento). "Parado" = velocidade abaixo do limiar abaixo.
LIMIAR_PARADO_KMH = float(os.environ.get("LIMIAR_PARADO_KMH", 3.0))
# Sem calibração não há km/h: usa deslocamento em pixels por segundo.
LIMIAR_PARADO_PX_S = float(os.environ.get("LIMIAR_PARADO_PX_S", 20.0))
# Mínimo de pontos no histórico para afirmar que um objeto está parado
# (antes disso ele é tratado como em movimento — não há como saber).
MIN_PONTOS_PARADO = int(os.environ.get("MIN_PONTOS_PARADO", 5))

# ==== TEMPO DO QUADRO ====
# Em arquivos de vídeo o tempo de cada quadro é quadro ÷ fps (tempo do vídeo),
# independente da velocidade de processamento. Se o arquivo não informar o
# fps, usa este valor padrão.
FPS_PADRAO = float(os.environ.get("FPS_PADRAO", 30))

# Faixas de classificação do score (0-100)
NIVEIS_RISCO = [
    (0, 29, "baixo"),
    (30, 59, "medio"),
    (60, 100, "alto"),
]

# Quantos frames um track_id de moto precisa aparecer para ser contado como
# "moto confirmada" (não só uma detecção isolada/ruído). Descoberto empiricamente
# ao rodar com vídeo real: sem esse filtro, IDs que aparecem em 1 frame só
# (falso positivo pontual ou troca de ID) inflam a contagem total de motos.
MIN_FRAMES_PRESENCA_MOTO = int(os.environ.get("MIN_FRAMES_PRESENCA_MOTO", 3))