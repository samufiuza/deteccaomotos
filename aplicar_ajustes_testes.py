"""Ajusta 4 asserts de testes antigos aos novos pesos do score. Rode na raiz do projeto:
    python aplicar_ajustes_testes.py
Cada troca é exata; se alguma não for encontrada, o script avisa e não altera aquele arquivo."""
import pathlib

AJUSTES = [
    ("tests/test_distancia_pixels.py",
     'assert analises[0]["risk_score"] == 25',
     'assert analises[0]["risk_score"] == 40  # peso de proximidade_perigosa (ajuste do gabarito)'),
    ("tests/test_state_riscos.py",
     'assert por_track[1]["risk_score"] == 30  # só velocidade_elevada',
     'assert por_track[1]["risk_score"] == 0  # velocidade_elevada tem peso 0 (ajuste do gabarito)'),
    ("tests/test_state_riscos.py",
     'assert analises[0]["risk_score"] == 55  # 30 + 25',
     'assert analises[0]["risk_score"] == 40  # só proximidade_perigosa; velocidade tem peso 0'),
    ("tests/test_tendencia.py",
     'todos = ["velocidade_elevada", "proximidade_perigosa", "zona_risco", "mudanca_brusca", "aproximacao_rapida"]',
     'todos = ["velocidade_elevada", "proximidade_perigosa", "proximidade_prevista", "zona_risco", "mudanca_brusca", "aproximacao_rapida"]'),
]
for arq, antigo, novo in AJUSTES:
    p = pathlib.Path(arq)
    if not p.exists():
        print(f"NÃO ENCONTRADO (arquivo): {arq}"); continue
    t = p.read_text(encoding="utf-8")
    if antigo not in t:
        print(f"NÃO ENCONTRADO (trecho) em {arq}: {antigo[:60]}..."); continue
    p.write_text(t.replace(antigo, novo, 1), encoding="utf-8")
    print(f"ok  {arq}")
