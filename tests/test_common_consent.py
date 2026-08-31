"""
Tests for ppxai/common/consent.py

Tests the ConsentManager and SyncConsentManager classes.
"""

import pytest

from ppxai.common.consent import ConsentManager, ConsentRequest, SyncConsentManager
from ppxai.constants import ConsentDecision


@pytest.mark.asyncio
async def test_consent_manager_always_approve():
    """Test that 'always' decision approves all subsequent requests."""
    async def mock_callback(request):
        return (True, "always")

    manager = ConsentManager(consent_callback=mock_callback)

    # First request returns always
    approved1 = await manager.request_consent("/path/file1.py")
    assert approved1 is True

    # Subsequent requests should be auto-approved without callback
    approved2 = await manager.request_consent("/path/file2.py")
    assert approved2 is True


@pytest.mark.asyncio
async def test_consent_manager_never_approve():
    """Test that 'never' decision denies all subsequent requests."""
    async def mock_callback(request):
        return (False, "never")

    manager = ConsentManager(consent_callback=mock_callback)

    approved1 = await manager.request_consent("/path/file1.py")
    assert approved1 is False

    # Subsequent requests should be auto-denied
    approved2 = await manager.request_consent("/path/file2.py")
    assert approved2 is False


@pytest.mark.asyncio
async def test_consent_manager_yes_per_file():
    """Test that 'yes' decision approves only that specific file."""
    call_count = [0]

    async def mock_callback(request):
        call_count[0] += 1
        if request.file_path == "/path/file1.py":
            return (True, "yes")
        return (False, "no")

    manager = ConsentManager(consent_callback=mock_callback)

    # Approve file1
    approved1 = await manager.request_consent("/path/file1.py")
    assert approved1 is True
    assert call_count[0] == 1

    # Request file1 again - should be cached, no callback
    approved1_again = await manager.request_consent("/path/file1.py")
    assert approved1_again is True
    assert call_count[0] == 1  # No additional callback

    # Request file2 - should prompt
    approved2 = await manager.request_consent("/path/file2.py")
    assert approved2 is False
    assert call_count[0] == 2


@pytest.mark.asyncio
async def test_consent_manager_no_per_file():
    """Test that 'no' decision denies only that specific file."""
    call_count = [0]

    async def mock_callback(request):
        call_count[0] += 1
        if request.file_path == "/path/denied.py":
            return (False, "no")
        return (True, "yes")

    manager = ConsentManager(consent_callback=mock_callback)

    # Deny denied.py
    approved1 = await manager.request_consent("/path/denied.py")
    assert approved1 is False

    # Request it again - should be cached
    approved1_again = await manager.request_consent("/path/denied.py")
    assert approved1_again is False
    assert call_count[0] == 1  # Cached, no callback

    # Approve different file
    approved2 = await manager.request_consent("/path/allowed.py")
    assert approved2 is True


@pytest.mark.asyncio
async def test_consent_manager_no_callback():
    """Test that manager denies when no callback provided (safe default)."""
    manager = ConsentManager()  # No callback

    approved = await manager.request_consent("/path/file.py")
    assert approved is False


@pytest.mark.asyncio
async def test_consent_manager_reset():
    """Test that reset clears all decisions."""
    async def mock_callback(request):
        return (True, "always")

    manager = ConsentManager(consent_callback=mock_callback)

    await manager.request_consent("/path/file.py")
    assert manager._always_approve is True

    manager.reset()

    assert manager._always_approve is False
    assert len(manager._approved_files) == 0


@pytest.mark.asyncio
async def test_consent_manager_get_status():
    """Test get_status returns current state."""
    async def mock_callback(request):
        return (True, "yes")

    manager = ConsentManager(consent_callback=mock_callback)

    status1 = manager.get_status()
    assert status1["file_mode"] == "prompt"
    assert status1["shell_mode"] == "prompt"

    await manager.request_consent("/path/file.py")

    status2 = manager.get_status()
    assert status2["approved_files"] == 1


@pytest.mark.asyncio
async def test_consent_manager_is_file_approved():
    """Test is_file_approved check without prompting."""
    async def mock_callback(request):
        return (True, "yes")

    manager = ConsentManager(consent_callback=mock_callback)

    # Not approved yet
    assert manager.is_file_approved("/path/file.py") is False

    # Approve it
    await manager.request_consent("/path/file.py")

    # Now should be approved
    assert manager.is_file_approved("/path/file.py") is True


def test_sync_consent_manager_yes():
    """Test synchronous consent manager with 'yes' decision."""
    def mock_callback(request):
        return (True, "yes")

    manager = SyncConsentManager(consent_callback=mock_callback)

    approved = manager.request_consent("/path/file.py")
    assert approved is True


def test_sync_consent_manager_always():
    """Test synchronous consent manager with 'always' decision."""
    def mock_callback(request):
        return (True, "always")

    manager = SyncConsentManager(consent_callback=mock_callback)

    approved1 = manager.request_consent("/path/file1.py")
    assert approved1 is True

    # Should be auto-approved
    approved2 = manager.request_consent("/path/file2.py")
    assert approved2 is True


def test_sync_consent_manager_never():
    """Test synchronous consent manager with 'never' decision."""
    def mock_callback(request):
        return (False, "never")

    manager = SyncConsentManager(consent_callback=mock_callback)

    approved1 = manager.request_consent("/path/file1.py")
    assert approved1 is False

    approved2 = manager.request_consent("/path/file2.py")
    assert approved2 is False


def test_sync_consent_manager_no_callback():
    """Test synchronous manager denies without callback."""
    manager = SyncConsentManager()

    approved = manager.request_consent("/path/file.py")
    assert approved is False


def test_consent_request_dataclass():
    """Test ConsentRequest dataclass."""
    request = ConsentRequest(
        file_path="/path/to/file.py",
        operation="edit",
        tool_name="apply_patch"
    )

    assert request.file_path == "/path/to/file.py"
    assert request.operation == "edit"
    assert request.tool_name == "apply_patch"


def test_consent_decision_enum():
    """Test ConsentDecision enum values."""
    assert ConsentDecision.YES.value == "yes"
    assert ConsentDecision.NO.value == "no"
    assert ConsentDecision.ALWAYS.value == "always"
    assert ConsentDecision.NEVER.value == "never"
