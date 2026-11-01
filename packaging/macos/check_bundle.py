"""Run the existing workflow checks using only the app's runtime and source."""
import os
from pathlib import Path
import runpy
import sys
bundle=Path(sys.argv[1]).resolve()
check=Path(sys.argv[2]).resolve()
args=sys.argv[3:]
for flag in ['--source','--target','--output']:
    if flag in args:
        i=args.index(flag)+1; args[i]=str(Path(args[i]).resolve())
source=bundle/'Contents/Resources/studio'
sys.path.insert(0,str(source))
from app.studio.runtime import configure_runtime
configure_runtime()
assert Path(sys.executable).is_relative_to(bundle)
sys.argv=[str(check),*args]
runpy.run_path(str(check),run_name='__main__')
