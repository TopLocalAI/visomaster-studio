"""Small upstream geometry/reference data, not inference weights."""
from pathlib import Path
import hashlib
import os

HASHES = {'liveportrait_onnx/lip_array.pkl': '2d61aab1cc37a2741f4774fe9963b2db2566e063f798b1d28d791dd119352738', 'meanshape_68.pkl': '39ffecf84ba73f0d0d7e49380833ba88713c9fcdec51df4f7ac45a48b8f4cc51', 'alphaface/emp.npy': 'cee626bc81721d71c5d6cb1f76f830b9ae46f595514b0884dd8ae34785576764', 'ref-ldm_embedding/configs/ldm.yaml': 'e5491203680f1f352e306c529a76a52792c2a42e947d7549be034f0cdde4e214', 'ref-ldm_embedding/configs/refldm.yaml': '7eba7c411690aa79249939e7a98b54eb10b98d218a14a2323e30b538a03ad62b', 'ref-ldm_embedding/configs/vqgan.yaml': '01681749ed015fade6d0ddaa667c5e00a1ccd4437ce225ae6b6a1df89a080730'}


def install_auxiliary(root):
    for name, expected in HASHES.items():
        source = Path(__file__).with_name('data') / name
        content = source.read_bytes()
        if hashlib.sha256(content).hexdigest() != expected:
            raise ValueError('辅助数据校验失败，请重新安装应用')
        target = root / name
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == expected:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink() or not target.resolve().is_relative_to(root.resolve()):
            raise ValueError('辅助数据路径无效')
        temp = target.with_suffix(target.suffix + '.tmp')
        if temp.is_symlink():
            raise ValueError('辅助数据路径无效')
        temp.write_bytes(content)
        os.replace(temp, target)
