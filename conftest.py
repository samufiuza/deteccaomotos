"""Configuração do pytest (raiz do projeto).

Por padrão o sistema NÃO registra eventos de velocidade_elevada e mudanca_brusca
(ver config.EVENTOS_INFORMATIVOS). Os testes de mecânica de eventos (transição,
cooldown, faixa, etc.) usam esses dois tipos como gatilho, então rodam com o
registro ligado. A regra padrão é testada em tests/test_score_gabarito.py.
"""
import os

os.environ.setdefault("EVENTOS_INFORMATIVOS", "")
