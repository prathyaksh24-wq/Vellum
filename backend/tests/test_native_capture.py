from pathlib import Path

from agent.computer_use.native_windows import capture


class FakeImage:
    def __init__(self):
        self.saved_to = None

    def save(self, path):
        self.saved_to = Path(path)
        Path(path).write_bytes(b"fake-png")


def test_screenshot_filename_is_sanitized(tmp_path):
    fake = FakeImage()

    result = capture.save_window_screenshot(
        100,
        screenshot_dir=tmp_path,
        filename="../bad name.png",
        image_factory=lambda hwnd: fake,
    )

    assert result["path"].endswith("bad_name.png")
    assert fake.saved_to.name == "bad_name.png"


def test_default_screenshot_filename_mentions_hwnd(tmp_path):
    fake = FakeImage()

    result = capture.save_window_screenshot(
        100,
        screenshot_dir=tmp_path,
        image_factory=lambda hwnd: fake,
    )

    assert "window-100-" in Path(result["path"]).name
    assert result["hwnd"] == 100
