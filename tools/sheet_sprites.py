"""Cut sprites out of the monster sheet with transparency rebuilt.

The sheet is a JPEG on black. A pixel is background when it is near black
AND connected to the sprite box's border through near-black pixels, so dark
outlines and shadows inside a monster stay opaque. Edges get a soft alpha
ramp from the luminance just above the threshold.
"""
import numpy as np
from PIL import Image
from scipy import ndimage

def cut(sheet_img, box, thr=34, pad=6):
    x0, y0, x1, y1 = box
    x0, y0 = max(0, x0 - pad), max(0, y0 - pad)
    x1, y1 = min(sheet_img.width, x1 + pad), min(sheet_img.height, y1 + pad)
    rgb = np.asarray(sheet_img.crop((x0, y0, x1, y1)).convert('RGB')).astype(np.float32)
    lum = rgb.max(axis=2)
    dark = lum <= thr
    lab, _ = ndimage.label(dark)
    border = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))) - {0}
    bg = np.isin(lab, list(border))
    alpha = np.where(bg, 0.0, 1.0)
    # soft edge: background-adjacent pixels ramp with brightness
    edge = ndimage.binary_dilation(bg, iterations=2) & ~bg
    ramp = np.clip((lum - thr * 0.5) / (thr * 1.5), 0, 1)
    alpha = np.where(edge, np.maximum(alpha * ramp, 0), alpha)
    alpha = ndimage.gaussian_filter(alpha, 0.6) * (~bg | edge)
    out = np.dstack([rgb, alpha * 255]).astype(np.uint8)
    im = Image.fromarray(out, 'RGBA')
    bb = im.getchannel('A').point(lambda v: 255 if v > 40 else 0).getbbox()
    return im.crop(bb) if bb else im
