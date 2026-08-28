# Phase 3 Provider live evidence

Date: 2026-08-24

Branch: `codex/product-production-backend`

## Gate status

`PASSED — FOUR REAL MODALITIES VERIFIED`

The earlier TLS failure was caused by the local proxy route, not by the API key
or model contracts. Switching Clash/Mihomo to rule mode allowed the Beijing
DashScope hosts to use the configured direct route. The smoke runner then
completed without any mock or fallback.

## Secret handling

- `DASHSCOPE_API_KEY` is stored only as a Windows user environment variable.
- The repository contains no API key, provider response body, signed artifact
  URL or `.env` with a live credential.
- The smoke output records only model identity, request-ID presence, usage
  presence and artifact counts.

## Accepted live run

Run ID: `0368bcf9-87cd-41a4-b99d-f985dbab2872`

| Modality | Exact model | Result | Request ID | Usage | Local artifact |
|---|---|---:|---:|---:|---:|
| Text | `qwen3.5-plus` | passed | present | present | text response |
| Image | `qwen-image-3.0-pro` | passed | present | present | 1 image |
| Video | `wan2.7-t2v` | passed | present | present | 1 video |
| Audio | `qwen3-tts-flash` | passed | present | present | 1 audio file |

The image, video and audio files were downloaded into the system temporary
directory and were not committed. The evidence JSON was consumed by the
fail-closed catalog activation command, which enabled only these four verified
deployments.

## Contract and region boundary

The active adapters use the Beijing-region OpenAI-compatible and native
DashScope endpoints. Alibaba documents that API keys are region-specific and
that the base URL must match the key's region:

- <https://help.aliyun.com/en/model-studio/singapore-regional-access-information>
- <https://help.aliyun.com/en/model-studio/base-url>

The Wan request uses its native asynchronous submit/poll contract. Image and
audio use native multimodal generation; text uses the OpenAI-compatible chat
completion stream.

## Acceptance boundary

This record proves live provider connectivity and successful four-modal calls
on this device. It does not prove production capacity, rate-limit headroom,
pricing correctness, regional failover or an object-storage deployment.
