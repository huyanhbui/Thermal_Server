"""Test calibration module integration with server."""
import asyncio
from server import make_state
from calibrate import calibration_task


def test_calibration_task_can_be_imported():
    """Verify calibration_task can be imported by server.py."""
    import inspect
    assert inspect.iscoroutinefunction(calibration_task)


def test_server_app_creation_with_calibrate_mode(tmp_path):
    """Verify app creation with calibrate=True doesn't raise errors."""
    from server import create_app
    state = make_state(
        db_path=":memory:", calibrate=True,
        model_path=str(tmp_path / "model.pkl"),
        settings_path=str(tmp_path / "settings.json"),
        esg_path=str(tmp_path / "esg.json"),
    )
    app = create_app(state)
    assert app is not None
