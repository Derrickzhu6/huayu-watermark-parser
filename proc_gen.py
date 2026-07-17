
import cv2
import numpy as np


def create_mask_from_strokes(image_shape, points, radius=10):
    mask = np.zeros(image_shape[:2], dtype=np.uint8)
    if not points or len(points) < 1:
        return mask
    for pt in points:
        if isinstance(pt, dict):
            x, y = float(pt.get('x', 0)), float(pt.get('y', 0))
        else:
            x, y = float(pt[0]), float(pt[1])
        cv2.circle(mask, (int(round(x)), int(round(y))), radius, 255, -1)
    return mask


def refine_inpaint(image: np.ndarray, mask: np.ndarray, radius: int = 5,
                   method: str = "telea", sharpen_strength: float = 0.3) -> np.ndarray:
    """
    高质量修复，带安全保护：
    - 修复面积 > 40% → 直接返回原图
    - 修复面积 20-40% → 少量度修复，无锐化
    - 修复面积 10-20% → 中等强度
    - 修复面积 < 10%   → 全强度 + 锐化
    """
    h, w = mask.shape
    mask_area = np.sum(mask > 0)
    total_area = h * w
    ratio = mask_area / total_area if total_area > 0 else 0

    # ── 安全门限 ──
    if ratio > 0.40:
        return image.copy()
    if ratio > 0.20:
        sharpen_strength = 0.0
        radius = min(radius, 3)
    elif ratio > 0.10:
        sharpen_strength = min(sharpen_strength, 0.15)

    # ── 膨胀掩码 ──
    kernel = np.ones((3, 3), np.uint8)
    expanded = cv2.dilate(mask, kernel, iterations=2)

    # ── 修复 ──
    flag = cv2.INPAINT_TELEA if method == "telea" else cv2.INPAINT_NS
    inpainted = cv2.inpaint(image, expanded, max(radius, 3), flag)

    # ── 锐化（仅修复区域） ──
    if sharpen_strength > 0:
        f = inpainted.astype(np.float32)
        blurred = cv2.GaussianBlur(f, (0, 0), 2)
        sharpened = cv2.addWeighted(f, 1.0 + sharpen_strength, blurred,
                                    -sharpen_strength, 0)
        sharpened = np.clip(sharpened, 0, 255).astype(np.uint8)

        mask_3ch = cv2.cvtColor(expanded, cv2.COLOR_GRAY2BGR).astype(np.float32) / 255.0
        result = (inpainted.astype(np.float32) * (1 - mask_3ch) +
                  sharpened.astype(np.float32) * mask_3ch)
        result = np.clip(result, 0, 255).astype(np.uint8)
    else:
        result = inpainted.copy()

    # ── 边缘羽化 ──
    edge = cv2.dilate(mask, kernel, iterations=3) & ~expanded
    if np.any(edge):
        dist = cv2.distanceTransform((edge > 0).astype(np.uint8), cv2.DIST_L2, 3)
        dist = cv2.normalize(dist, None, 0, 1, cv2.NORM_MINMAX)
        alpha = cv2.cvtColor((dist * 255).astype(np.uint8),
                             cv2.COLOR_GRAY2BGR).astype(np.float32) / 255.0
        alpha *= 0.4
        result = (result.astype(np.float32) * (1 - alpha) +
                  image.astype(np.float32) * alpha)
        result = np.clip(result, 0, 255).astype(np.uint8)

    return result.astype(np.uint8)
