# Guia de testes — pipeline de detecção/rastreamento de motos

Os testes se dividem em três categorias, porque exigem coisas diferentes:

| Tipo | O que valida | Precisa de | Roda onde |
|---|---|---|---|
| **Unitário (automatizado)** | Lógica matemática pura (calibração, velocidade, distância) | Nada além do Python | Aqui mesmo, em segundos, com `pytest` |
| **Funcional/visual (manual)** | Detecção e tracking em vídeo/imagem reais | YOLO instalado + `moto_teste.jpg` / `vídeo_moto.mp4` | No ambiente de vocês (local, com GPU se tiver) |
| **Integração** | Pipeline ponta a ponta + persistência no banco | Tudo acima + PostgreSQL rodando | No ambiente de vocês |

A pasta `tests/` já traz os testes unitários prontos e passando (15/15). Os demais são passo a passo manual, porque não têm uma "resposta certa" objetiva — dependem de comparação com a realidade do vídeo.

---

## 1. `calibration.py` e `risk.py` (velocidade/distância) — automatizado

```bash
pip install pytest
cd deteccao_motos
python -m pytest tests/ -v
```

**O que os testes cobrem:**
- Caso conhecido: 100px em 1s com escala 0.1 m/px deve dar exatamente 36 km/h.
- Casos de borda: histórico com 1 ponto só, dois timestamps iguais (câmera travando/duplicando frame), veículo parado (velocidade deve ser 0, não erro).
- Sem calibração: velocidade deve retornar `None` (não deve inventar um número), distância deve cair para pixels.
- Propriedades matemáticas: distância(A, B) == distância(B, A); distância de um ponto a ele mesmo é 0.

**Critério de sucesso:** os 15 testes passam. Se vocês alterarem a fórmula de `calcular_velocidade` ou `calcular_distancia` no futuro, rodem de novo — é o que evita que uma mudança quebre algo que já funcionava (regressão).

**Quando rodar:** toda vez que mexer em `calibration.py` ou `risk.py`, antes de testar com vídeo real. Se um teste quebrar aqui, o problema é matemático — não adianta ir direto pro vídeo tentar descobrir o que está errado.

---

## 2. `detector.py` (YOLO + tracking) — teste visual com imagem

Isso precisa do ambiente de vocês (`pip install ultralytics`) e do arquivo `moto_teste.jpg`.

**Passo a passo:**
1. Rode `python main.py --source moto_teste.jpg`.
2. Compare visualmente: quantas motos o sistema contou vs. quantas você conta olhando a imagem.
3. Anote, para essa imagem específica: verdadeiros positivos (motos corretamente detectadas), falsos positivos (algo marcado como moto que não é), falsos negativos (moto que passou batido).

**Critério de sucesso:** para uma imagem com boa iluminação e motos não muito pequenas/distantes, esperar recall alto (poucos falsos negativos). É normal e esperado ter algum erro — o objetivo do teste é **medir e documentar**, não chegar a 100%. Esse número (ex.: "detectou 8 de 9 motos visíveis, 89% de recall nesta amostra") é material direto para a seção de avaliação experimental do TCC.

4. Repita com pelo menos mais 2-3 imagens/frames em condições diferentes (mais longe, mais perto, mais veículos, sombra) para não tirar conclusão de uma amostra só.

---

## 3. Tracking — teste de estabilidade com vídeo

Usa `vídeo_moto.mp4`.

**Passo a passo:**
1. Rode `python main.py --source vídeo_moto.mp4` (com janela aberta, sem `--no-display`).
2. Escolha visualmente 2-3 motos específicas no vídeo e acompanhe o número (`#ID`) que aparece ao lado de cada uma.
3. Anote quantas vezes o ID de uma mesma moto **trocou** durante o trajeto dela em cena (isso indica que o tracker "perdeu" o objeto, geralmente por oclusão — outro veículo passando na frente, ou saída parcial de quadro).

**Critério de sucesso:** o ideal é 0 trocas de ID por trajeto. 1 troca ocasional em cena com muita oclusão é aceitável e deve ser citado como limitação. Muitas trocas (a cada poucos segundos) indica que vale ajustar o `conf` em `config.py` ou revisar a taxa de FPS processada.

**Por que isso importa mais do que parece:** se o tracking troca de ID no meio do trajeto, a velocidade calculada por `risk.py` fica errada (o histórico "reinicia" com um ID novo). Por isso esse teste vem antes de confiar nos números de velocidade.

---

## 4. Velocidade/distância — teste com valor real conhecido

Depois que a calibração e o tracking estiverem OK isoladamente, valide a integração:

1. Escolha um trecho do vídeo em que dê pra estimar visualmente a velocidade aproximada (ex.: você sabe que aquele trecho é via urbana, limite de 40-50km/h, tráfego fluindo normal).
2. Calibre com dois pontos de referência reais na cena (ex.: largura da via, ~3m por faixa).
3. Rode o pipeline e observe os valores de km/h exibidos sobre as motos.

**Critério de sucesso:** os valores devem estar numa faixa plausível (não 300km/h nem 0.5km/h para uma moto em movimento normal). Se estiverem muito fora da faixa esperada, o problema costuma ser a calibração (pontos errados ou distância real informada errada) — não o cálculo em si, que já está testado isoladamente na seção 1.

---

## 5. `db.py` — teste de persistência

Precisa de um PostgreSQL rodando (pode ser local ou um banco de teste separado do de produção).

**Passo a passo:**
1. Configure as variáveis de ambiente apontando para um banco de teste (ex.: `projeto_motos_test`), **não** o banco real, para não misturar dados de teste com dados do TCC.
2. Rode `python main.py --source moto_teste.jpg --no-display`.
3. Confira no banco:
   ```sql
   SELECT count(*) FROM deteccoes;
   SELECT * FROM deteccoes ORDER BY id DESC LIMIT 5;
   ```
4. Verifique se `track_id`, `vehicle_type`, `x`, `y` batem com o que apareceu na tela/log.
5. Rode o pipeline uma segunda vez sobre um vídeo curto e confirme que `garantir_schema()` não duplica nem quebra a tabela (deve ser idempotente — rodar de novo não deve dar erro nem recriar do zero).

**Critério de sucesso:** número de linhas inseridas bate com o número de detecções processadas; nenhum erro de conexão/schema ao rodar múltiplas vezes.

---

## 6. Teste de integração ponta a ponta

Só depois que 1-5 passaram individualmente:

```bash
python main.py --source vídeo_moto.mp4 --calib-p1 "X,Y" --calib-p2 "X,Y" --calib-dist N --no-display
```

Rodar o vídeo inteiro sem travar, checar no final:
- total de motos únicas rastreadas (impresso no console) bate com a contagem manual;
- banco populado com velocidade/distância preenchidas para a maioria dos registros (não tudo `NULL`);
- tempo de execução razoável (anotar FPS de processamento — vira dado para a seção de desempenho do TCC).

---

## Resumo — ordem recomendada

1. `pytest tests/` (automatizado, roda toda vez, custa segundos)
2. Detecção em imagens (visual)
3. Tracking em vídeo (estabilidade de ID)
4. Velocidade/distância com calibração real (plausibilidade)
5. Persistência no banco de teste
6. Integração ponta a ponta

Cada nível só vale a pena testar depois que o anterior estiver ok — testar velocidade antes de confirmar que o tracking é estável, por exemplo, mistura dois problemas diferentes e dificulta saber qual consertar.
