
import cv2
import numpy as np


def quality_inpaint(image: np.ndarray, mask: np.ndarray,
                    patch_size: int = 7, search_radius: int = 25) -> np.ndarray:
    """
    高质量纹理合成修复（优化版）。
    速度优化：搜索范围缩小 → 25px，步长加大 → 3，只处理少量块。
    """
    h, w = mask.shape[:2]
    half = patch_size // 2

    # 膨胀掩码
    kernel = np.ones((3, 3), np.uint8)
    working_mask = cv2.dilate(mask, kernel, iterations=3)

    # 基础平滑修复
    smooth = cv2.inpaint(image, working_mask, 5, cv2.INPAINT_TELEA)

    # 非掩码区域
    non_masked = (working_mask == 0)

    # 如果掩码太大，用快速模式
    mask_ratio = np.sum(working_mask > 0) / (h * w)
    if mask_ratio > 0.1:
        # 大区域 -> 直接用 refine_inpaint 逻辑（锐化+羽化）
        return _fast_enhance(smooth, image, working_mask, mask)

    # 结构/纹理分离
    smooth_f = smooth.astype(np.float32)
    structure = cv2.bilateralFilter(smooth, 9, 75, 75).astype(np.float32)
    orig_structure = cv2.bilateralFilter(image, 9, 75, 75).astype(np.float32)
    orig_texture = image.astype(np.float32) - orig_structure

    # 累积器
    weight_sum = np.zeros((h, w), dtype=np.float32)
    color_sum = np.zeros((h, w, 3), dtype=np.float32)

    # 大步长网格处理（减少块数量）
    grid_step = max(half * 2, 8)
    processed = 0
    max_blocks = 80  # 最多处理80个块

    for gy in range(half, h - half, grid_step):
        for gx in range(half, w - half, grid_step):
            if working_mask[gy, gx] == 0:
                continue
            if processed >= max_blocks:
                break

            y1, y2 = gy - half, gy + half + 1
            x1, x2 = gx - half, gx + half + 1

            target_patch = structure[y1:y2, x1:x2]

            # 搜索范围
            sy1 = max(half, gy - search_radius)
            sy2 = min(h - half, gy + search_radius)
            sx1 = max(half, gx - search_radius)
            sx2 = min(w - half, gx + search_radius)

            best_ssd = float('inf')
            best_sy, best_sx = gy, gx

            # 步长 3 搜索
            for sy in range(sy1, sy2 - patch_size + 1, 3):
                for sx in range(sx1, sx2 - patch_size + 1, 3):
                    cy, cx = sy + half, sx + half
                    if not non_masked[cy, cx]:
                        continue
                    cs_y = min(sy, h - patch_size)
                    cs_x = min(sx, w - patch_size)
                    cand = orig_structure[cs_y:cs_y + patch_size, cs_x:cs_x + patch_size]
                    ssd = float(np.sum((target_patch - cand) ** 2))
                    if ssd < best_ssd:
                        best_ssd = ssd
                        best_sy, best_sx = sy, sx

            # 迁移纹理
            bsy = min(best_sy, h - patch_size)
            bsx = min(best_sx, w - patch_size)
            tex = orig_texture[bsy:bsy + patch_size, bsx:bsx + patch_size]
            blended = structure[y1:y2, x1:x2] + tex

            # 高斯融合
            wy = np.hanning(patch_size)
            wx = np.hanning(patch_size)
            weight = np.maximum(wy[:, None] * wx[None, :], 0.01)
            w_3ch = np.stack([weight] * 3, axis=-1)

            color_sum[y1:y2, x1:x2] += blended * w_3ch
            weight_sum[y1:y2, x1:x2] += weight
            processed += 1

        if processed >= max_blocks:
            break

    # 应用结果
    result_f = smooth_f.copy()
    valid = weight_sum > 0
    for c in range(3):
        result_f[valid, c] = color_sum[valid, c] / weight_sum[valid]

    result = np.clip(result_f, 0, 255).astype(np.uint8)

    # 与原图融合
    mask_3ch = cv2.cvtColor(working_mask, cv2.COLOR_GRAY2BGR).astype(np.float32) / 255.0
    final = smooth.astype(np.float32) * (1 - mask_3ch) + result.astype(np.float32) * mask_3ch

    # 边缘羽化
    edge = cv2.dilate(mask, kernel, iterations=5) & ~working_mask
    if np.any(edge):
        dist = cv2.distanceTransform((edge > 0).astype(np.uint8), cv2.DIST_L2, 3)
        dist = cv2.normalize(dist, None, 0, 1, cv2.NORM_MINMAX)
        alpha = cv2.cvtColor((dist * 255).astype(np.uint8),
                             cv2.COLOR_GRAY2BGR).astype(np.float32) / 255.0
        alpha *= 0.3
        final = (final * (1 - alpha) + image.astype(np.float32) * alpha)

    return np.clip(final, 0, 255).astype(np.uint8)


def _fast_enhance(smooth, original, working_mask, original_mask):
    """快速增强模式：锐化 + 羽化，不做纹理合成"""
    result = smooth.astype(np.float32)
    blurred = cv2.GaussianBlur(result, (0, 0), 2)
    sharpened = cv2.addWeighted(result, 1.3, blurred, -0.3, 0)
    sharpened = np.clip(sharpened, 0, 255).astype(np.uint8)

    mask_3ch = cv2.cvtColor(working_mask, cv2.COLOR_GRAY2BGR).astype(np.float32) / 255.0
    final = smooth.astype(np.float32) * (1 - mask_3ch) + sharpened.astype(np.float32) * mask_3ch

    # 羽化
    kernel = np.ones((3, 3), np.uint8)
    edge = cv2.dilate(original_mask, kernel, iterations=5) & ~working_mask
    if np.any(edge):
        dist = cv2.distanceTransform((edge > 0).astype(np.uint8), cv2.DIST_L2, 3)
        dist = cv2.normalize(dist, None, 0, 1, cv2.NORM_MINMAX)
        alpha = cv2.cvtColor((dist * 255).astype(np.uint8),
                             cv2.COLOR_GRAY2BGR).astype(np.float32) / 255.0
        alpha *= 0.3
        final = (final * (1 - alpha) + original.astype(np.float32) * alpha)

    return np.clip(final, 0, 255).astype(np.uint8)
