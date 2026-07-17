"""
Watermark Removal Engine v10 - Hybrid Approach
  - LaMa AI inpainting (best quality, ~3-8s on CPU)
  - OpenCV enhanced (fast fallback, ~0.5s)
"""

import cv2
import numpy as np


def _get_mask_ratio(mask):
    return float(np.sum(mask > 0)) / float(mask.size)


def improved_inpaint(image, mask, use_texture=True, use_color_match=True, quality="quality"):
    """
    Hybrid inpainting engine.
    
    quality="quality": Uses LaMa AI model when available, falls back to OpenCV
    quality="speed": Always uses OpenCV fast path
    """
    mask_ratio = _get_mask_ratio(mask)
    if mask_ratio < 0.0001:
        return image.copy()
    if mask_ratio > 0.65:
        return image.copy()
    
    # Brush/text removal: aggressively cover then inpaint
    mask_ratio = _get_mask_ratio(mask)
    if mask_ratio < 0.50:
        # Dilate the mask aggressively to ensure full coverage
        dilate_kernel = np.ones((7, 7), np.uint8) if mask_ratio < 0.05 else np.ones((5, 5), np.uint8)
        iterations = 3 if mask_ratio < 0.05 else 2
        expanded_mask = cv2.dilate((mask > 0).astype(np.uint8), dilate_kernel, iterations=iterations)
        try:
            from .text_inpaint import remove_text_watermark
            result = remove_text_watermark(image, expanded_mask, radius=3)
            if result is not None and result.shape == image.shape:
                print("[DEBUG] Text removal done", flush=True)
                return result
        except Exception as e:
            print(f"[DEBUG] Text removal failed: {e}", flush=True)
    
    # Try LaMa for quality mode  
    if quality == "quality":
        try:
            from .lama_inpaint import lama_inpaint, is_lama_available
            _lama_ok = is_lama_available()
            print(f"[DEBUG] LaMa available: {_lama_ok}", flush=True)
            if _lama_ok:
                result = lama_inpaint(image, mask)
                if result is not None and result.shape == image.shape:
                    return result
        except Exception:
            pass  # Fall through to OpenCV
    # OpenCV fallback
    return _opencv_inpaint(image, mask, use_texture, use_color_match)


def _opencv_inpaint(image, mask, use_texture=True, use_color_match=True):
    """Enhanced OpenCV inpainting with texture synthesis"""
    mask_ratio = _get_mask_ratio(mask)
    h, w = image.shape[:2]
    
    kernel = np.ones((3, 3), np.uint8)
    refined = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    refined = cv2.dilate(refined, kernel, iterations=2)
    mask_f = refined > 0
    
    if mask_ratio > 0.15:
        result = _fast_inpaint(image, refined)
    else:
        result = _quality_inpaint(image, refined)
    
    if use_color_match:
        result = _color_match(image, result, refined, mask_f)
    
    result = _feather_edges(image, result, refined)
    return np.clip(result, 0, 255).astype(np.uint8)


def _fast_inpaint(image, mask):
    """Multi-kernel blur + texture transfer"""
    h, w = image.shape[:2]
    result_f = np.zeros_like(image, dtype=np.float32)
    
    for ksize in [5, 9, 15]:
        blurred = cv2.medianBlur(image, ksize).astype(np.float32)
        result_f += blurred / 3
    
    result = np.clip(result_f, 0, 255).astype(np.uint8)
    
    # Texture transfer
    surround = cv2.dilate(mask, np.ones((25, 25), np.uint8))
    source_region = surround & (~cv2.dilate(mask, np.ones((5, 5), np.uint8)))
    
    if np.sum(source_region > 0) > 500:
        img_f = image.astype(np.float32)
        base = cv2.GaussianBlur(img_f, (0, 0), 3)
        texture = img_f - base
        texture[~source_region] = 0
        
        dist = cv2.distanceTransform((mask > 0).astype(np.uint8), cv2.DIST_L2, 3)
        alpha = np.clip(dist / 15.0, 0, 1)
        alpha_3ch = np.stack([alpha] * 3, axis=-1)
        result = np.clip(result_f + texture * alpha_3ch * 0.12, 0, 255).astype(np.uint8)
    
    sharp = np.clip(result, 0, 255).astype(np.uint8)
    blr = cv2.GaussianBlur(sharp, (0, 0), 0.5)
    sharpened = cv2.addWeighted(sharp, 1.3, blr, -0.3, 0)
    
    mask_3ch = np.stack([(mask > 0).astype(np.float32)] * 3, axis=-1)
    final = sharpened.astype(np.float32) * mask_3ch + image.astype(np.float32) * (1 - mask_3ch)
    return np.clip(final, 0, 255).astype(np.uint8)


def _quality_inpaint(image, mask):
    """Patch-based texture synthesis"""
    h, w = image.shape[:2]
    img_f = image.astype(np.float32)
    
    dilated = cv2.dilate(mask, np.ones((3, 3), np.uint8), iterations=2)
    inpainted = cv2.inpaint(image, dilated, 5, cv2.INPAINT_TELEA)
    structure = cv2.bilateralFilter(inpainted, 9, 50, 50).astype(np.float32)
    orig_structure = cv2.bilateralFilter(image, 9, 50, 50).astype(np.float32)
    orig_texture = img_f - orig_structure
    
    non_mask = (dilated == 0)
    mask_y, mask_x = np.where(dilated > 0)
    
    if len(mask_y) > 0:
        result_f = structure.copy()
        patch_size = 7
        half = patch_size // 2
        
        for i in range(0, len(mask_y), 3):
            py, px = mask_y[i], mask_x[i]
            if py < half or py >= h - half or px < half or px >= w - half:
                continue
            
            sp = structure[py-half:py+half+1, px-half:px+half+1]
            
            y1 = max(half, py - 20)
            y2 = min(h - half, py + 20)
            x1 = max(half, px - 20)
            x2 = min(w - half, px + 20)
            
            best_ssd = float("inf")
            best_ty, best_tx = py, px
            
            for sy in range(y1, y2 - patch_size + 1, 2):
                for sx in range(x1, x2 - patch_size + 1, 2):
                    cy, cx = sy + half, sx + half
                    if not non_mask[cy, cx]:
                        continue
                    cp = orig_structure[sy:sy+patch_size, sx:sx+patch_size]
                    ssd = float(np.sum((sp - cp) ** 2))
                    if ssd < best_ssd:
                        best_ssd = ssd
                        best_ty, best_tx = sy, sx
            
            if best_ssd < 1e8:
                tex = orig_texture[best_ty:best_ty+patch_size, best_tx:best_tx+patch_size]
                wy = np.hanning(patch_size)
                wx = np.hanning(patch_size)
                weights = wy[:, None] * wx[None, :]
                w_3ch = np.stack([weights] * 3, axis=-1) * 0.7 + 0.3
                blended = sp + tex
                result_f[py-half:py+half+1, px-half:px+half+1] = \
                    result_f[py-half:py+half+1, px-half:px+half+1] * (1 - w_3ch) + blended * w_3ch
        
        result = np.clip(result_f, 0, 255).astype(np.uint8)
    else:
        result = inpainted
    
    mask_3ch = np.stack([(dilated > 0).astype(np.float32)] * 3, axis=-1)
    final = result.astype(np.float32) * mask_3ch + image.astype(np.float32) * (1 - mask_3ch)
    return np.clip(final, 0, 255).astype(np.uint8)


def _color_match(original, result, mask, mask_f):
    surround = cv2.dilate(mask, np.ones((25, 25), np.uint8))
    surround_region = surround & (~cv2.dilate(mask, np.ones((5, 5), np.uint8)))
    if np.sum(surround_region > 0) < 100:
        return result
    
    result_f = result.astype(np.float32)
    for c in range(3):
        orig_surround = original[:, :, c][surround_region > 0]
        result_mask = result_f[:, :, c][mask_f]
        if len(orig_surround) < 10 or len(result_mask) < 10:
            continue
        orig_mean = np.mean(orig_surround)
        orig_std = max(np.std(orig_surround), 1)
        result_mean = np.mean(result_mask)
        result_std = max(np.std(result_mask), 1)
        adjusted = (result_f[:, :, c] - result_mean) * (orig_std / result_std) + orig_mean
        result_f[:, :, c][mask_f] = adjusted[mask_f]
    return np.clip(result_f, 0, 255).astype(np.uint8)


def _feather_edges(original, result, mask):
    kernel = np.ones((9, 9), np.uint8)
    outer = cv2.dilate(mask, kernel, iterations=3)
    edge_region = outer & (~cv2.dilate(mask, np.ones((3, 3), np.uint8), iterations=1))
    if np.any(edge_region):
        dist = cv2.distanceTransform((edge_region > 0).astype(np.uint8), cv2.DIST_L2, 3)
        max_d = np.max(dist)
        if max_d > 0:
            alpha = np.clip(dist / max_d, 0, 1) * 0.12
            a3 = np.stack([alpha] * 3, axis=-1)
            result = (result.astype(np.float32) * (1 - a3) + original.astype(np.float32) * a3)
    return np.clip(result, 0, 255).astype(np.uint8)
