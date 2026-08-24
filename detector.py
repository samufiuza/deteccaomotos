"""
Detecção + rastreamento de veículos com YOLO/ByteTrack.

Reaproveita o tracker nativo do Ultralytics em vez de reimplementar
a lógica de rastreamento manualmente (o que era feito nos scripts anteriores).
"""

from ultralytics import YOLO
from config import (
    MODEL_PATH,
    TRACKER_CONFIG,
    CONF_THRESHOLD,
    TARGET_CLASSES,
)


def carregar_modelo():
    return YOLO(MODEL_PATH)


def detectar_e_rastrear(frame, model):
    """
    Roda detecção + tracking em um frame.

    Retorna uma lista de dicts:
    {"track_id": int|None, "vehicle_type": str, "confidence": float,
     "x": float, "y": float, "bbox": (x1, y1, x2, y2)}

    x, y = centro da bounding box (base para velocidade/distância nas próximas etapas).
    """
    results = model.track(
        frame,
        persist=True,
        classes=list(TARGET_CLASSES.keys()),
        conf=CONF_THRESHOLD,
        tracker=TRACKER_CONFIG,
        verbose=False,
    )

    objetos = []
    res = results[0]
    if res.boxes is None:
        return objetos, res

    ids = res.boxes.id.cpu().numpy().astype(int) if res.boxes.id is not None else None

    for i, box in enumerate(res.boxes):
        x1, y1, x2, y2 = map(float, box.xyxy[0].cpu().numpy())
        conf = float(box.conf[0].cpu().numpy())
        cls_idx = int(box.cls[0].cpu().numpy())
        cls_name = TARGET_CLASSES.get(cls_idx, model.names.get(cls_idx, "unknown"))
        track_id = int(ids[i]) if ids is not None else None

        objetos.append({
            "track_id": track_id,
            "vehicle_type": cls_name,
            "confidence": conf,
            "x": (x1 + x2) / 2,
            "y": (y1 + y2) / 2,
            "bbox": (x1, y1, x2, y2),
        })

    return objetos, res
