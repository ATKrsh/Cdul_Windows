import os
import re

with open('../Allme_Windows/allme.py', 'r', encoding='utf-8') as f:
    code = f.read()

# Replace App Names & Paths
code = code.replace('"Allme"', '"Cdul"')
code = code.replace("'Allme'", "'Cdul'")
code = code.replace("allme.py", "cdul.py")
code = code.replace("allme_crash_report.txt", "cdul_crash_report.txt")
code = code.replace("AllMeD Dashboard", "Cdul Dashboard")
code = code.replace("AllMeD Control Dashboard", "Cdul Control Dashboard")

# Remove telemetry_source and telemetry_target from DEFAULT_CONFIG
code = re.sub(r'\s*"telemetry_source":\s*".*?",?', '', code)
code = re.sub(r'\s*"telemetry_target":\s*".*?",?', '', code)
code = re.sub(r'\s*"hdd_drive":\s*".*?",?', '', code)
code = re.sub(r'\s*"hdd_mode":\s*".*?",?', '', code)
code = re.sub(r'\s*"net_mode":\s*".*?",?', '', code)
code = re.sub(r'\s*"gpu_choice":\s*".*?",?', '', code)

# Remove Link Source & Link Sink submenus from _setup_tray
code = re.sub(r'# 📊 Submenu 4: Renamed to "Link Source".*?target_menu\.addAction\(act\)\n', '', code, flags=re.DOTALL)

# Remove Telemetry Links box from DashboardWindow
code = re.sub(r'# --- TELEMETRY ---.*?\n\s*grp2 = QGroupBox\("Telemetry Links"\); grp2\.setLayout\(v2\); grid\.addWidget\(grp2, 0, 1\)\n', '', code, flags=re.DOTALL)

# Save as cdul.py
with open('cdul.py', 'w', encoding='utf-8') as f:
    f.write(code)

print("Generated super-lite cdul.py cleanly.")
