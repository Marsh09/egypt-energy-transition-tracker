# Sample raw data (synthetic)

`samples/raw/` has the same folder layout, file names and manifests as a real run, so the
Transformation work can start before real data is available.

**Everything in here is made up.** Product IDs are `SYN-*`, units are `SYN-UNIT`, and the values mean nothing.
The *shape* follows the documented EIA v2 and World Bank responses; the exact field list and
the real `productId` / `unit` values must be checked against the first real EIA file.

Regenerate with `python scripts/generate_samples.py`. The request URLs in the manifests
point at a local stub (`127.0.0.1:8765`) for that reason.
