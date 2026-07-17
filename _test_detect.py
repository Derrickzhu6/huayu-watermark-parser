import sys
sys.path.insert(0, r"C:\AI_Workspace\01_Projects\视频解析API")
import cv2, numpy as np
from pathlib import Path
from processors.auto_detect import auto_detect_watermark

buf = np.fromfile(str(Path(r"C:\AI_Workspace\01_Projects\视频解析API\uploads\test_upload.png")), dtype=np.uint8)
img = cv2.imdecode(buf, cv2.IMREAD_COLOR)

mask = auto_detect_watermark(img)
pixels = np.sum(mask > 0)
total = mask.shape[0] * mask.shape[1]
print(f"Detected: {pixels} pixels ({pixels/total*100:.1f}%)")

ys, xs = np.where(mask > 0)
if len(ys) > 0:
    print(f"Mask: y[{ys.min()}:{ys.max()}], x[{xs.min()}:{xs.max()}]")
    print(f"Watermark text spans x~290-550. Detected starts at x={xs.min()}")

# Save mask for visual inspection
cv2.imwrite(r"C:\AI_Workspace\01_Projects\视频解析API\results\_mask_fix.png", mask)
