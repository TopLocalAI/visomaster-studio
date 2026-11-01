"""Build a relocatable Apple Silicon app from the verified Studio environment.

No models, credentials, user settings or media enter the bundle. Signing uses the
existing Keychain identity. --notarize explicitly submits the DMG to Apple.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
VERSION = '0.2.1'
RELEASE = ROOT.parent / f'releases/macos-{VERSION}'
APP = RELEASE / 'VisoMaster Studio.app'
RES = APP / 'Contents/Resources'
MAGIC = {b'\xcf\xfa\xed\xfe', b'\xca\xfe\xba\xbe', b'\xfe\xed\xfa\xcf', b'\xbe\xba\xfe\xca'}

def run(args, **kw):
    return subprocess.run([str(x) for x in args], check=True, **kw)

def capture(args):
    return subprocess.check_output([str(x) for x in args], text=True)

def macho(p):
    if not p.is_file() or p.is_symlink(): return False
    with p.open('rb') as f: return f.read(4) in MAGIC

def dependencies(p):
    return [line.strip().split(' (compatibility')[0] for line in capture(['otool','-L',p]).splitlines() if line.startswith('\t')]

def remove(p):
    if p.is_symlink() or p.is_file(): p.unlink()
    elif p.exists(): shutil.rmtree(p)

def copy(src, dest):
    if src.is_dir(): shutil.copytree(src, dest, symlinks=True, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.DS_Store'))
    else: dest.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dest)

def build():
    assert sys.platform == 'darwin' and os.uname().machine == 'arm64'
    assert not APP.exists(), 'Existing artifact preserved; choose a new release directory or move it before rebuilding'
    RELEASE.mkdir(parents=True,exist_ok=True)
    RES.mkdir(parents=True)
    py = ROOT/'.venv-studio/bin/python'
    home = Path(capture([py,'-c','import sys; print(sys.base_prefix)']).strip())
    copy(home, RES/'python')
    sp = RES/'python/lib/python3.12/site-packages'
    remove(sp)
    copy(ROOT/'.venv-studio/lib/python3.12/site-packages',sp)
    for p in list(sp.glob('_virtualenv*')): remove(p)
    for name in ['pytest','_pytest','py','pluggy','iniconfig']:
        for p in [sp/name, sp/(name+'.py'), *sp.glob(name+'-*.dist-info')]: remove(p)
    for p in list(sp.rglob('direct_url.json')): p.unlink()
    for base in [RES/'python/lib/python3.12', sp]:
        for p in list(base.rglob('tests')):
            if p.is_dir(): remove(p)
    for n in ['test','idlelib','tkinter','turtledemo','ensurepip']:
        remove(RES/'python/lib/python3.12'/n)
    for p in (RES/'python/lib/python3.12/lib-dynload').glob('_tkinter*'): remove(p)
    for p in list((RES/'python/lib').iterdir()):
        if any(s in p.name for s in ['tcl','tk9','thread3','pkgconfig']): remove(p)
    for n in ['include','share']: remove(RES/'python'/n)
    # No unused executables with absolute developer shebangs.
    for p in (RES/'python/bin').iterdir():
        if not p.name.startswith('python3'): remove(p)
    for p in list((RES/'python/bin').glob('*config')): remove(p)
    # Keep just the Qt modules used by the workspace and the inherited engine.
    qt = sp/'PySide6'
    modules={'QtCore','QtGui','QtWidgets','QtNetwork','QtSvg','QtSvgWidgets','QtMultimedia','QtMultimediaWidgets','QtOpenGL','QtOpenGLWidgets','QtXml'}
    for p in qt.glob('Qt*.so'):
        if p.name.split('.')[0] not in modules: remove(p)
    for n in ['qml','libexec','metatypes','translations']: remove(qt/'Qt'/n)
    for p in (qt/'Qt/plugins').iterdir():
        if p.name not in {'platforms','imageformats','iconengines','multimedia','styles','tls','networkinformation'}: remove(p)
    for p in list((qt/'Qt/plugins/platforms').iterdir()):
        if p.name not in {'libqcocoa.dylib','libqoffscreen.dylib','libqminimal.dylib'}: remove(p)
    needed=set()
    pending=[p for p in qt.glob('*.so')] + [p for p in (qt/'Qt/plugins').rglob('*') if macho(p)]
    visited=set()
    while pending:
        p=pending.pop()
        if p in visited: continue
        visited.add(p)
        for dep in dependencies(p):
            match=re.search(r'(Qt[^/]+)\.framework/',dep)
            if match and match[1] not in needed:
                name=match[1]; needed.add(name)
                framework=qt/'Qt/lib'/f'{name}.framework'
                binary=next(framework.glob('Versions/*/'+name), framework/name)
                if binary.exists(): pending.append(binary)
    for p in (qt/'Qt/lib').glob('*.framework'):
        if p.stem not in needed: remove(p)
    for n in ['include','typesystems','glue','scripts','support']:
        # Python support package is used by PySide6 imports.
        if n!='support': remove(qt/n)
    # Source is intentionally bundled to preserve GPL attribution and aid debugging.
    code=RES/'studio'; code.mkdir()
    copy(ROOT/'app',code/'app')
    for n in ['studio.py','LICENSE','STUDIO.md','version.json','requirements_studio_macos_dev.lock']:
        copy(ROOT/n,code/n)
    (RES/'ThirdPartyNotices.txt').write_text('VisoMaster Studio '+VERSION+'\nBased on VisoMaster Fusion v3.12.3, GPL-3.0. See studio/LICENSE.\nPython dependency license files and metadata are included under python/lib/python3.12/site-packages.\nFFmpeg 8.1 and its libraries are bundled from the local Homebrew build, including GPL codecs. See notices/ffmpeg-build.txt and notices/licenses.\nModels are not bundled.\n')
    notices=RES/'notices'; notices.mkdir()
    (notices/'ffmpeg-build.txt').write_text(capture(['/opt/homebrew/bin/ffmpeg','-version']))
    # Recursively vendor all FFmpeg non-system dylibs and rewrite install names.
    bins=RES/'bin'; bins.mkdir()
    libs=RES/'lib'; libs.mkdir()
    pending=[]; origins={}
    for n in ['ffmpeg','ffprobe']:
        src=Path('/opt/homebrew/bin')/n; copy(src,bins/n); pending.append((src.resolve(),bins/n))
    while pending:
        src,dst=pending.pop()
        for dep in dependencies(src):
            if not dep.startswith('/opt/homebrew/'): continue
            original=Path(dep).resolve()
            # A dylib's first dependency is its own install ID.
            if original==src: continue
            target=libs/original.name
            if target.name in origins: assert origins[target.name]==original
            else:
                origins[target.name]=original; copy(original,target); pending.append((original,target))
            relative=os.path.relpath(target,dst.parent)
            run(['install_name_tool','-change',dep,'@loader_path/'+relative,dst],capture_output=True)
        if dst.suffix=='.dylib': run(['install_name_tool','-id','@loader_path/'+dst.name,dst],capture_output=True)
    # Preserve available dependency notices without copying credentials or build caches.
    for original in set(origins.values()) | {Path('/opt/homebrew/bin/ffmpeg').resolve()}:
        parts=original.parts
        if 'Cellar' not in parts: continue
        i=parts.index('Cellar'); cellar=Path(*parts[:i+3])
        for item in cellar.iterdir():
            if item.is_file() and re.match(r'(?i)(copying|license|notice|copyright)',item.name):
                dst=notices/'licenses'/parts[i+1]/item.name
                if not dst.exists(): copy(item,dst)
    # Normalize wheel frameworks into canonical versioned bundles.
    for fw in RES.rglob('*.framework'):
        versions=fw/'Versions'
        if not versions.is_dir(): continue
        versions_list=[p for p in versions.iterdir() if p.is_dir() and not p.is_symlink()]
        assert len(versions_list)==1
        v=versions_list[0].name
        for target,link in [(v,versions/'Current'),('Versions/Current/'+fw.stem,fw/fw.stem),('Versions/Current/Resources',fw/'Resources')]:
            if link.is_symlink(): continue
            if not (fw/'Versions'/v/('Resources' if link.name=='Resources' else fw.stem)).exists() and link.name=='Resources': continue
            remove(link); link.symlink_to(target)
    exe=APP/'Contents/MacOS/VisoMaster Studio'; exe.parent.mkdir()
    run(['clang','-arch','arm64','-mmacosx-version-min=26.0','-I'+str(home/'include/python3.12'),ROOT/'packaging/macos/launcher.c','-L'+str(home/'lib'),'-lpython3.12','-o',exe])
    libpython=RES/'python/lib/libpython3.12.dylib'
    for dep in dependencies(exe):
        if 'libpython3.12' in dep: run(['install_name_tool','-change',dep,'@executable_path/../Resources/python/lib/libpython3.12.dylib',exe])
    run(['install_name_tool','-id','@loader_path/libpython3.12.dylib',libpython])
    # Relocate the standalone interpreter's absolute libpython reference if present.
    for p in (RES/'python/bin').iterdir():
        if not macho(p): continue
        for dep in dependencies(p):
            if 'libpython3.12' in dep and dep.startswith('/'):
                run(['install_name_tool','-change',dep,'@executable_path/../lib/libpython3.12.dylib',p])
    info={'CFBundleName':'VisoMaster Studio','CFBundleDisplayName':'VisoMaster Studio','CFBundleIdentifier':'com.visomaster.studio','CFBundleVersion':VERSION,'CFBundleShortVersionString':VERSION,'CFBundleExecutable':'VisoMaster Studio','CFBundlePackageType':'APPL','LSMinimumSystemVersion':'26.0','NSHighResolutionCapable':True,'NSPrincipalClass':'NSApplication','CFBundleIconFile':'Studio.icns','NSHumanReadableCopyright':'VisoMaster Studio contributors; based on VisoMaster Fusion (GPL-3.0).'}
    (APP/'Contents/Info.plist').write_bytes(plistlib.dumps(info))
    run([py,ROOT/'packaging/macos/icon.py',RES/'Studio.icns'])
    # Sanity check symlinks and runtime dependency portability before signing.
    for p in APP.rglob('*'):
        if p.is_symlink(): assert p.resolve().is_relative_to(APP), f'External symlink: {p}'
        if macho(p):
            for dep in dependencies(p):
                assert not dep.startswith(('/opt/homebrew','/Users/')), f'External library: {p}: {dep}'
    print('Built portable app',flush=True)

def refresh(source):
    """Reuse an already signed local runtime for a source-only UI update."""
    source = Path(source).resolve()
    assert not APP.exists(), 'Existing artifact preserved'
    old_code = source/'Contents/Resources/studio'
    lock = 'requirements_studio_macos_dev.lock'
    assert (old_code/lock).read_bytes() == (ROOT/lock).read_bytes(), 'Runtime changed: use full build'
    run(['codesign','--verify','--deep','--strict',source])
    RELEASE.mkdir(parents=True, exist_ok=True)
    run(['ditto', source, APP])
    code = RES/'studio'
    remove(code); code.mkdir()
    copy(ROOT/'app', code/'app')
    for name in ['studio.py','LICENSE','STUDIO.md','version.json',lock]:
        copy(ROOT/name,code/name)
    info_path = APP/'Contents/Info.plist'
    info = plistlib.loads(info_path.read_bytes())
    info.update(CFBundleVersion=VERSION,CFBundleShortVersionString=VERSION)
    info_path.write_bytes(plistlib.dumps(info))
    notices = RES/'ThirdPartyNotices.txt'
    lines = notices.read_text().splitlines()
    lines[0] = 'VisoMaster Studio '+VERSION
    notices.write_text('\n'.join(lines)+'\n')
    print('Refreshed source; signing is required before use',flush=True)


def identity():
    if os.environ.get('APPLE_SIGNING_IDENTITY'): return os.environ['APPLE_SIGNING_IDENTITY']
    ids=re.findall(r'"([^"\n]*Developer ID Application:[^"\n]+)"',capture(['security','find-identity','-p','codesigning','-v']))
    assert len(ids)==1, 'Set APPLE_SIGNING_IDENTITY to an installed identity'
    return ids[0]

def sign():
    who=identity(); log=RELEASE/'signing.log'
    def one(p,ent=False):
        if p.is_file():
            details=subprocess.run(['codesign','-dvvv',str(p)],capture_output=True,text=True).stderr
            team=re.search(r'\(([A-Z0-9]+)\)$',who)
            if team and 'TeamIdentifier='+team[1] in details and 'Timestamp=' in details and 'runtime' in details:
                if subprocess.run(['codesign','--verify','--strict',str(p)],capture_output=True).returncode==0: return
        args=['codesign','--force','--timestamp','--options','runtime','--sign',who]
        if ent: args+=['--entitlements',str(ROOT/'packaging/macos/entitlements.plist')]
        for attempt in range(3):
            result=subprocess.run([*args,str(p)],capture_output=True,text=True)
            with log.open('a') as f: f.write(result.stdout+result.stderr)
            if not result.returncode: return
            if attempt==2: raise RuntimeError(result.stderr)
            time.sleep(2)
    files=sorted([p for p in APP.rglob('*') if macho(p)],key=lambda p:len(p.parts),reverse=True)
    for i,p in enumerate(files):
        one(p, p.name.startswith('python3') or p.name=='VisoMaster Studio')
        if i%25==0: print(f'Signed {i+1}/{len(files)} code files',flush=True)
    for p in sorted([p for p in APP.rglob('*') if p.is_dir() and not p.is_symlink() and p.suffix in {'.framework','.app','.xpc'}],key=lambda p:len(p.parts),reverse=True): one(p)
    one(APP,True)
    run(['codesign','--verify','--deep','--strict',APP])

def package(notarize=False):
    dmg=RELEASE/f'VisoMaster-Studio-{VERSION}-macOS-arm64.dmg'
    stage=RELEASE/'dmg-stage'; stage.mkdir(exist_ok=False)
    run(['ditto',APP,stage/APP.name])
    (stage/'Applications').symlink_to('/Applications')
    (stage/'安装说明.txt').write_text('VisoMaster Studio '+VERSION+'\n适用于 Apple Silicon（M 系列）Mac，macOS 26 或更高版本。\n将 VisoMaster Studio 拖入 Applications，然后打开。\n首次处理按提示准备基础模型。\n')
    run(['hdiutil','create','-volname','VisoMaster Studio','-srcfolder',stage,'-format','UDZO',dmg])
    shutil.rmtree(stage)
    run(['codesign','--force','--timestamp','--sign',identity(),dmg])
    if notarize:
        result=run(['xcrun','notarytool','submit',dmg,'--keychain-profile',os.environ.get('NOTARY_PROFILE','visomaster-notary'),'--wait','--output-format','json'],capture_output=True,text=True)
        (RELEASE/'notarization.json').write_text(result.stdout)
        report=json.loads(result.stdout)
        if report.get('status')!='Accepted':
            (RELEASE/'notarization-log.json').write_text(capture(['xcrun','notarytool','log',report['id'],'--keychain-profile',os.environ.get('NOTARY_PROFILE','visomaster-notary')]))
            raise RuntimeError('Notarization failed; see local log')
        for p in [APP,dmg]:
            run(['xcrun','stapler','staple',p]); run(['xcrun','stapler','validate',p])
    checksum=hashlib.file_digest(dmg.open('rb'),'sha256').hexdigest()
    report={'version':VERSION,'file':dmg.name,'bytes':dmg.stat().st_size,'sha256':checksum,'signed':True,'notarized':notarize,'platform':'macOS 26+, Apple Silicon arm64','models_bundled':False}
    (RELEASE/'manifest.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('step',choices=['build','refresh','sign','package'])
    parser.add_argument('--notarize',action='store_true')
    parser.add_argument('--base-app', help='Existing verified local app for a source-only refresh')
    args=parser.parse_args()
    if args.step=='build': build()
    elif args.step=='refresh':
        assert args.base_app, '--base-app is required'
        refresh(args.base_app)
    elif args.step=='sign': sign()
    else: package(args.notarize)
