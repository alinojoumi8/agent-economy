# Phase 1 modular asset kit

The kit contains original procedural assets for `residence`, `office`, `workshop`, `bank`, `civic_hall`, `neutral`, and `agent`. Each asset has a low and high detail GLB. Building details are children of a metadata root at the ground-centered origin. No textures, labels, simulation records, entity IDs, or external game assets are embedded.

`catalog.json` is the source-side catalog and is copied byte-for-byte to `dashboard/public/city/catalog.json`. Dimensions use native meters in `[width, height, depth]` order for the exported glTF Y-up convention. Variant URLs use `/city/<key>-<detail>.glb`. The catalog pins Blender, the exporter source SHA-256, every GLB SHA-256, byte size, triangle count, and material names/count.

## Reproduce and validate

From the repository root:

```bash
blender --background --python city/blender/export_assets.py
python3 city/validate_assets.py
python3 -m pytest -q tests/test_city_assets.py
```

Generation and validation were run with Blender 5.2.1 LTS. Validation reimported all 14 GLBs and checked unique metadata roots, finite transforms, nonempty meshes, material references, grounded pivots, declared bounds, and recorded triangle counts. The public kit totals 223,924 bytes against its 10,000,000-byte budget. Catalog rejection tests cover duplicate keys, oversized variants, and invalid dimensions.

`contact-sheet.png` was rendered from the exported high-detail GLBs and visually inspected. All seven silhouettes are visible at city zoom; the residence roof, office height, workshop vent/loading door, bank colonnade, civic tower, neutral fallback, and agent marker remain distinct.

## Limits

The assets are static geometry with simple Principled BSDF materials. Browser GPU/frame-time performance belongs to the viewer integration gate. Binary GLB identity is pinned for this export but is not promised across Blender versions; rerunning the exporter intentionally refreshes hashes and both catalog copies. The existing `city/blender/build_city.py` concept generator remains independent and unchanged.
