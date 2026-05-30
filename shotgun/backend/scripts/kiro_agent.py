import time, json, os, subprocess

WORKDIR = "d:/KANE_KIRO_CLI/app-under-test"
TRIGGER = "d:/KANE_KIRO_CLI/app-under-test/.shotgun/trigger.json"

print("[Kiro] Mock Kiro Bot is online and watching for incidents...")

while True:
    if os.path.exists(TRIGGER):
        print(f"\n[Kiro] Trigger detected: {TRIGGER}")
        try:
            with open(TRIGGER) as f:
                data = json.load(f)
            branch = data["branch"]
            print(f"[Kiro] Fixing incident on branch: {branch}")
            
            # Checkout branch
            subprocess.run(f"git checkout -B {branch}", shell=True, cwd=WORKDIR)
            
            # Fix the bug in payment.js (cardNumbr -> cardNumber)
            payment_js = f"{WORKDIR}/payment.js"
            if os.path.exists(payment_js):
                with open(payment_js, "r") as f:
                    code = f.read()
                code = code.replace("cardNumbr", "cardNumber")
                with open(payment_js, "w") as f:
                    f.write(code)
                print(f"[Kiro] Bug patched in payment.js")
            else:
                print(f"[Kiro] Error: {payment_js} not found!")
                
            # Commit and push using the new token
            subprocess.run("git add -A", shell=True, cwd=WORKDIR)
            subprocess.run(f'git commit -m "fix: resolve checkout error (cardNumbr typo)"', shell=True, cwd=WORKDIR)
            
            # Auth with the token to avoid hangs
            token = os.environ.get("GITHUB_TOKEN", "")
            url = f"https://oauth2:{token}@github.com/arham766/app-under-test.git"
            subprocess.run(f"git remote set-url origin {url}", shell=True, cwd=WORKDIR)
            
            subprocess.run(f"git push --set-upstream origin {branch}", shell=True, cwd=WORKDIR)
            print(f"[Kiro] Pushed fix to GitHub: {branch}")
            
            # Delete trigger file
            os.remove(TRIGGER)
            print("[Kiro] Trigger file deleted. Ready for next incident.")
        except Exception as e:
            print(f"[Kiro] Error: {e}")
            os.remove(TRIGGER) # Remove it so it doesn't loop infinitely on error
            
    time.sleep(2)
