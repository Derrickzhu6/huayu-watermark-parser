
import cv2
import numpy as np


def frequency_filter(image: np.ndarray, sigma: float = 30.0) -> np.ndarray:
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image.copy()

    f = np.fft.fft2(gray.astype(np.float32))
    fshift = np.fft.fftshift(f)
    rows, cols = gray.shape
    crow, ccol = rows // 2, cols // 2
    x = np.arange(cols) - ccol
    y = np.arange(rows) - crow
    xx, yy = np.meshgrid(x, y)
    dist = np.sqrt(xx**2 + yy**2)
    mask_high = 1.0 - np.exp(-(dist**2) / (2 * sigma**2))
    fshift_filtered = fshift * mask_high
    f_ishift = np.fft.ifftshift(fshift_filtered)
    img_back = np.fft.ifft2(f_ishift)
    img_back = np.abs(img_back)
    img_back = cv2.normalize(img_back, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    if len(image.shape) == 3:
        return cv2.cvtColor(img_back, cv2.COLOR_GRAY2BGR)
    return img_back


def text_watermark_removal(image: np.ndarray, threshold: int = 40) -> np.ndarray:
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image.copy()
    _, mask = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.dilate(mask, kernel, iterations=1)
    result = cv2.inpaint(image, mask, 3, cv2.INPAINT_TELEA)
    return result
