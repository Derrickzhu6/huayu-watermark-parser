"""
Text Watermark Removal Engine - Fast & Quality
Strategy:
  1. Precise thin mask
  2. Multi-radius TELEA inpainting (fast, good for thin text)
  3. Color matching from surrounding area
  4. Minimal edge blending
"""

import cv2
import numpy as np


def remove_text_watermark(image, mask, radius=2):
    h, w = image.shape[:2]
    result = image.copy()
    
    kernel = np.ones((2, 2), np.uint8)
    working_mask = cv2.dilate((mask > 0).astype(np.uint8), kernel, iterations=1)
    
    n, labels, stats, _ = cv2.connectedComponentsWithStats(working_mask, 8)
    if n < 2:
        return image.copy()
    
    for i in range(1, n):
        x = stats[i, cv2.CC_STAT_LEFT]
        y = stats[i, cv2.CC_STAT_TOP]
        bw = stats[i, cv2.CC_STAT_WIDTH]
        bh = stats[i, cv2.CC_STAT_HEIGHT]
        area = stats[i, cv2.CC_STAT_AREA]
        
        if area < 5 or bw < 2 or bh < 2:
            continue
        
        # Crop region with padding
        pad = max(20, min(bw, bh))
        x1 = max(0, x - pad)
        y1 = max(0, y - pad)
        x2 = min(w, x + bw + pad)
        y2 = min(h, y + bh + pad)
        
        roi_img = image[y1:y2, x1:x2]
        roi_mask = working_mask[y1:y2, x1:x2]
        
        # TELEA inpainting
        inpainted = cv2.inpaint(roi_img, roi_mask, radius, cv2.INPAINT_TELEA)
        
        # Color match to surrounding area
        inpainted = _color_match(roi_img, inpainted, roi_mask)
        
        # Feather edges
        roi_result = _feather_edges(
            roi_img.astype(np.float32),
            inpainted.astype(np.float32),
            roi_mask
        )
        
        result[y1:y2, x1:x2] = np.clip(roi_result, 0, 255).astype(np.uint8)
    
    return result


def _color_match(original, result, mask):
    """Match color of result area to surrounding original area"""
    surround = cv2.dilate(mask, np.ones((15, 15), np.uint8), iterations=1)
    surround_region = surround & (~cv2.dilate(mask, np.ones((3, 3), np.uint8), iterations=1))
    
    if np.sum(surround_region > 0) < 30:
        return result
    
    mask_f = (mask > 0)
    result_f = result.astype(np.float32)
    
    for c in range(3):
        orig_surround = original[:, :, c][surround_region > 0]
        result_mask = result_f[:, :, c][mask_f]
        
        if len(orig_surround) < 10 or len(result_mask) < 10:
            continue
        
        orig_mean = float(np.mean(orig_surround))
        orig_std = max(float(np.std(orig_surround)), 1)
        result_mean = float(np.mean(result_mask))
        result_std = max(float(np.std(result_mask)), 1)
        
        adjusted = (result_f[:, :, c] - result_mean) * (orig_std / result_std) + orig_mean
        result_f[:, :, c][mask_f] = adjusted[mask_f]
    
    return np.clip(result_f, 0, 255).astype(np.uint8)


def _feather_edges(original_f, result_f, mask):
    kernel = np.ones((3, 3), np.uint8)
    outer = cv2.dilate(mask, kernel, iterations=2)
    edge = outer & (~cv2.dilate(mask, kernel, iterations=1))
    
    if np.any(edge):
        dist = cv2.distanceTransform((edge > 0).astype(np.uint8), cv2.DIST_L2, 3)
        max_d = np.max(dist)
        if max_d > 0:
            alpha = np.clip(dist / max_d, 0, 1) * 0.15
            a3 = np.stack([alpha] * 3, axis=-1)
            result_f = result_f * (1 - a3) + original_f * a3
    
    return result_f
