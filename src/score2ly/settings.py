from dataclasses import dataclass

from score2ly.image_processing import BlockMethod, SheetMethod
from score2ly.pdf import PdfKind
from score2ly.utils import APIKey


@dataclass(frozen=True, slots=True)
class ConvertSettings:
    # PDF type
    pdf_kind: PdfKind = PdfKind.AUTO

    # Image preprocessing (for scans)
    sheet_method: SheetMethod = SheetMethod.NONE
    block_method: BlockMethod = BlockMethod.NONE
    background_normalize: bool = False
    background_normalize_kernel: float = 0.1
    trunc_threshold: bool = False
    trunc_threshold_value: int = 200
    gamma_correction: bool = False
    gamma: float = 2.0
    deskew: bool = False
    tight_crop: bool = False
    clahe: bool = False
    projection_k: float = 1.5
    projection_denoise: bool = False

    # Page range to extract (1-indexed start/end, inclusive; None means all pages)
    page_range: tuple[int, int] | None = None

    # Score info (CLI overrides for interactive prompts)
    title: str = ""
    subtitle: str = ""
    composer: str = ""
    work_number: str = ""
    copyright: str = ""
    tagline: str = ""
    no_prompt: bool = False

    def preprocessing_is_noop(self) -> bool:
        return (
            self.sheet_method is SheetMethod.NONE
            and self.block_method is BlockMethod.NONE
            and not self.background_normalize
            and not self.trunc_threshold
            and not self.gamma_correction
            and not self.deskew
            and not self.tight_crop
            and not self.clahe
        )


DEFAULT_MAX_RETRIES = 2


@dataclass(frozen=True, slots=True)
class FixSettings:
    # LLM parameters (CLI overrides for interactive prompts)
    model: str = ""
    api_key: APIKey = APIKey("")
    max_retries: int | None = None
