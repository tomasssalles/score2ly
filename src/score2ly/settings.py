from dataclasses import dataclass
from typing import Literal


@dataclass
class ConvertSettings:
    # PDF type
    pdf_kind: Literal["auto", "vector", "scan"] = "auto"
    skip_image_preprocessing: bool = False

    # Image preprocessing (for scans)
    sheet_method: Literal["cc", "flood_fill", "largest_contour", "none"] = "flood_fill"
    block_method: Literal["contour", "projection", "none"] = "projection"
    clahe: bool = True
    projection_k: float = 0.3
    projection_denoise: bool = False