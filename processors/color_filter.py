
import cv2
import numpy as np


def remove_by_color(
    image: np.ndarray,
    lower_color: list,
    upper_color: list,
    inpaint_radius: int = 3
) -> np.ndarray:
    lower = np.array(lower_color, dtype=np.uint8)
    upper = np.array(upper_color, dtype=np.uint8)
    mask = cv2.inRange(image, lower, upper)
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    mask = cv2.dilate(mask, kernel, iterations=1)
    result = cv2.inpaint(image, mask, inpaint_radius, cv2.INPAINT_TELEA)
    return result


def remove_alpha_watermark(image: np.ndarray, alpha_threshold: int = 200) -> np.ndarray:
    if len(image.shape) == 2 or image.shape[2] < 3:
        return image
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    _, mask = cv2.threshold(gray, alpha_threshold, 255, cv2.THRESH_BINARY)
    bg_mask = cv2.bitwise_not(mask)
    bg_mean = cv2.mean(image, bg_mask)[:3]
    result = image.copy().astype(np.float32)
    for c in range(3):
        channel = result[:, :, c]
        alpha = gray.astype(np.float32) / 255.0
        channel = channel * (1 - alpha * 0.3) + bg_mean[c] * alpha * 0.3
        result[:, :, c] = np.clip(channel, 0, 255)
    return result.astype(np.uint8)
