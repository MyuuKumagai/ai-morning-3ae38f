#!/usr/bin/env python3
# 公開前チェック：生成したHTMLの中の<script>が構文的に壊れていないかを node で検査する。
# 1つでも壊れていたら終了コード1を返す → GitHub Actions のジョブが失敗し、
# 壊れたサイトは公開されず、直前の正常なサイトがそのまま残る。
import sys, re, subprocess, tempfile, os, glob


def check_file(path):
    html = open(path, encoding="utf-8", errors="replace").read()
    scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
    if not scripts:
        return True  # インラインJSが無いページは対象外
    ok = True
    for i, js in enumerate(scripts):
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
            f.write(js)
            tmp = f.name
        r = subprocess.run(["node", "--check", tmp], capture_output=True, text=True)
        os.unlink(tmp)
        if r.returncode != 0:
            ok = False
            print(f"NG {os.path.basename(path)} の script #{i+1} が壊れています:")
            for line in r.stderr.strip().splitlines()[:6]:
                print("   " + line)
    if ok:
        print(f"OK {os.path.basename(path)}")
    return ok


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "site")
    files = sorted(glob.glob(os.path.join(target, "*.html")))
    if not files:
        print(f"チェック対象のHTMLがありません: {target}")
        return 0
    results = [check_file(f) for f in files]
    if all(results):
        print(f"\n全{len(files)}ページ JS構文OK。公開してよい。")
        return 0
    print("\n構文エラーがあるため公開を中止します（サイトは前回のまま維持）。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
