# Pipeline consolidado — Detecção + Tracking + Velocidade + Distância + Zona de Risco

Substitui `detectio_motos.py`, `detection.py` e `main.py` do projeto original.

## Estrutura

```
config.py       - configurações (modelo, classes, banco via env vars)
calibration.py  - conversão pixel -> metros a partir de 2 pontos de referência
detector.py     - detecção + tracking (YOLO + ByteTrack nativo do Ultralytics)
risk.py         - velocidade, distância e zona de risco (implementados); score (stub, próxima etapa)
state.py        - histórico de posições e estado de zona por track_id (sem depender de YOLO/banco)
db.py           - conexão e persistência no PostgreSQL (detecções + eventos)
main.py         - orquestração / ponto de entrada
zonas_exemplo.json - exemplo de configuração de zonas de risco
```

## Instalação

```bash
pip install -r requirements.txt
```

## Configuração do banco

```bash
export DB_HOST=localhost
export DB_NAME=projeto_motos
export DB_USER=postgres
export DB_PASSWORD=sua_senha
```

A tabela `deteccoes` é criada automaticamente na primeira execução, caso não exista.

## Uso

```bash
# vídeo, sem calibração (velocidade não é calculada, distância fica em pixels)
python main.py --source vídeo_moto.mp4

# vídeo, com calibração (recomendado)
# marque na imagem dois pontos cuja distância real você conhece
# (ex.: duas faixas de pedestre, largura de uma via) e informe:
python main.py --source vídeo_moto.mp4 \
    --calib-p1 "100,400" --calib-p2 "500,400" --calib-dist 8

# imagem
python main.py --source moto_teste.jpg

# webcam
python main.py --source 0

# com zonas de risco (ver zonas_exemplo.json — ajuste as coordenadas pro seu vídeo)
python main.py --source vídeo_moto.mp4 --zonas zonas_exemplo.json

# sem abrir janela (ex.: rodando em servidor)
python main.py --source vídeo_moto.mp4 --no-display
```

### Como calibrar

1. Pause em um frame do vídeo (ex.: `cv2.imwrite` de um frame, ou um player qualquer).
2. Identifique dois pontos na imagem cuja distância real no mundo você conhece
   (ex.: início e fim de uma faixa de pedestres — geralmente ~3-4m; largura de
   uma pista — geralmente ~3m; postes com espaçamento conhecido).
3. Anote as coordenadas (x, y) em pixels desses dois pontos e a distância real em metros.
4. Passe em `--calib-p1`, `--calib-p2`, `--calib-dist`.

A escala assume que a câmera tem pouca inclinação/perspectiva — é uma aproximação
que deve ser explicitada como limitação no TCC.

### Como configurar zonas de risco

1. Copie `zonas_exemplo.json` e edite as coordenadas (em pixels, do frame do vídeo).
2. Cada zona é um polígono: lista de pontos `[x, y]`, na ordem (não precisa fechar
   o polígono repetindo o primeiro ponto no fim).
3. Passe o arquivo com `--zonas caminho/para/zonas.json`.
4. Quando um veículo rastreado entra em uma zona pela primeira vez (ou reentra
   depois de sair), um evento `entrada_zona_risco` é salvo na tabela `eventos`,
   já com a velocidade e distância estimadas naquele momento.

## O que muda em relação aos scripts antigos

- Um único módulo, sem duplicação de lógica entre os três arquivos anteriores.
- Sem senha nem caminho de vídeo hardcoded no código.
- Tracking usa o ByteTrack nativo do Ultralytics (`tracker="bytetrack.yaml"`) em vez de reimplementar contagem manual de IDs.
- Cada detecção é salva no banco com posição (x, y), velocidade estimada e distância até o veículo mais próximo no frame.
- Velocidade e distância só são calculadas com calibração; sem ela, o sistema avisa e segue funcionando (distância cai para pixels, velocidade fica `None`).
- Zonas de risco são configuráveis por JSON, sem precisar mexer no código; entrada em zona vira evento no banco.
- A lógica de histórico/zona vive em `state.py`, separada de `main.py`, para não depender de YOLO nem do banco — dá pra testar isoladamente.

## Testes automatizados

```bash
pip install pytest
python -m pytest tests/ -v
```

31 testes cobrindo calibração, velocidade, distância, point-in-polygon (inclusive polígono côncavo) e as transições de zona (entrada, permanência sem duplicar evento, saída, reentrada, múltiplos veículos simultâneos). Veja `TESTES.md` para o guia completo, incluindo os testes manuais que precisam do YOLO/vídeo real.

## Próxima etapa

Score de risco (`calcular_score` em `risk.py`) — ainda stub, combinando os eventos já detectados (velocidade elevada, proximidade perigosa, zona de risco) em uma pontuação 0–100.
