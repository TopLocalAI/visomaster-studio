"""VisoMaster Studio entry point for the complete workspace and optional engine worker."""
import argparse
import sys


def main():
    from app.studio.runtime import configure_runtime
    configure_runtime()
    parser = argparse.ArgumentParser(description='VisoMaster Studio')
    parser.add_argument('--engine', action='store_true')
    parser.add_argument('--source')
    parser.add_argument('--target')
    parser.add_argument('--output')
    parser.add_argument('--frame', type=int, default=0)
    args = parser.parse_args()
    if args.engine:
        if not all((args.source, args.target, args.output)):
            parser.error('engine requires source, target and output')
        from app.studio.engine import run_engine
        return run_engine(args)
    from PySide6.QtWidgets import QApplication
    from app.studio.workspace import StudioWorkspace
    app = QApplication([sys.argv[0]])
    app.setApplicationName('VisoMaster Studio')
    app.setOrganizationName('VisoMasterStudio')
    window = StudioWorkspace()
    window.show()
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
