#!/usr/bin/env python3
"""Image build step: fetch every tree-sitter grammar build_graph.py uses into OUT_DIR (read-only at runtime).

tree-sitter-language-pack downloads grammars on first use; the sealed sandbox has no network, so the image
ships them and sets TREE_SITTER_LANGUAGE_PACK_LIBS_DIR. Usage: bake_grammars.py TOOLS_DIR OUT_DIR
"""

import glob
import os
import shutil
import sys
import tempfile


def main(tools_dir: str, out_dir: str) -> int:
    sys.path.insert(0, tools_dir)
    from build_graph import EXT_LANG

    with tempfile.TemporaryDirectory() as cache:
        os.environ["TREE_SITTER_LANGUAGE_PACK_CACHE_DIR"] = cache
        import tree_sitter_language_pack as tslp

        langs = sorted(set(EXT_LANG.values()))
        for lang in langs:
            tslp.get_parser(lang)
        os.makedirs(out_dir, exist_ok=True)
        libs = glob.glob(os.path.join(cache, "**", "*.so"), recursive=True)
        for lib in libs:
            dst = os.path.join(out_dir, os.path.basename(lib))
            shutil.copyfile(lib, dst)
            os.chmod(dst, 0o644)
    print(f"baked {len(libs)} grammars for {len(langs)} languages: {', '.join(langs)}")
    return 0 if libs else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
