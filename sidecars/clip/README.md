# CLIP embedding sidecar

The model behind image search in generated apps. A Blueprint field
`{"type": "vector", "embedding": {"of": "photo"}}` is filled from the `photo`
field on every write and ranked by an `op: "similar"` page source (or `similar()`
in a code page's `load.ts`). This service computes the vectors.

CLIP (open_clip ViT-B-32, `laion2b_s34b_b79k`) embeds images and text into one
space, so a record can be found by another picture or by a sentence.

## Run

```bash
docker compose up -d --build     # http://localhost:8001, weights baked into the image
./smoke.sh                       # a red square must sit closer to "red" than to "blue"
```

CPU only, about 1 GB. One image takes tens of milliseconds once warm.

## Connect

Set `EMBEDDINGS_URL` (and `EMBEDDINGS_API_KEY` if the sidecar sets one) under
**Settings → Integrations → Embeddings** on the platform. Every generated app
receives them in its environment, like any other platform integration.

Without it, writes still succeed (the vector stays empty and is filled on the
row's next write), and a search says that image search is not connected.

## Contract

`POST /embed` with exactly one of `{image_b64, mime_type}`, `{image_url}` or
`{text}` returns `{vector, dimensions, model}`, the vector L2-normalised.

## Changing the model

The column length is the platform's `EMBEDDING_DIMENSIONS`
(`backend/services/blueprint/embeddings.py`, 512). A model with another output
length needs that constant changed, the apps' schemas re-projected and every row
re-embedded. The runtime refuses a vector of the wrong length by name rather
than storing it.
