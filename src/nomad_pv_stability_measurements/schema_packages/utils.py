from nomad.units import ureg


def _is_monitor_control(step) -> bool:
    # By `monitor`, not by `set_point`: a ramp has none, and a block has neither (§15.11).
    return 'monitor' in step.m_def.all_quantities


#: The kinds of step, as the prefixes of their class names — longest first, or
#: `HoldBelow…` would lose only its `Hold` and land on a quantity of its own (§17.5).
KIND_PREFIXES = ('HoldBelow', 'Hold', 'Ramp')


def _quantity_of(step) -> str:
    """The quantity a step speaks to: its class name without its kind prefix, so
    `HoldTemperature`, `RampTemperature` and `HoldBelowTemperature` are kinds of step on
    one quantity and contradict each other exactly as two holds do (§15.11, §17.5).

    The name is the whole rule. This module imports no schema class, so it reads the
    class itself, never a type it would have to import (§15.4).
    """
    name = type(step).__name__
    for prefix in KIND_PREFIXES:
        if name.startswith(prefix):
            return name.removeprefix(prefix)
    return name


def report_overlapping_steps(steps, mode: str, where: str, logger) -> None:

    by_quantity = {}
    for step in steps:
        if _is_monitor_control(step):
            by_quantity.setdefault(_quantity_of(step), []).append(step)

    for quantity, overlapping in by_quantity.items():
        if len(overlapping) <= 1:
            continue
        if mode == 'parallel':
            reason = 'a `parallel` block runs its steps at the same time'
        elif any(step.estimated_duration is None for step in overlapping):
            # A step without a duration is a condition and spans the whole block, so it
            # overlaps whatever else speaks to the quantity (D13).
            reason = "a step without an `estimated_duration` holds for the block's whole span"
        else:
            continue  # each has its own turn — genuinely subsequent
        logger.error(
            f'{len(overlapping)} {quantity} steps overlap in {where}: {reason}. '
            f'Siblings are not merged into one step — write one step with all the '
            f'keys, or give each its own `estimated_duration` in a sequential block.'
        )


def report_steps_that_never_run(steps, mode: str, duration, where: str, logger) -> None:

    if mode != 'sequential' or duration is None:
        return
    budget = duration.to('s').magnitude
    spent = 0.0
    for step in steps:
        if step.estimated_duration is None:
            continue
        if spent >= budget:
            logger.warning(
                f'{step.name or "<unnamed>"} never runs: the `estimated_duration` of '
                f'{where} is already spent by the steps before it.'
            )
        spent += step.estimated_duration.to('s').magnitude


def fit_steps_to_duration(steps, mode: str, duration, where: str, logger) -> None:

    if duration is None:
        return
    budget = duration.to('s').magnitude
    spent = 0.0
    for step in steps:
        if step.estimated_duration is None:
            continue
        length = step.estimated_duration.to('s').magnitude
        available = budget if mode == 'parallel' else budget - spent
        if 0 < available < length:
            logger.warning(
                f'{step.name or "<unnamed>"} is shortened from {length:g} s to '
                f'{available:g} s to fit the `estimated_duration` of {where}.'
            )
            step.estimated_duration = available * ureg.second
        spent += length


def derive_duration(steps, mode: str):

    lengths = [
        step.estimated_duration.to('s').magnitude
        for step in steps
        if step.estimated_duration is not None
    ]
    if not lengths:
        return None
    return (max(lengths) if mode == 'parallel' else sum(lengths)) * ureg.second


def check_steps(steps, mode: str, duration, where: str, logger) -> None:
    """R4, R5 and R6 over one run of `steps` against `duration`. A repeating block runs
    them against one iteration, never against all of them together (§15.8)."""
    report_overlapping_steps(steps, mode, where, logger)
    report_steps_that_never_run(steps, mode, duration, where, logger)
    fit_steps_to_duration(steps, mode, duration, where, logger)


def normalize_steps(section, mode: str, logger) -> None:

    where = section.name or '<unnamed>'
    duration = section.estimated_duration
    check_steps(section.steps, mode, duration, where, logger)
    if duration is None:
        derived = derive_duration(section.steps, mode)
        if derived is not None:
            section.estimated_duration = derived
