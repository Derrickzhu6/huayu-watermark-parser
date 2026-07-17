"""
LaMa ONNX Inpainting Integration
Model: opencv/inpainting_lama (inpainting_lama_2025jan.onnx)
Inputs: image (1,3,512,512) float[-1,1], mask (1,1,512,512) float[0,1]
Output: (1,3,512,512) float[-1,1]
"""

import os
import cv2
import numpy as np
from pathlib import Path

MODEL_PATH = Path(__file__).parent / "models" / "lama.onnx"
_session = None


def _get_session():
    global _session
    if _session is None:
        import onnxruntime
        if not MODEL_PATH.exists():
            raise FileNotFoundError(f"LaMa model not found at {MODEL_PATH}")
        _session = onnxruntime.InferenceSession(str(MODEL_PATH), providers=["CPUExecutionProvider"])
    return _session


def lama_inpaint(image, mask):
    """
    Run LaMa inpainting.
    
    Args:
        image: BGR numpy array (H, W, 3)
        mask: binary mask (H, W) where >0 = region to inpaint
    
    Returns:
        inpainted BGR image
    """
    h, w = image.shape[:2]
    mask_bin = (mask > 0).astype(np.uint8)
    
    ys, xs = np.where(mask_bin > 0)
    if len(ys) == 0:
        return image.copy()
    
    # Crop with padding
    pad = 40
    y1 = max(0, int(ys.min()) - pad)
    y2 = min(h, int(ys.max()) + pad + 1)
    x1 = max(0, int(xs.min()) - pad)
    x2 = min(w, int(xs.max()) + pad + 1)
    crop_h, crop_w = y2 - y1, x2 - x1
    
    img_crop = image[y1:y2, x1:x2].copy()
    mask_crop = mask_bin[y1:y2, x1:x2].copy()
    
    # Resize to 512x512 for model input
    img_resized = cv2.resize(img_crop, (512, 512), interpolation=cv2.INTER_LINEAR)
    mask_resized = cv2.resize(mask_crop, (512, 512), interpolation=cv2.INTER_NEAREST)
    
    # Normalize to [-1, 1]
    img_norm = img_resized.astype(np.float32) / 127.5 - 1.0
    mask_norm = (mask_resized > 0).astype(np.float32)
    
    # Batched inputs: (1, 3, 512, 512) and (1, 1, 512, 512)
    img_input = img_norm.transpose(2, 0, 1)[None, :, :, :]
    mask_input = mask_norm[None, None, :, :]
    
    # Run inference
    sess = _get_session()
    output = sess.run(None, {"image": img_input, "mask": mask_input})[0]
    
    # Post-process
    output = output[0].transpose(1, 2, 0)  # (512, 512, 3)
    output = np.clip((output + 1.0) * 127.5, 0, 255).astype(np.uint8)
    
    # Resize back to original crop size
    output = cv2.resize(output, (crop_w, crop_h), interpolation=cv2.INTER_LINEAR)
    
    # Paste back with improved edge blending (Gaussian feather)
    result = image.copy()
    
    # Create a soft mask with Gaussian-blurred edges
    mask_soft = (mask_crop > 0).astype(np.float32)
    # Blur the mask for smooth transition
    kernel_size = max(3, min(crop_h, crop_w) // 20 * 2 + 1)  # odd number, smaller kernel
    if kernel_size > 3:
        mask_soft = cv2.GaussianBlur(mask_soft, (kernel_size, kernel_size), 0)
    # Keep soft mask as-is, no amplification
    mask_soft = np.clip(mask_soft, 0, 1)
    
    mask_3ch = np.stack([mask_soft] * 3, axis=-1)
    result[y1:y2, x1:x2] = (
        output.astype(np.float32) * mask_3ch +
        image[y1:y2, x1:x2].astype(np.float32) * (1 - mask_3ch)
    ).astype(np.uint8)
    
    return result


def is_lama_available():
    return MODEL_PATH.exists() and os.path.getsize(str(MODEL_PATH)) > 1000000

def warmup():
    """Pre-warm the model on server startup to avoid cold start delay"""
    import cv2
    import numpy as np
    img = np.zeros((512, 512, 3), dtype=np.uint8)
    mask = np.zeros((512, 512), dtype=np.uint8)
    mask[200:300, 200:300] = 255
    try:
        t0 = time.time()
        result = lama_inpaint(img, mask)
        dt = time.time() - t0
        print(f"[LaMa] Warmup completed in {dt:.1f}s")
        return True
    except Exception as e:
        print(f"[LaMa] Warmup failed: {e}")
        return False
