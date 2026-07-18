from pathlib import Path
import sys

from travel_agent.services import audio_service


def test_ffmpeg_binary_uses_bundled_imageio_binary_when_system_binary_is_missing(monkeypatch, tmp_path):
    bundled_ffmpeg = tmp_path / 'ffmpeg'
    bundled_ffmpeg.write_text('binary')

    class FakeImageioFfmpeg:
        @staticmethod
        def get_ffmpeg_exe() -> str:
            return str(bundled_ffmpeg)

    def fake_exists(path: Path) -> bool:
        return path == bundled_ffmpeg

    monkeypatch.setattr(audio_service.settings, 'ffmpeg_path', '')
    monkeypatch.setattr(audio_service.Path, 'exists', fake_exists)
    monkeypatch.setitem(sys.modules, 'imageio_ffmpeg', FakeImageioFfmpeg)

    assert audio_service.ffmpeg_binary() == str(bundled_ffmpeg)
