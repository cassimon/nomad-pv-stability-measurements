def _is_monitor_control(instruction) -> bool:
    # By `monitor`, not by `set_point`: a ramp has none, and a block has neither (§15.11).
    return 'monitor' in instruction.m_def.all_quantities


#: The kinds of instruction, as the prefixes of their class names — longest first, or
#: `HoldBelow…` would lose only its `Hold` and land on a quantity of its own (§17.5).
KIND_PREFIXES = ('HoldBetween', 'HoldBelow', 'Hold', 'Ramp')


def _quantity_of(instruction) -> str:
    """The quantity an instruction speaks to: its class name without its kind prefix, so
    `HoldTemperature`, `RampTemperature` and `HoldBelowTemperature` are kinds of
    instruction on one quantity and contradict each other exactly as two holds do
    (§15.11, §17.5).

    The name is the whole rule. This module imports no schema class, so it reads the
    class itself, never a type it would have to import (§15.4).
    """
    name = type(instruction).__name__
    for prefix in KIND_PREFIXES:
        if name.startswith(prefix):
            return name.removeprefix(prefix)
    return name


def report_overlapping_instructions(
    instructions, mode: str, where: str, logger
) -> None:
    """Two instructions on one quantity at the same time contradict each other: siblings
    are never merged. Only a `parallel` run puts them at the same time — one after
    another, each has its own turn."""
    if mode != 'parallel':
        return
    by_quantity = {}
    for instruction in instructions:
        if _is_monitor_control(instruction):
            by_quantity.setdefault(_quantity_of(instruction), []).append(instruction)
    for quantity, overlapping in by_quantity.items():
        if len(overlapping) <= 1:
            continue
        logger.error(
            f'{len(overlapping)} {quantity} instructions overlap in {where}: they run '
            f'at the same time. Siblings are not merged into one instruction — write one '
            f'instruction with all the keys, or run them one after another.'
        )


def report_instructions_that_never_run(
    instructions, mode: str, stop, where: str, logger
) -> None:
    """One after another, an instruction never starts once the ones before it never
    finish, or once they have used up `stop`, the time the run is stopped at."""
    if mode == 'parallel':
        return
    budget = None if stop is None else stop.to('s').magnitude
    spent = 0.0
    for instruction in instructions:
        if spent is None or (budget is not None and spent >= budget):
            logger.warning(
                f'{instruction.name or "<unnamed>"} never runs: the instructions before '
                f'it in {where} never finish, or are stopped first.'
            )
            continue
        if instruction.estimated_duration is None:
            spent = None
        else:
            spent += instruction.estimated_duration.to('s').magnitude


def check_instructions(instructions, mode: str, stop, where: str, logger) -> None:
    """R4 and R5 over one run of `instructions`, stopped at `stop` if that is not
    empty."""
    report_overlapping_instructions(instructions, mode, where, logger)
    report_instructions_that_never_run(instructions, mode, stop, where, logger)
