"""
Consent operations — file edit and shell command consent management.

Extracted from engine/client.py (v1.17.1) to reduce EngineClient size.
All functions take an engine reference as first parameter.
"""

from pathlib import Path

from .types import Event, EventType
from ..common.logger import get_logger
from ..common.consent import classify_shell_command
from ..constants import ConsentMode, ConsentResponse, ShellRiskLevel

logger = get_logger("tui")


async def request_file_edit_consent(engine, file_path: str) -> bool:
    """Request user consent for editing a file.

    Manages the consent flow:
    1. Check if consent mode is "always" or "never"
    2. Check if file already allowed
    3. If needed, call consent_callback to ask user
    4. Update session state based on response
    5. Create checkpoint before first file edit in agent mode

    Args:
        file_path: Path to file that needs editing

    Returns:
        True if edit is allowed, False otherwise
    """
    path = Path(file_path).resolve()

    # Create checkpoint before first file edit in agent mode
    if engine._agent_mode and engine._checkpoint_manager and not engine.session.allowed_files:
        filename = path.name
        engine.create_checkpoint(f"Before editing {filename}")

    # Check global consent mode
    if engine.session.edit_consent_mode == ConsentMode.ALWAYS:
        return True
    if engine.session.edit_consent_mode == ConsentMode.NEVER:
        return False

    # Check if already consented for this file
    if path in engine.session.allowed_files:
        return True

    # If no callback, default to allow (backward compatible)
    if engine.consent_callback is None:
        return True

    # Request consent from user via callback
    try:
        consent_event = Event(
            type=EventType.CONSENT_REQUEST,
            data={"file_path": str(path)},
            metadata={"file_path": str(path)}
        )
        engine.enqueue_event(consent_event)
        logger.debug(f"Consent: queued consent_request event for {path}")

        logger.debug(f"Consent: calling callback for {path}")
        approved, response = await engine.consent_callback(str(path))
        logger.debug(f"Consent: callback returned approved={approved} response={response}")

        if response == ConsentResponse.YES:
            engine.session.allowed_files.add(path)
            return True
        elif response == ConsentResponse.ALWAYS:
            engine.session.edit_consent_mode = ConsentMode.ALWAYS
            logger.debug("Consent: set edit_consent_mode to ALWAYS")
            return True
        elif response == ConsentResponse.NEVER:
            engine.session.edit_consent_mode = ConsentMode.NEVER
            return False
        else:
            return False

    except Exception as e:
        logger.debug(f"Consent: callback EXCEPTION: {type(e).__name__}: {e}")
        logger.error(f"Consent callback error: {e}")
        return False


def classify_command(engine, command: str) -> str:
    """Classify shell command risk level.

    Args:
        command: Shell command to classify

    Returns:
        Risk level: ShellRiskLevel value (NEVER, DANGEROUS, or SAFE)
    """
    return classify_shell_command(command, engine._shell_config)


async def request_shell_consent(engine, command: str, working_dir: str = ".") -> bool:
    """Request user consent for shell command execution.

    Manages the shell consent flow:
    1. Classify command risk level (never/dangerous/safe)
    2. Block "never" commands immediately
    3. Allow "safe" commands without consent
    4. Request consent for "dangerous" commands
    5. Check session state (always/never modes)

    Args:
        command: Shell command to execute
        working_dir: Working directory for the command

    Returns:
        True if execution is allowed, False otherwise
    """
    risk_level = classify_command(engine, command)

    logger.debug(
        f"Shell consent: command='{command[:50]}...' risk={risk_level} "
        f"callback={engine.shell_consent_callback is not None}"
    )

    if risk_level == ShellRiskLevel.NEVER:
        return False

    if risk_level == ShellRiskLevel.SAFE:
        return True

    # Check global shell consent mode
    if engine.session.shell_consent_mode == ConsentMode.ALWAYS:
        return True
    if engine.session.shell_consent_mode == ConsentMode.NEVER:
        return False

    # Check if already consented for this specific command
    if command in engine.session.allowed_commands:
        return True

    # If no callback, default to deny (fail-safe)
    if engine.shell_consent_callback is None:
        return False

    try:
        logger.debug(f"Requesting shell consent for: {command[:50]}...")

        consent_event = Event(
            type=EventType.CONSENT_REQUEST,
            data={
                "command": command,
                "working_dir": working_dir,
                "risk_level": risk_level,
                "type": "shell"
            },
            metadata={"command": command, "type": "shell"}
        )
        engine.enqueue_event(consent_event)

        approved, response = await engine.shell_consent_callback(command, working_dir, risk_level)

        logger.debug(f"Shell consent response: approved={approved} response={response}")

        if response == ConsentResponse.YES:
            engine.session.allowed_commands.add(command)
            return True
        elif response == ConsentResponse.ALWAYS:
            engine.session.shell_consent_mode = ConsentMode.ALWAYS
            return True
        elif response == ConsentResponse.NEVER:
            engine.session.shell_consent_mode = ConsentMode.NEVER
            return False
        else:
            return False

    except Exception as e:
        logger.error(f"Shell consent callback error: {e}")
        return False
