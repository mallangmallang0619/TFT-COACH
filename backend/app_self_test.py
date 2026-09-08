"""Exercise shipped native dependencies without a game or installed Python."""
import json
import cv2
import numpy as np
from app_paths import PATHS, cache_path
from detector import Detector, pytesseract


def run():
    import windows_capture
    from websocket_server import TFTCoachServer
    detector = Detector()
    if not detector.unit_classifier.available:
        raise RuntimeError('Bundled champion model did not load')
    detector.unit_classifier.classify_batch([np.full((192, 192, 3), 100, np.uint8)])
    if detector.star_level_classifier.available:
        detector.star_level_classifier._infer([np.full((96, 96, 3), 100, np.uint8)])
    text = np.full((80, 260, 3), 255, np.uint8)
    cv2.putText(text, '123', (15, 60), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 0), 3)
    result = pytesseract.image_to_string(text, config='--psm 7').strip()
    if result != '123':
        raise RuntimeError(f'Bundled Tesseract failed OCR: {result!r}')
    for directory in (PATHS.logs, PATHS.diagnostics, PATHS.training):
        directory.mkdir(parents=True, exist_ok=True)
    cache_path('tftacademy_cache.json')
    report = {'ok': True, 'frozen': PATHS.frozen, 'ocr': result,
              'resources': str(PATHS.resources), 'data': str(PATHS.data),
              'model_available': detector.unit_classifier.available,
              'star_model_available': detector.star_level_classifier.available}
    (PATHS.logs / 'self-test.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report), flush=True)
    return 0
