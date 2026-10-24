import io
import os
import requests
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

FONTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "fonts")
os.makedirs(FONTS_DIR, exist_ok=True)

# 1. Onest
print("Fetching Onest variable font...")
onest_url = "https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/onest/Onest%5Bwght%5D.ttf"
r = requests.get(onest_url, timeout=20)
r.raise_for_status()

# Save license
ofl_url = "https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/onest/OFL.txt"
r_ofl = requests.get(ofl_url, timeout=10)
with open(os.path.join(FONTS_DIR, "OFL-Onest.txt"), "w", encoding="utf-8") as f:
    f.write(r_ofl.text)

onest_weights = {
    "Regular": 400,
    "Medium": 500,
    "SemiBold": 600,
    "Bold": 700,
}

for name, wght in onest_weights.items():
    var_font = TTFont(io.BytesIO(r.content))
    static_font = instancer.instantiateVariableFont(var_font, {"wght": wght})
    out_path = os.path.join(FONTS_DIR, f"Onest-{name}.ttf")
    static_font.save(out_path)
    print(f"Saved {out_path} ({os.path.getsize(out_path)} bytes)")

# 2. JetBrains Mono
print("Fetching JetBrains Mono variable font...")
jbm_url = "https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/jetbrainsmono/JetBrainsMono%5Bwght%5D.ttf"
r_jbm = requests.get(jbm_url, timeout=20)
r_jbm.raise_for_status()

jbm_ofl_url = "https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/jetbrainsmono/OFL.txt"
r_jbm_ofl = requests.get(jbm_ofl_url, timeout=10)
with open(os.path.join(FONTS_DIR, "OFL-JetBrainsMono.txt"), "w", encoding="utf-8") as f:
    f.write(r_jbm_ofl.text)

jbm_weights = {
    "Regular": 400,
    "Medium": 500,
}

for name, wght in jbm_weights.items():
    var_font = TTFont(io.BytesIO(r_jbm.content))
    static_font = instancer.instantiateVariableFont(var_font, {"wght": wght})
    out_path = os.path.join(FONTS_DIR, f"JetBrainsMono-{name}.ttf")
    static_font.save(out_path)
    print(f"Saved {out_path} ({os.path.getsize(out_path)} bytes)")

print("All fonts generated successfully!")
