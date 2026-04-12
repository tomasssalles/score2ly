from collections.abc import Sequence
from logging import getLogger
from pathlib import Path

from score2ly import new_pipeline
from score2ly.pipeline_common import run_stage, StageParams
from score2ly.settings import FixSettings

logger = getLogger(__name__)


def run(output_dir: Path, settings: FixSettings) -> None:
    new_pipeline_stage_params = new_pipeline.get_stage_params(None, None)
    stage_params: Sequence[StageParams[FixSettings]] = ()

    for stage_idx, params in enumerate(stage_params, start=len(new_pipeline_stage_params) + 1):
        run_stage(params, output_dir, settings, stage_idx, logger)

    logger.info("Fix pipeline finished successfully.")
