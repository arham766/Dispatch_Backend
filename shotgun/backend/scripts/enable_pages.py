"""Enable GitHub Pages using the classic deploy-from-branch method."""
import httpx, sys, os, json
os.environ["PYTHONIOENCODING"] = "utf-8"
sys.stdout.reconfigure(encoding='utf-8')

TOKEN = os.environ.get("GITHUB_TOKEN", "")
REPO = "arham766/app-under-test"

# Try loading token from .env
if not TOKEN:
    env_path = r"d:\KANE_KIRO_CLI\shotgun\backend\.env"
    with open(env_path) as f:
        for line in f:
            if line.startswith("GITHUB_TOKEN="):
                TOKEN = line.split("=", 1)[1].strip()

headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

# Check current pages status
print("Checking Pages status...")
r = httpx.get(f"https://api.github.com/repos/{REPO}/pages", headers=headers)
print(f"  Status: {r.status_code}")
if r.status_code == 200:
    d = r.json()
    print(f"  URL: {d.get('html_url')}")
    print(f"  Status: {d.get('status')}")
    print("Pages already enabled!")
    sys.exit(0)

# Try enabling with different accept headers
print("\nTrying to enable Pages...")
for accept in [
    "application/vnd.github+json",
    "application/vnd.github.switcheroo-preview+json",
]:
    r = httpx.post(
        f"https://api.github.com/repos/{REPO}/pages",
        headers={**headers, "Accept": accept},
        json={
            "source": {"branch": "main", "path": "/"},
            "build_type": "legacy",
        },
    )
    print(f"  Accept: {accept}")
    print(f"  Status: {r.status_code}")
    print(f"  Body: {r.text[:300]}")
    if r.status_code in (200, 201):
        print("SUCCESS!")
        break

# Also try updating repo to enable Pages via topics
print("\nChecking repo info...")
r = httpx.get(f"https://api.github.com/repos/{REPO}", headers=headers)
if r.status_code == 200:
    repo = r.json()
    print(f"  Name: {repo['full_name']}")
    print(f"  Has Pages: {repo.get('has_pages', False)}")
    print(f"  Default branch: {repo.get('default_branch')}")
