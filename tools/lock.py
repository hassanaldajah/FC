"""Write a pip --require-hashes lock from the exact versions installed in a venv,
taking every published sha256 for each version from the PyPI JSON API."""
import json, subprocess, sys, urllib.request
venv_py, out, *skip = sys.argv[1:]
skip = {s.lower() for s in skip} | {"pip"}
frozen = subprocess.run([venv_py, "-m", "pip", "freeze", "--all"], capture_output=True, text=True, check=True).stdout
lines = ["# Exact versions with hashes. Install with:  pip install --require-hashes -r " + out.split("/")[-1],
         "# Regenerated from requirements.in (see the README)."]
for row in sorted(frozen.split(), key=str.lower):
    name, ver = row.split("==")
    if name.lower() in skip:
        continue
    data = json.load(urllib.request.urlopen(f"https://pypi.org/pypi/{name}/{ver}/json", timeout=30))
    hashes = sorted({f["digests"]["sha256"] for f in data["urls"]})
    lines.append(f"{name}=={ver} \\")
    lines += [f"    --hash=sha256:{h} \\" for h in hashes[:-1]] + [f"    --hash=sha256:{hashes[-1]}"]
open(out, "w", newline="\n").write("\n".join(lines) + "\n")
print("locked", sum(1 for l in lines if "==" in l), "packages ->", out)
