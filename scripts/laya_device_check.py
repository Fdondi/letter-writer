"""Print the Laya device this machine would use. Does not download weights."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from letter_writer.laya_device import probe_cuda, probe_directml, resolve_laya_device


def main() -> None:
    cuda_ok, cuda_name = probe_cuda()
    dml_ok, dml_name = probe_directml()
    kind, detail = resolve_laya_device()
    print(f"cuda: {cuda_ok} {cuda_name}".rstrip())
    print(f"directml: {dml_ok} {dml_name}".rstrip())
    print(f"selected: {kind}")
    print(f"detail: {detail}")


if __name__ == "__main__":
    main()
