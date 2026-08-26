# halogen — precision of the shipped checkpoint

What the checkpoint the image loads actually carries. This is the
basis for the bits-per-weight figures quoted in the README.

**~6.3 bits/weight effective at decode, and the only 4-bit trunk tensors are
ones somebody else calibrated.** Two thirds of the weight bytes decode streams
are 8-bit or wider. The single aggressive technique (W4A4, int4 *activations*)
is fenced to prefill and never touches token generation.

| what | value |
|---|---|
| file size | 35.87 GB, 1352 tensors |
| bytes decode streams | **23.51 GB** |
| effective decode precision | **6.32 bpw** over 29.75B params (incl. the 2.2B drafter) |
| 4-bit trunk tensors | FFN mlp only, **imported NVFP4 values** |
| everything else | FP8 rows, BF16 embeddings/norms |
| W4A4 | prefill only (≥64 rows), **all 400 planes active** since the 2026-08-25 promotion (was 168) |

For scale: the `Qwen3.8-27B-UD-Q6_K_XL.gguf` sitting next to it on the box is
25.9 GB at ~6.6 bpw. halogen's decode footprint is slightly *smaller* and in
the same precision class.

---

The per-tensor quantization map is not published.
