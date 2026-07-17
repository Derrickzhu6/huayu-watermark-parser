import sys, cv2, numpy as np
sys.path.insert(0, r"C:\AI_Workspace\01_Projects\视频解析API")
from processors.auto_detect import auto_detect_watermark

img = np.ones((800, 600, 3), dtype=np.uint8) * 220
np.random.seed(42)
noise = np.random.randint(-15, 15, img.shape, dtype=np.int8)
img = np.clip(img.astype(np.int16) + noise.astype(np.int16), 0, 255).astype(np.uint8)

overlay = img.copy()
cv2.putText(overlay, "抖音", (480, 45), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (180, 180, 180), 3)
cv2.putText(overlay, "@user123456", (440, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (160, 160, 160), 2)
img = cv2.addWeighted(overlay, 0.5, img, 0.5, 0)
cv2.putText(img, "请勿商用", (20, 770), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (150, 150, 150), 3)

print(f"Image: {img.shape}")
mask = auto_detect_watermark(img)
pixels = np.sum(mask > 0)
total = mask.shape[0] * mask.shape[1]
print(f"Auto detect: {pixels} pixels ({pixels/total*100:.2f}%)")

if pixels > 10:
    ys, xs = np.where(mask > 0)
    print(f"Mask box: y=[{ys.min()},{ys.max()}], x=[{xs.min()},{xs.max()}]")
    wm1 = np.any(mask[25:80, 440:540] > 0)
    wm2 = np.any(mask[760:780, 20:200] > 0)
    print(f"Watermark1(top-right): {'FOUND' if wm1 else 'MISSED'}")
    print(f"Watermark2(bottom-left): {'FOUND' if wm2 else 'MISSED'}")
else:
    print("Auto detect found NOTHING - testing individual strategies...")
    from processors.auto_detect import _corner_watermark_detect, _brightness_anomaly_detect, _text_detect
    for name, fn in [("corner", _corner_watermark_detect), ("anomaly", _brightness_anomaly_detect), ("text", _text_detect)]:
        m = fn(img)
        p = np.sum(m > 0)
        print(f"  {name}: {p} pixels")
