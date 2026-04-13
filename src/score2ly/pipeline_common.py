import shutil
import time
from collections.abc import Sequence, Iterable
from dataclasses import dataclass
from logging import Logger
from pathlib import Path
from typing import Protocol

from score2ly import metadata
from score2ly.stages import Stage
from score2ly.utils import relative


class StageFn[SettingsT](Protocol):
    def __call__(
        self,
        stage_output_dir: Path,
        settings: SettingsT,
        dependencies_to_outputs: dict[Stage, Sequence[Path]],
        stage_idx: int,
    ) -> Iterable[Path]: ...


@dataclass(frozen=True, slots=True)
class StageParams[SettingsT]:
    stage: Stage
    description: str
    output_dir_name: str
    dependencies: Sequence[Stage]
    fn: StageFn[SettingsT]


def get_dependencies_to_outputs(
    stage_idx: int,
    dependencies: Sequence[Stage],
    stages_meta: dict[Stage, dict],
) -> dict[Stage, Sequence[Path]]:
    result = {}
    for dep in dependencies:
        dep_meta = stages_meta.get(dep)
        if (not dep_meta) or (not (dep_outputs := dep_meta.get("outputs"))):
            raise RuntimeError(f"Stage {stage_idx}: Dependency stage {dep.value!r} has not completed. Aborting...")
        result[dep] = tuple(Path(s) for s in dep_outputs)

    return result


def should_run(
    stage_idx: int,
    dependencies: Sequence[Stage],
    stage_meta: dict | None,
    pipeline_output_dir: Path,
    dependencies_to_outputs: dict[Stage, Sequence[Path]],
    logger: Logger,
) -> bool:
    if not stage_meta:
        logger.info("Stage %d: No metadata yet. Running.", stage_idx)
        return True

    stage_outputs: Sequence[str] | None = stage_meta.get("outputs")
    if not stage_outputs:
        logger.info("Stage %d: No outputs in metadata. Running.", stage_idx)
        return True

    for out in stage_outputs:
        if not (pipeline_output_dir / out).exists():
            logger.info("Stage %d: Missing expected output file %s. Running.", stage_idx, out)
            return True

    source_checksums: dict[str, str] | None = stage_meta.get("source_checksums")
    if dependencies and (not source_checksums):
        logger.info("Stage %d: Stage has dependencies but no source checksums in metadata. Running.", stage_idx)
        return True

    if source_checksums is None:
        source_checksums = {}

    updated_sources = {
        str(dep_out)
        for dep_outputs in dependencies_to_outputs.values()
        for dep_out in dep_outputs
    }
    if updated_sources != set(source_checksums.keys()):
        logger.info(
            "Stage %d: Dependencies listed in metadata do not match current dependencies. Running.",
            stage_idx,
        )
        return True

    for src, cs in source_checksums.items():
        src_p = pipeline_output_dir / src
        if metadata.checksum(src_p) != cs:
            logger.info("Stage %d: Dependency %s has been externally modified. Running.", stage_idx, src)
            return True

    logger.info("Stage %d: Already done. Skipping.", stage_idx)
    return False


def run_stage[SettingsT](
    params: StageParams[SettingsT],
    pipeline_output_dir: Path,
    settings: SettingsT,
    stage_idx: int,
    logger: Logger,
) -> None:
    logger.info("* Stage %d: %s", stage_idx, params.description)

    stages_meta = metadata.get_stages(pipeline_output_dir)
    dependencies_to_outputs = get_dependencies_to_outputs(stage_idx, params.dependencies, stages_meta)
    stage_meta = stages_meta.get(params.stage)

    if not should_run(
        stage_idx, params.dependencies, stage_meta, pipeline_output_dir, dependencies_to_outputs, logger
    ):
        return

    stage_output_dir = pipeline_output_dir / f"{stage_idx:02d}.{params.output_dir_name}"
    if stage_output_dir.exists():
        shutil.rmtree(stage_output_dir)
    stage_output_dir.mkdir(parents=True)

    source_checksums = {
        str(dep_out_rel_p): metadata.checksum(pipeline_output_dir / dep_out_rel_p)
        for dep_outputs in dependencies_to_outputs.values()
        for dep_out_rel_p in dep_outputs
    }

    t0 = time.monotonic()
    stage_outputs = tuple(
        params.fn(stage_output_dir, settings, dependencies_to_outputs, stage_idx)
    )
    elapsed = time.monotonic() - t0

    metadata.update_stage(pipeline_output_dir, params.stage, {
        "description": params.description,
        "outputs": [str(relative(out, pipeline_output_dir)) for out in stage_outputs],
        "source_checksums": source_checksums,
    })
    if elapsed >= 1.0:
        logger.info("Stage %d: Done (%.0fs).", stage_idx, elapsed)
    else:
        logger.info("Stage %d: Done.", stage_idx)
