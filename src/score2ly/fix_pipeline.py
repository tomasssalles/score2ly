import logging
from collections.abc import Sequence
from pathlib import Path

from score2ly import convert_pipeline
from score2ly.pipeline_common import run_stage, StageParams
from score2ly.settings import FixSettings, ConvertSettings

logger = logging.getLogger(__name__)


def _verify_convert_pipeline(stage_params: Sequence[StageParams[ConvertSettings]]) -> None:
    logger.info("Verifying stages 1 to %d have been completed...", len(stage_params))

    null_logger = logging.getLogger("_verify_convert_pipeline_null_logger")
    null_logger.setLevel(logging.CRITICAL + 1)

    for stage_idx, params in enumerate(stage_params, start=1):
        pass  # TODO: Essentially want to call pipeline_common.should_run and check that it returns False. But need to clean up code e.g. dependencies_to_outputs

    logger.info("First %d stages are already done. Moving on to fixing pipeline.", len(stage_params))


def run(output_dir: Path, settings: FixSettings) -> None:
    conv_pipeline_stage_params = convert_pipeline.get_stage_params(None, None)
    _verify_convert_pipeline(conv_pipeline_stage_params)

    stage_params: Sequence[StageParams[FixSettings]] = ()

    for stage_idx, params in enumerate(stage_params, start=len(conv_pipeline_stage_params) + 1):
        run_stage(params, output_dir, settings, stage_idx, logger)

    logger.info("Fixing pipeline finished successfully.")
