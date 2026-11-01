"""User-writable Studio settings, independent of the install directory."""
from dataclasses import dataclass
from pathlib import Path
import json
import os
import sys


def data_root() -> Path:
    if os.environ.get("VISOMASTER_STUDIO_HOME"):
        return Path(os.environ["VISOMASTER_STUDIO_HOME"]).expanduser().resolve()
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "VisoMasterStudio"
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/VisoMasterStudio"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "visomaster-studio"


@dataclass
class Settings:
    model_dir: Path
    output_dir: Path

    @classmethod
    def load(cls, root: Path):
        defaults = cls(root / "models", Path.home() / "Videos/VisoMaster")
        try:
            data = json.loads((root / "settings.json").read_text(encoding="utf-8"))
            model = data.get("model_dir")
            output = data.get("output_dir")
            if isinstance(model, str) and Path(model).is_absolute():
                defaults.model_dir = Path(model)
            if isinstance(output, str) and Path(output).is_absolute():
                defaults.output_dir = Path(output)
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        return defaults

    def save(self, root: Path):
        root.mkdir(parents=True, exist_ok=True)
        dest = root / "settings.json"
        tmp = dest.with_suffix(".tmp")
        tmp.write_text(json.dumps({"version": 1, "model_dir": str(self.model_dir),
                                   "output_dir": str(self.output_dir)}, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, dest)
