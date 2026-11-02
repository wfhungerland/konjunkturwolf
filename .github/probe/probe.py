import subprocess
ids = ["de_alq_sa", "de_alo_sa", "de_vac_sa", "de_ka_sa", "de_ka_fte_ratio", "de_sahm", "de_sahm_u", "de_sahm_v"]
subprocess.run(["python", "-m", "konjunkturwolf", "run", "--no-cache", "--only", *ids], check=True)
