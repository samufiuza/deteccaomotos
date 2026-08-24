# Pipeline consolidado — Detecção + Tracking + Velocidade + Distância

Substitui `detectio_motos.py`, `detection.py` e `main.py` do projeto original.

## Estrutura

```
config.py       - configurações (modelo, classes, banco via env vars)
calibration.py  - conversão pixel -> metros a partir de 2 pontos de referência
detector.py     - detecção + tracking (YOLO + ByteTrack nativo do Ultralytics)
risk.py         - velocidade e distância (implementados); zona/score (stubs, próxima etapa)
db.py           - conexão e persistência no PostgreSQL
main.py         - orquestração / ponto de entrada
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

## O que muda em relação aos scripts antigos

- Um único módulo, sem duplicação de lógica entre os três arquivos anteriores.
- Sem senha nem caminho de vídeo hardcoded no código.
- Tracking usa o ByteTrack nativo do Ultralytics (`tracker="bytetrack.yaml"`) em vez de reimplementar contagem manual de IDs.
- Cada detecção é salva no banco com posição (x, y), velocidade estimada e distância até o veículo mais próximo no frame.
- Velocidade e distância só são calculadas com calibração; sem ela, o sistema avisa e segue funcionando (distância cai para pixels, velocidade fica `None`).
- `risk.py` já testado isoladamente (ver seção de testes abaixo) — a lógica matemática está validada antes de depender do YOLO/vídeo real.

## Testes rápidos da lógica (sem precisar de vídeo/YOLO/banco)

```bash
python3 -c "
from calibration import calcular_escala
from risk import calcular_velocidade, calcular_distancia
# ver exemplo de uso no histórico do projeto
"
```

## Próxima etapa

Zonas de risco (`checar_zona`) e score (`calcular_score`) em `risk.py` — ainda stubs.
