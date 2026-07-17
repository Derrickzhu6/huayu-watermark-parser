"""
Auto Watermark Detection - Multi-strategy with corner detection
Strategies:
  1. Corner detection (watermarks most often in corners)
  2. Brightness/texture anomaly detection  
  3. MSER text detection
  4. Edge density analysis
  5. Color consistency detection
"""

import cv2
import numpy as np


def _corner_watermark_detect(image):
    """Strategy 1: Detect watermarks in corners (most common location)"""
    h, w = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    mask = np.zeros((h, w), dtype=np.uint8)
    
    # Define corner regions (15% from each edge)
    corner_size_h = int(h * 0.15)
    corner_size_w = int(w * 0.15)
    
    corners = [
        (0, 0, corner_size_w, corner_size_h),                           # top-left
        (w - corner_size_w, 0, corner_size_w, corner_size_h),           # top-right
        (0, h - corner_size_h, corner_size_w, corner_size_h),           # bottom-left
        (w - corner_size_w, h - corner_size_h, corner_size_w, corner_size_h),  # bottom-right
    ]
    
    for cx, cy, cw, ch in corners:
        roi = gray[cy:cy+ch, cx:cx+cw]
        roi_area = roi.shape[0] * roi.shape[1]
        if roi_area < 100:
            continue
        
        # Try multiple detection methods on each corner
        
        # Method A: Look for text-like patterns (edges + uniform interior)
        edges = cv2.Canny(roi, 30, 150)
        edge_density = np.sum(edges > 0) / roi_area
        
        if edge_density > 0.01 and edge_density < 0.3:
            # Dilate edges to find connected regions
            kernel = np.ones((3, 3), np.uint8)
            dilated = cv2.dilate(edges, kernel, iterations=2)
            closed = cv2.morphologyEx(dilated, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
            
            n, labels, stats, _ = cv2.connectedComponentsWithStats(closed, 8)
            for i in range(1, n):
                area = stats[i, cv2.CC_STAT_AREA]
                if area < 50 or area > roi_area * 0.3:
                    continue
                bx, by, bw, bh = stats[i, cv2.CC_STAT_LEFT], stats[i, cv2.CC_STAT_TOP], stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT]
                # Check if region has consistent brightness (watermark characteristic)
                region_pixels = roi[by:by+bh, bx:bx+bw]
                mean_val = np.mean(region_pixels)
                std_val = np.std(region_pixels)
                if std_val < 50 and 20 < mean_val < 240:
                    mask[cy+by:cy+by+bh, cx+bx:cx+bx+bw] = 255
        
        # Method B: Semi-transparent overlay detection (common for logos)
        # Check if corner has uniform color shift compared to surrounding
        surround_pad = 20
        sy1 = max(0, cy - surround_pad)
        sy2 = min(h, cy + ch + surround_pad)
        sx1 = max(0, cx - surround_pad)
        sx2 = min(w, cx + cw + surround_pad)
        
        if sy2 - sy1 > ch and sx2 - sx1 > cw:
            surround = gray[sy1:sy2, sx1:sx2]
            # Create mask for corner vs surround
            corner_mask = np.zeros(surround.shape, dtype=np.uint8)
            corner_mask[cy-sy1:cy-sy1+ch, cx-sx1:cx-sx1+cw] = 1
            
            if np.sum(corner_mask > 0) > 50 and np.sum(corner_mask == 0) > 50:
                corner_pixels = surround[corner_mask > 0]
                surround_pixels = surround[corner_mask == 0]
                
                mean_diff = abs(np.mean(corner_pixels) - np.mean(surround_pixels))
                if mean_diff > 5 and mean_diff < 80:
                    mask[cy:cy+ch, cx:cx+cw] = 255
    
    return mask


def _brightness_anomaly_detect(image):
    """Strategy 2: Detect brightness/texture anomalies"""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    
    # Compute local mean and std
    local_mean = cv2.boxFilter(gray.astype(np.float32), cv2.CV_32F, (15, 15))
    local_std = cv2.boxFilter((gray.astype(np.float32) - local_mean) ** 2, cv2.CV_32F, (15, 15))
    local_std = np.sqrt(np.abs(local_std)) + 0.01
    
    # Z-score: how much each pixel deviates from its neighborhood
    z = (gray.astype(np.float32) - local_mean) / local_std
    
    # Anomalies (both bright and dark)
    anomalies = (np.abs(z) > 2.0).astype(np.uint8) * 255
    
    # Clean up
    kernel = np.ones((3, 3), np.uint8)
    anomalies = cv2.morphologyEx(anomalies, cv2.MORPH_CLOSE, kernel)
    anomalies = cv2.erode(anomalies, kernel, iterations=1)
    
    # Only keep connected components that look like watermarks
    n, labels, stats, _ = cv2.connectedComponentsWithStats(anomalies, 8)
    result = np.zeros((h, w), dtype=np.uint8)
    
    for i in range(1, n):
        area = stats[i, cv2.CC_STAT_AREA]
        if area < 20 or area > h * w * 0.15:
            continue
        x, y, bw, bh = stats[i, cv2.CC_STAT_LEFT], stats[i, cv2.CC_STAT_TOP], stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT]
        
        # Check aspect ratio (watermarks tend to be wide or square, not tall thin lines)
        aspect = max(bw, bh) / max(min(bw, bh), 1)
        if aspect < 15:  # Not too elongated
            result[labels == i] = 255
    
    return result


def _text_detect(image):
    """Strategy 3: Adaptive threshold text detection"""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    mask = np.zeros((h, w), dtype=np.uint8)
    
    # Try both dark-on-light and light-on-dark
    for inv in [True, False]:
        if inv:
            th = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                       cv2.THRESH_BINARY_INV, 25, 5)
        else:
            th = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                       cv2.THRESH_BINARY, 25, 5)
        
        # Clean
        kernel = np.ones((2, 2), np.uint8)
        th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, kernel)
        
        n, labels, stats, _ = cv2.connectedComponentsWithStats(th, 8)
        for i in range(1, n):
            area = stats[i, cv2.CC_STAT_AREA]
            bw = stats[i, cv2.CC_STAT_WIDTH]
            bh = stats[i, cv2.CC_STAT_HEIGHT]
            if area < 10 or area > 5000:
                continue
            aspect = max(bw, bh) / (min(bw, bh) + 1)
            if aspect > 8:
                continue
            x, y = stats[i, cv2.CC_STAT_LEFT], stats[i, cv2.CC_STAT_TOP]
            pad = 2
            x1 = max(0, x - pad); y1 = max(0, y - pad)
            x2 = min(w, x + bw + pad); y2 = min(h, y + bh + pad)
            mask[y1:y2, x1:x2] = 255
    
    return mask


def _edge_density_detect(image):
    """Strategy 4: Edge density - watermarks often have distinct edge patterns"""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    
    edges = cv2.Canny(gray, 20, 100)
    edge_density = cv2.boxFilter(edges.astype(np.float32), cv2.CV_32F, (15, 15))
    
    # Normalize
    edge_density = edge_density / np.max(edge_density + 0.01) * 255
    
    # Threshold for high edge density areas
    _, mask = cv2.threshold(edge_density.astype(np.uint8), 50, 255, cv2.THRESH_BINARY)
    
    # Clean
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    mask = cv2.erode(mask, kernel, iterations=2)
    
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    result = np.zeros((h, w), dtype=np.uint8)
    
    for i in range(1, n):
        area = stats[i, cv2.CC_STAT_AREA]
        if area < 30 or area > h * w * 0.04:
            continue
        result[labels == i] = 255
    
    return result


def _color_uniformity_detect(image):
    """Strategy 5: Detect color-uniform regions (logos/badges often have consistent color)"""
    h, w = image.shape[:2]
    img_f = image.astype(np.float32)
    
    # Compute color std in local windows
    means = []
    stds = []
    for c in range(3):
        mean = cv2.boxFilter(img_f[:,:,c], cv2.CV_32F, (11, 11))
        var = cv2.boxFilter((img_f[:,:,c] - mean) ** 2, cv2.CV_32F, (11, 11))
        means.append(mean)
        stds.append(np.sqrt(np.abs(var)))
    
    # Average std across channels
    avg_std = sum(stds) / 3
    
    # Low std means uniform color (watermark characteristic)
    low_std = (avg_std < 12).astype(np.uint8) * 255
    
    # But exclude pure white/black backgrounds
    avg_brightness = (means[0] + means[1] + means[2]) / 3
    valid = (avg_brightness > 15) & (avg_brightness < 245)
    low_std[~valid] = 0
    
    kernel = np.ones((3, 3), np.uint8)
    low_std = cv2.morphologyEx(low_std, cv2.MORPH_CLOSE, kernel)
    low_std = cv2.erode(low_std, kernel, iterations=1)
    
    n, labels, stats, _ = cv2.connectedComponentsWithStats(low_std, 8)
    result = np.zeros((h, w), dtype=np.uint8)
    
    for i in range(1, n):
        area = stats[i, cv2.CC_STAT_AREA]
        if area < 30 or area > h * w * 0.12:
            continue
        result[labels == i] = 255
    
    return result


def _corner_text_detect(image):
    """Strategy 6: Aggressive text detection in corners for small watermarks"""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    mask = np.zeros((h, w), dtype=np.uint8)
    
    # Define corner zones (20% from edges)
    zones = [
        (0, 0, int(w*0.12), int(h*0.12)),          # top-left
        (w-int(w*0.20), 0, int(w*0.12), int(h*0.12)),  # top-right
        (0, h-int(h*0.20), int(w*0.12), int(h*0.12)),  # bottom-left
        (w-int(w*0.20), h-int(h*0.20), int(w*0.12), int(h*0.12)),  # bottom-right
    ]
    
    for zx, zy, zw, zh in zones:
        roi = gray[zy:zy+zh, zx:zx+zw]
        if roi.size < 100:
            continue
        
        # Try adaptive threshold to separate text from background
        thresh = cv2.adaptiveThreshold(roi, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                       cv2.THRESH_BINARY_INV, 31, 5)
        
        # Clean up
        kernel = np.ones((2, 2), np.uint8)
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
        thresh = cv2.erode(thresh, kernel, iterations=1)
        
        # Get connected components
        n, labels, stats, _ = cv2.connectedComponentsWithStats(thresh, 8)
        zone_text_count = 0
        for i in range(1, n):
            area = stats[i, cv2.CC_STAT_AREA]
            if area < 10 or area > zw*zh*0.10:
                continue
            bw = stats[i, cv2.CC_STAT_WIDTH]
            bh = stats[i, cv2.CC_STAT_HEIGHT]
            aspect = max(bw, bh) / (min(bw, bh) + 1)
            if aspect < 8 and bh < zh*0.3:
                bx, by = stats[i, cv2.CC_STAT_LEFT], stats[i, cv2.CC_STAT_TOP]
                mask[zy+by:zy+by+bh, zx+bx:zx+bx+bw] = 255
                zone_text_count += 1
        
        # If only a few text components found in corner, it's likely a watermark
        # Expand the area around them generously
        if 1 <= zone_text_count <= 10:
            cy, cx = zy + zh//2, zx + zw//2
            expand = int(min(zw, zh) * 0.15)
            y1 = max(0, cy - expand)
            y2 = min(h, cy + expand)
            x1 = max(0, cx - expand)
            x2 = min(w, cx + expand)
            mask[y1:y2, x1:x2] = 255
    
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.dilate(mask, kernel, iterations=2)
    return mask



def merge_masks(*masks):
    """Merge multiple detection masks"""
    valid = [m for m in masks if m is not None and np.any(m > 0)]
    if not valid:
        return np.zeros((masks[0].shape if masks else (1, 1)), dtype=np.uint8)
    
    h, w = valid[0].shape
    merged = np.zeros((h, w), dtype=np.uint8)
    for mask in valid:
        merged = cv2.bitwise_or(merged, mask)
    
    kernel = np.ones((3, 3), np.uint8)
    merged = cv2.dilate(merged, kernel, iterations=1)
    merged = cv2.erode(merged, kernel, iterations=1)
    return merged


def auto_detect_watermark(image):
    h, w = image.shape[:2]
    total = h * w
    result = np.zeros((h, w), dtype=np.uint8)
    m3 = _text_detect(image)
    m6 = _corner_text_detect(image)
    text_mask = np.zeros((h, w), dtype=np.uint8)
    for m in [m3, m6]:
        if np.sum(m > 0) > 20:
            text_mask = cv2.bitwise_or(text_mask, m)
    text_area = int(np.sum(text_mask > 0))
    if text_area > 20:
        kernel = np.ones((3, 3), np.uint8)
        result = cv2.dilate(text_mask, kernel, iterations=2)
        print("[auto_detect] Text: " + str(text_area) + " px", flush=True)
        return result
    m1 = _corner_watermark_detect(image)
    corner_area = int(np.sum(m1 > 0))
    if corner_area > 30 and corner_area < total * 0.10:
        kernel = np.ones((3, 3), np.uint8)
        result = cv2.dilate(m1, kernel, iterations=1)
        print("[auto_detect] Corner: " + str(corner_area) + " px", flush=True)
        return result
    print("[auto_detect] No watermark", flush=True)
    return result


def auto_detect_and_inpaint(image, radius=5, method='telea'):
    """Convenience: detect + inpaint"""
    mask = auto_detect_watermark(image)
    if np.sum(mask > 0) < 10:
        return image.copy(), mask
    from processors.improved_inpaint import improved_inpaint
    result = improved_inpaint(image, mask)
    return result, mask
