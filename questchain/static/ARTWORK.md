# Agent artwork

The four specialist sets introduced in November 2026 follow the approved
QuestChain blue-agent pixel-art direction. Each role has three individually
prepared, transparent PNGs:

- Researcher (`Explorer`): `researcher-stage-{1,2,3}.png`, purple, book and magnifier.
- Workspace knowledge (`Keeper`): `workspace-stage-{1,2,3}.png`, green, scrolls and window icons.
- Builder (`Builder`): `builder-stage-{1,2,3}.png`, orange, hammer and armor.
- Scheduler (`Scheduler`): `scheduler-stage-{1,2,3}.png`, red, pocketwatch and clock motifs.

These assets were prepared with image generation's background-extraction edit
workflow from the approved role concept sheets, then visually checked. They are
individual production cutouts, not lossless rectangular crops of the sheets.
The prompt requested preservation of each selected character's design, pose,
proportions, colors, blocky style and accessories, removal of the charcoal
backdrop and floor shadow, and a genuine transparent background. The stone
pedestals and floating role accessories are intentional parts of the sprites.

Each file is 1254 × 1254, 8-bit RGBA, with transparent padding. Keep alpha when
exporting. The UI uses its existing `object-fit: contain` image slots. No new
rendering dependency or external asset URL is needed, and the existing
`static/*` package-data rule includes the files in distributions.

The server selects stage 1 at levels 1–5, stage 2 at levels 6–10 and stage 3 at
level 11 and above. Only the four corresponding entries in `_CLASS_IMAGES`
change. The main/Router, Custom fallback and Planner artwork remain unchanged,
and legacy specialist files remain available. Main-agent source image bytes
are protected by `tests/test_agent_artwork.py`.
