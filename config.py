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
# "mudanca_brusca" e "aproximacao_rapida" ainda não são detectados nesta
# etapa — exigem análise de tendência ao longo do tempo, não só do frame
# atual — ficam para uma próxima iteração.
PESOS_RISCO = {
    "velocidade_elevada": 30,
    "proximidade_perigosa": 25,
    "zona_risco": 15,
}

# Faixas de classificação do score (0-100)
NIVEIS_RISCO = [
    (0, 29, "baixo"),
    (30, 59, "medio"),
    (60, 100, "alto"),
]
