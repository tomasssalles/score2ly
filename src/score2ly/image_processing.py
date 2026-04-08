import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

import cv2
import numpy as np

if TYPE_CHECKING:
    from PIL.Image import Image

logger = logging.getLogger(__name__)


class SheetMethod(str, Enum):
    NONE = "none"
    CC = "cc"
    FLOOD_FILL = "flood_fill"
    LARGEST_CONTOUR = "largest_contour"


class BlockMethod(str, Enum):
    NONE = "none"
    CONTOUR = "contour"
    PROJECTION = "projection"


@dataclass
class _DebugCtx:
    debug_dir: Path | None
    _step: int = field(default=0, init=False)

    def save(self, name: str, img: np.ndarray) -> None:
        if self.debug_dir is None:
            return
        self._step += 1
        filename = self.debug_dir / f"{self._step:02d}_{name}.png"
        cv2.imwrite(str(filename), img)
        logger.debug("saved debug image %s", filename.name)


def _to_bgr(gray: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


# --- Sheet isolation ---

def _crop_to_main_sheet_cc(gray: np.ndarray, ctx: _DebugCtx) -> np.ndarray:
    h, w = gray.shape
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    inv = 255 - bw

    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(inv, connectivity=8)
    logger.debug("[cc] image %dx%d, components: %d", w, h, num_labels - 1)

    page_idx = None
    max_area = 0
    for i in range(1, num_labels):
        x, y, ww, hh, area = stats[i]
        if area < 0.05 * w * h:
            continue
        touches_all = x == 0 and y == 0 and x + ww >= w and y + hh >= h
        if touches_all:
            logger.debug("[cc] component %d: skipped (touches all borders)", i)
            continue
        logger.debug("[cc] component %d: x=%d y=%d w=%d h=%d area=%.1f%%", i, x, y, ww, hh, area / (w * h) * 100)
        if area > max_area:
            max_area = area
            page_idx = i

    if ctx.debug_dir is not None:
        vis = _to_bgr(gray)
        for i in range(1, num_labels):
            x, y, ww, hh, area = stats[i]
            if area < 0.05 * w * h:
                continue
            color = (0, 255, 0) if i == page_idx else (0, 0, 255)
            cv2.rectangle(vis, (x, y), (x + ww, y + hh), color, 3)
        ctx.save("crop_to_main_sheet_cc_candidates", vis)

    if page_idx is None:
        logger.debug("[cc] no suitable component, returning full image")
        return gray

    x, y, ww, hh, _ = stats[page_idx]
    logger.debug("[cc] selected: x=%d y=%d w=%d h=%d", x, y, ww, hh)

    x0 = max(0, x)
    y0 = max(0, y)
    x1 = min(w, x + ww)
    y1 = min(h, y + hh)
    cropped = gray[y0:y1, x0:x1]
    ctx.save("crop_to_main_sheet_cc_result", cropped)
    return cropped


def _crop_to_main_sheet_flood_fill(gray: np.ndarray, ctx: _DebugCtx) -> np.ndarray:
    h, w = gray.shape
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    filled = bw.copy()
    ff_mask = np.zeros((h + 2, w + 2), np.uint8)

    filled_from = []
    for seed_x, seed_y in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]:
        if filled[seed_y, seed_x] == 0:
            cv2.floodFill(filled, ff_mask, (seed_x, seed_y), 128)
            filled_from.append((seed_x, seed_y))

    logger.debug("[flood_fill] filled from corners: %s", filled_from)

    page_mask = (filled == 255).astype(np.uint8)
    coords = np.column_stack(np.where(page_mask))

    if ctx.debug_dir is not None:
        vis = _to_bgr(gray)
        vis[filled == 128] = (0, 0, 80)
        vis[filled == 255] = (0, 80, 0)
        ctx.save("crop_to_main_sheet_flood_fill_mask", vis)

    if len(coords) == 0:
        logger.debug("[flood_fill] no page region found, returning full image")
        return gray

    y0, x0 = coords.min(axis=0)
    y1, x1 = coords.max(axis=0)
    logger.debug("[flood_fill] page bbox: x=%d..%d y=%d..%d", x0, x1, y0, y1)

    if ctx.debug_dir is not None:
        vis = _to_bgr(gray)
        cv2.rectangle(vis, (x0, y0), (x1, y1), (0, 255, 0), 3)
        ctx.save("crop_to_main_sheet_flood_fill_result_bbox", vis)

    cleaned = gray.copy()
    cleaned[filled == 128] = 255

    cropped = cleaned[y0:y1 + 1, x0:x1 + 1]
    ctx.save("crop_to_main_sheet_flood_fill_result", cropped)
    return cropped


def _crop_to_main_sheet_largest_contour(gray: np.ndarray, ctx: _DebugCtx) -> np.ndarray:
    h, w = gray.shape
    blur_size = max(51, min(w, h) // 8)
    if blur_size % 2 == 0:
        blur_size += 1
    blurred = cv2.GaussianBlur(gray, (blur_size, blur_size), 0)
    _, coarse = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    logger.debug("[largest_contour] blur kernel: %dx%d", blur_size, blur_size)

    ctx.save("crop_to_main_sheet_largest_contour_coarse", coarse)

    contours, _ = cv2.findContours(coarse, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    logger.debug("[largest_contour] image %dx%d, contours: %d", w, h, len(contours))

    vis = _to_bgr(gray) if ctx.debug_dir is not None else None
    best = None
    best_area = 0
    for cnt in contours:
        x, y, ww, hh = cv2.boundingRect(cnt)
        area = ww * hh
        touches_all = x == 0 and y == 0 and x + ww >= w and y + hh >= h
        if touches_all:
            logger.debug("[largest_contour] skipped (touches all borders): %dx%d", ww, hh)
            if vis is not None:
                cv2.rectangle(vis, (x, y), (x + ww, y + hh), (0, 0, 128), 1)
            continue
        logger.debug("[largest_contour] candidate: x=%d y=%d w=%d h=%d area=%.1f%%", x, y, ww, hh, area / (w * h) * 100)
        if vis is not None:
            cv2.rectangle(vis, (x, y), (x + ww, y + hh), (255, 165, 0), 2)
        if area > best_area:
            best_area = area
            best = (x, y, ww, hh)

    if best is None:
        logger.debug("[largest_contour] no suitable contour, returning full image")
        if vis is not None:
            ctx.save("crop_to_main_sheet_largest_contour_candidates", vis)
        return gray

    x, y, ww, hh = best
    logger.debug("[largest_contour] selected: x=%d y=%d w=%d h=%d (%.1f%%)", x, y, ww, hh, best_area / (w * h) * 100)
    if vis is not None:
        cv2.rectangle(vis, (x, y), (x + ww, y + hh), (0, 255, 0), 3)
        ctx.save("crop_to_main_sheet_largest_contour_candidates", vis)

    cropped = gray[y:y + hh + 1, x:x + ww + 1]
    ctx.save("crop_to_main_sheet_largest_contour_result", cropped)
    return cropped


# --- Music block detection ---

def _crop_to_music_block_contour(gray: np.ndarray, ctx: _DebugCtx) -> np.ndarray:
    h, w = gray.shape
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    _, bw = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    inv = 255 - bw

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    opened = cv2.morphologyEx(inv, cv2.MORPH_OPEN, kernel, iterations=1)

    contours, _ = cv2.findContours(opened, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    logger.debug("[block_contour] image %dx%d, contours: %d", w, h, len(contours))

    if not contours:
        return gray

    page_area = h * w
    cy_page, cx_page = h / 2.0, w / 2.0
    candidate = None
    candidate_score = -1
    vis = _to_bgr(gray) if ctx.debug_dir is not None else None

    for cnt in contours:
        x, y, ww, hh = cv2.boundingRect(cnt)
        area = ww * hh
        aspect = ww / float(hh)
        frac = area / page_area
        dist2 = ((x + ww / 2.0) - cx_page) ** 2 + ((y + hh / 2.0) - cy_page) ** 2
        score = area - 0.5 * dist2

        if area < 0.1 * page_area or area > 0.95 * page_area or aspect < 0.3 or aspect > 3.0:
            if vis is not None and area > 0.05 * page_area:
                cv2.rectangle(vis, (x, y), (x + ww, y + hh), (0, 0, 128), 1)
            continue

        logger.debug("[block_contour] candidate: x=%d y=%d w=%d h=%d area=%.1f%% aspect=%.2f", x, y, ww, hh, frac * 100, aspect)
        if vis is not None:
            cv2.rectangle(vis, (x, y), (x + ww, y + hh), (255, 165, 0), 2)
        if score > candidate_score:
            candidate_score = score
            candidate = (x, y, ww, hh)

    if candidate is None:
        logger.debug("[block_contour] no suitable contour, returning full image")
        if vis is not None:
            ctx.save("crop_to_music_block_contour_candidates", vis)
        return gray

    x, y, ww, hh = candidate
    logger.debug("[block_contour] selected: x=%d y=%d w=%d h=%d", x, y, ww, hh)
    if vis is not None:
        cv2.rectangle(vis, (x, y), (x + ww, y + hh), (0, 255, 0), 3)
        ctx.save("crop_to_music_block_contour_candidates", vis)

    shrink_x = int(0.01 * w)
    shrink_y = int(0.01 * h)
    x0 = max(0, x + shrink_x)
    y0 = max(0, y + shrink_y)
    x1 = min(w, x + ww - shrink_x)
    y1 = min(h, y + hh - shrink_y)

    if x1 <= x0 or y1 <= y0:
        return gray

    cropped = gray[y0:y1, x0:x1]
    ctx.save("crop_to_music_block_contour_result", cropped)
    return cropped


def _find_gap_inward(proj: np.ndarray, start: int, stop: int, direction: int, min_ink: int) -> int:
    total = abs(stop - start)
    min_travel = int(0.05 * total)
    in_gap = False
    traveled = 0
    for i in range(start, stop, direction):
        traveled += 1
        if traveled < min_travel:
            continue
        if proj[i] < min_ink:
            in_gap = True
        elif in_gap:
            return i
    return start


def _draw_projections(h_proj: np.ndarray, v_proj: np.ndarray, h: int, w: int, min_ink: int) -> np.ndarray:
    bar_w = 200
    canvas = np.ones((h + bar_w, w + bar_w, 3), dtype=np.uint8) * 240
    h_max = max(h_proj.max(), 1)
    for row, val in enumerate(h_proj):
        bar_len = int(val / h_max * (bar_w - 10))
        color = (0, 180, 0) if val >= min_ink else (180, 0, 0)
        cv2.line(canvas, (0, row), (bar_len, row), color, 1)
    v_max = max(v_proj.max(), 1)
    for col, val in enumerate(v_proj):
        bar_len = int(val / v_max * (bar_w - 10))
        color = (0, 180, 0) if val >= min_ink else (180, 0, 0)
        cv2.line(canvas, (bar_w + col, h), (bar_w + col, h + bar_len), color, 1)
    return canvas


def _crop_to_music_block_projection(gray: np.ndarray, ctx: _DebugCtx, k: float, denoise: bool) -> np.ndarray:
    h, w = gray.shape
    page_pixels = gray[gray < 255].astype(np.float32)
    mean, std = float(page_pixels.mean()), float(page_pixels.std())
    thresh_val = int(mean - k * std)
    _, bw = cv2.threshold(gray, thresh_val, 255, cv2.THRESH_BINARY)
    inv = 255 - bw
    logger.debug("[block_projection] mean=%.1f std=%.1f k=%s thresh_val=%d ink_before=%d",
                 mean, std, k, thresh_val, int(inv.sum() / 255))
    ctx.save("projection_inv_before_denoise", inv)

    if denoise:
        denoise_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        inv = cv2.morphologyEx(inv, cv2.MORPH_OPEN, denoise_kernel, iterations=1)
        logger.debug("[block_projection] ink_after_denoise=%d", int(inv.sum() / 255))
        ctx.save("projection_inv_after_denoise", inv)

    h_proj = inv.sum(axis=1) / 255.0
    v_proj = inv.sum(axis=0) / 255.0
    min_ink = max(10, min(h, w) // 50)
    logger.debug("[block_projection] min_ink=%d image=%dx%d", min_ink, w, h)

    content_rows = np.where(h_proj >= min_ink)[0]
    content_cols = np.where(v_proj >= min_ink)[0]

    if len(content_rows) == 0 or len(content_cols) == 0:
        logger.debug("[block_projection] no content found, returning full image")
        return gray

    outer_y0, outer_y1 = int(content_rows[0]), int(content_rows[-1])
    outer_x0, outer_x1 = int(content_cols[0]), int(content_cols[-1])
    logger.debug("[block_projection] outer bbox: x=%d..%d y=%d..%d", outer_x0, outer_x1, outer_y0, outer_y1)

    inner_y0 = _find_gap_inward(h_proj, outer_y0, outer_y1, 1, min_ink)
    inner_y1 = _find_gap_inward(h_proj, outer_y1, outer_y0, -1, min_ink)
    inner_x0 = _find_gap_inward(v_proj, outer_x0, outer_x1, 1, min_ink)
    inner_x1 = _find_gap_inward(v_proj, outer_x1, outer_x0, -1, min_ink)

    if (inner_y0, inner_y1, inner_x0, inner_x1) != (outer_y0, outer_y1, outer_x0, outer_x1):
        logger.debug("[block_projection] inner bbox (border stripped): x=%d..%d y=%d..%d", inner_x0, inner_x1, inner_y0, inner_y1)
    else:
        logger.debug("[block_projection] no inner gap found, using outer bbox")

    if ctx.debug_dir is not None:
        vis = _to_bgr(gray)
        cv2.rectangle(vis, (outer_x0, outer_y0), (outer_x1, outer_y1), (0, 0, 255), 2)
        cv2.rectangle(vis, (inner_x0, inner_y0), (inner_x1, inner_y1), (0, 255, 0), 3)
        ctx.save("crop_to_music_block_projection_profiles", _draw_projections(h_proj, v_proj, h, w, min_ink))
        ctx.save("crop_to_music_block_projection_bbox", vis)

    margin = int(0.005 * max(w, h))
    x0 = max(0, inner_x0 - margin)
    y0 = max(0, inner_y0 - margin)
    x1 = min(w - 1, inner_x1 + margin)
    y1 = min(h - 1, inner_y1 + margin)

    cropped = gray[y0:y1 + 1, x0:x1 + 1]
    ctx.save("crop_to_music_block_projection_result", cropped)
    return cropped


# --- Deskew ---

def _deskew_staff_based(gray: np.ndarray, ctx: _DebugCtx) -> tuple[np.ndarray, float, str]:
    h, w = gray.shape
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    inv = 255 - bw

    kernel_len = max(40, w // 12)
    horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_len, 1))
    detected = cv2.morphologyEx(inv, cv2.MORPH_OPEN, horizontal_kernel, iterations=1)

    lines = cv2.HoughLinesP(detected, rho=1, theta=np.pi / 1800.0, threshold=100,
                             minLineLength=kernel_len, maxLineGap=10)

    angles = []
    vis = _to_bgr(gray) if ctx.debug_dir is not None else None

    if lines is not None:
        for line in lines:
            x1, y1, x2, y2 = line[0]
            dx = x2 - x1
            if dx == 0:
                continue
            angle = np.degrees(np.arctan2(y2 - y1, dx))
            if -5.0 < angle < 5.0:
                angles.append(angle)
                if vis is not None:
                    cv2.line(vis, (x1, y1), (x2, y2), (0, 255, 0), 1)
            elif vis is not None:
                cv2.line(vis, (x1, y1), (x2, y2), (0, 0, 128), 1)

    logger.debug("[deskew] kernel_len=%d lines=%d near-horizontal=%d",
                 kernel_len, len(lines) if lines is not None else 0, len(angles))

    if len(angles) >= 5:
        median_angle = float(np.median(angles))
        angle_to_rotate = -median_angle
        method_used = "staff"
        logger.debug("[deskew] method=staff median=%.3f° rotating by %.3f°", median_angle, angle_to_rotate)
    else:
        coords = np.column_stack(np.where(bw < 255))
        if coords.size == 0:
            return gray, 0.0, "none"
        rect = cv2.minAreaRect(coords)
        angle = rect[-1]
        angle_to_rotate = -(90 + angle) if angle < -45 else -angle
        method_used = "rect"
        logger.debug("[deskew] method=rect (fallback) angle_to_rotate=%.3f°", angle_to_rotate)

    if vis is not None:
        ctx.save("deskew_lines", vis)

    if abs(angle_to_rotate) < 0.1:
        logger.debug("[deskew] angle < 0.1°, skipping rotation")
        ctx.save("deskew_result", gray)
        return gray, angle_to_rotate, method_used

    center = (w // 2, h // 2)
    M = cv2.getRotationMatrix2D(center, angle_to_rotate, 1.0)
    rotated = cv2.warpAffine(gray, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    ctx.save("deskew_result", rotated)
    return rotated, angle_to_rotate, method_used


# --- Tight crop ---

def _tight_crop(gray: np.ndarray, ctx: _DebugCtx) -> np.ndarray:
    h, w = gray.shape
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    coords = np.column_stack(np.where(bw < 255))
    if coords.size == 0:
        return gray

    y0, x0 = coords.min(axis=0)
    y1, x1 = coords.max(axis=0) + 1

    margin = int(0.01 * max(w, h))
    x0 = max(0, x0 - margin)
    y0 = max(0, y0 - margin)
    x1 = min(w, x1 + margin)
    y1 = min(h, y1 + margin)

    logger.debug("[tight_crop] bbox: x=%d..%d y=%d..%d (image was %dx%d)", x0, x1, y0, y1, w, h)

    if ctx.debug_dir is not None:
        vis = _to_bgr(gray)
        cv2.rectangle(vis, (x0, y0), (x1, y1), (0, 255, 0), 3)
        ctx.save("tight_crop_bbox", vis)

    cropped = gray[y0:y1, x0:x1]
    ctx.save("tight_crop_result", cropped)
    return cropped


# --- CLAHE ---

def _enhance_contrast(gray: np.ndarray) -> np.ndarray:
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return clahe.apply(gray)


# --- Public API ---

def process_page(
    gray: np.ndarray,
    *,
    sheet_method: SheetMethod,
    block_method: BlockMethod,
    deskew: bool,
    tight_crop: bool,
    clahe: bool,
    projection_k: float,
    projection_denoise: bool,
    debug_dir: Path | None,
) -> np.ndarray:
    ctx = _DebugCtx(debug_dir)
    ctx.save("input_grayscale", gray)

    step = gray

    if sheet_method is not SheetMethod.NONE:
        logger.info("  step 1: crop to main sheet [%s]", sheet_method.value)
        if sheet_method is SheetMethod.CC:
            step = _crop_to_main_sheet_cc(step, ctx)
        elif sheet_method is SheetMethod.FLOOD_FILL:
            step = _crop_to_main_sheet_flood_fill(step, ctx)
        elif sheet_method is SheetMethod.LARGEST_CONTOUR:
            step = _crop_to_main_sheet_largest_contour(step, ctx)

    if block_method is not BlockMethod.NONE:
        logger.info("  step 2: crop to music block [%s]", block_method.value)
        if block_method is BlockMethod.CONTOUR:
            step = _crop_to_music_block_contour(step, ctx)
        elif block_method is BlockMethod.PROJECTION:
            step = _crop_to_music_block_projection(step, ctx, k=projection_k, denoise=projection_denoise)

    if deskew:
        logger.info("  step 3: deskew")
        step, angle, method = _deskew_staff_based(step, ctx)
        logger.info("  deskew: %.3f° (%s)", angle, method)

    if tight_crop:
        logger.info("  step 4: tight crop")
        step = _tight_crop(step, ctx)

    if clahe:
        logger.info("  step 5: enhance contrast (CLAHE)")
        step = _enhance_contrast(step)

    ctx.save("final", step)
    return step


CROP_PADDING = 0.02


def crop_and_save(img: "Image", bounds: dict, dest: Path) -> None:
    pad = round(img.width * CROP_PADDING)
    x = max(0, bounds["x"] - pad)
    y = max(0, bounds["y"] - pad)
    right = min(img.width, bounds["x"] + bounds["width"] + pad)
    bottom = min(img.height, bounds["y"] + bounds["height"] + pad)
    img.crop((x, y, right, bottom)).save(dest)
