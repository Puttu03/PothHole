"""Canonical road-damage classes; numeric IDs are never guessed."""
LABELS = {'pothole':'Pothole','longitudinal_crack':'Longitudinal crack','transverse_crack':'Transverse crack','alligator_crack':'Alligator crack','road_damage':'Road damage (unspecified)'}
ALIASES={'d00':'longitudinal_crack','d10':'transverse_crack','d20':'alligator_crack','d40':'pothole','longitudinal crack':'longitudinal_crack','transverse crack':'transverse_crack','alligator crack':'alligator_crack','pothole':'pothole','potholes':'pothole','road damage':'road_damage'}
def canonical(value):
    import re
    name=re.sub(r'[^a-z0-9]+',' ',str(value).lower()).strip()
    if name in ALIASES:return ALIASES[name]
    codes={'d00':'longitudinal_crack','d10':'transverse_crack','d20':'alligator_crack','d40':'pothole'}
    for code,label in codes.items():
        if code in name.split():return label
    for phrase in ('longitudinal crack','transverse crack','alligator crack','road damage','pothole'):
        if phrase in name:return ALIASES[phrase]
    return None
