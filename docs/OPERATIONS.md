# Operation and recovery

The active setup is **Vexo band 43 → Bluetooth → this Mac → Pipecat → Deepgram Nova-3 → inLoop**, with Deepgram diarization enabled. The connected Android phone supplies GPS and Health data; it does not carry the band’s caption audio.

Run commands from the repository directory. `./vexo` uses the project’s Python environment and configuration. Explicit process environment variables override `.env`. Existing `OMI_*` setting names and journal filenames are compatibility details and remain unchanged.

## Connect and read

If the working source and bridge are already running, open `./inloop`; do not start a second source. Otherwise:

1. Run `./vexo start` and `./vexo status`.
2. Release any other client that owns band 43. Double-tap the band to open its Bluetooth discovery window, then run `./vexo source vexo --band 43 --transport ble` in a terminal.
3. Run `./inloop` to open `http://127.0.0.1:8790`. It starts the local web server when needed, subscribes to existing captions and leaves capture ownership with the source process.

USB may stay connected to the band for charging; BLE mode does not read its serial audio port. Keep the band near the Mac. The source command runs in the foreground; its Ctrl+C path disables the microphone, drains queued audio and closes the input session. No second Bluetooth connection is opened by inLoop.

`./vexo status --json` separates bridge health, input connection, fresh audio, provider state and saving. A healthy idle bridge does not establish microphone quality or recognition accuracy. Existing health fields may still say `phone` or `direct_ws`; for this setup their source identity is Vexo 43 over BLE.

The optional terminal viewer is `./vexo captions`: `d` diagnostics, `g` follow live, `/` search, `q` close; `b` bookmarks, `[` / `]` navigate, `B` copies and `e` exports. These are terminal tools, not controls added to the minimal web app.

## Active speech configuration

The private configuration selects:

```dotenv
OMI_HOST=127.0.0.1
OMI_STT_BACKEND=deepgram
OMI_DEEPGRAM_PIPELINE=pipecat
OMI_DEEPGRAM_MODEL=nova-3
OMI_DEEPGRAM_DIARIZE=true
OMI_LANGUAGE=en
OMI_LANGUAGES=en
```

Nova-3 is also the adapter default when the model setting is absent. Deepgram performs speech recognition and anonymous speaker diarization. Speaker numbers are provisional/session-scoped labels, not verified personal identities. Nearby audio leaves the Mac for Deepgram. The current adapter supports fixed English and an English-only publication allowlist.

Pipecat is the active orchestration, not a second recognizer. No Daily room, WebRTC server, LLM or TTS service is needed for this speech route. Its dependencies stay in `.venv-pipecat`, separate from the Python 3.15 bridge and Python 3.14 Vexo capture worker. On a new installation:

```bash
python3.14 -m venv .venv-pipecat
.venv-pipecat/bin/python -m pip install -r requirements-pipecat.txt -c requirements-pipecat.lock
```

Pipecat is pinned to 1.16.0 and Deepgram SDK to 7.19.0. A small pinned-service subclass preserves raw result provenance, ordered drain metadata and source timestamps; the bridge owns retry, bounded replay and immutable save recovery. Upgrade the packages together with runtime tests and a fresh smoke check. Pipecat does not itself prove faster recognition: cold framework startup can delay the first caption.

## GPS, Health, GitHub and tasks

Phone data is a separate path. The installed `dev.alhinai.fliptracker` service writes a private atomic snapshot every five seconds. The Mac reads it over the authorized ADB connection; USB disconnection or stale snapshots are visible. The existing authenticated Tailscale phone ingress and read-only website telemetry are fallbacks. App source/freshness labels distinguish them. This does not change alhinai.dev.

Each GPS fix and Health reading retains its measurement timestamp. A selected transcript can attach only a preceding GPS fix within ten minutes; a fix older than two minutes is last known. Historical speech without a suitable fix remains unmatched. Missing heart rate or sleep is not a zero reading. Phone Health data comes from its actual Health Connect/Fitbit sources, not from Vexo. See [the additive phone snapshot patch](../scripts/inloop-phone-snapshot.md) for rebuilding without losing signing identity, permissions or existing uploads.

GitHub access is read-only through the existing authenticated CLI. The app lists the user's open involved issues and PRs across repositories. It does not create issues, submit reviews or merge PRs. Mac/phone network addresses are shown as actual device details, not assumed public IPs.

Gemini Decision (`gemini-decision-1`, Decisions API) classifies exact-source sentence candidates from finalized transcript snippets as `none`, `todo`, `calendar`, or `action_item`. Resulting titles retain the spoken wording instead of a generated rewrite. Source identity and exact supporting text are checked before storage; a provisional confidence threshold rejects low-score candidates. Calendar items begin as suggestions for review. After event-editing authorization, Gemini Decision can act on explicit spoken calendar requests. Event creation needs a concrete date (without a spoken time it becomes all-day); updates/deletions need one exact existing target. A durable action ledger prevents replay and uncertain-result retries. The editor also supports manual changes. Spoken task completion is matched against actual open task IDs and audited. The separate optional `scripts/live_gemini_motion.py` preview uses the same Decision model for Vexo IMU movement labels. The web app does not add or change motion control or emotion classification.

## Diagnose a problem

```bash
./vexo check
./vexo verify --phrase "Blue lantern seven" --timeout 60
```

`check` reads configuration, package metadata and local health without sending audio. `verify` observes authenticated captions and packet progress. Wait for its subscription-ready message, then speak. Only a new matching final is checked in the journal, Markdown and a fresh viewer. Old terminal painting, physical microphone identity and pre-bridge delay require separate observation.

Viewer diagnostics distinguish segment receipt age from estimated word-end delay. Starred word-end metrics use the bridge receipt clock and exclude upstream wearable delay. A growing `phone_delivery_errors` health counter describes the legacy phone reply path, not loss of the separate journal or caption subscription.

For intentional input recording, run `./vexo dev capture --record --wait-for-enter`. Press Enter and speak after its countdown and Recording message. It requires fresh advancing audio and records at most ten seconds to a private `0600` WAV under `~/Library/Application Support/OmiDiagnostics/`. Listen for the intended words before scoring recognition. There is no public audio-download endpoint. Normal Vexo operation does not record raw audio.

## Stop, restart and history

Stop the foreground Vexo capture before `./vexo stop`, `./vexo restart` or an explicit backend switch. The bridge drains accepted audio. Existing finals live in `logs/omi_transcript_events.jsonl` and daily Markdown; inLoop keeps its workspace in `logs/inloop-app.sqlite3`. Closing a browser window only closes that viewer; it does not turn off the microphone or stop the capture process.

The journal is authoritative; Markdown is its readable projection. Unsaved finals and pending PCM are memory-only, so a full crash or power loss can lose them. Preserve `.env`, transcripts, databases, model assets, credentials and private phone builds outside source control. Avoid history resets and do not overwrite the current journal with Mini recovery files.

## Explicit developer tools

```bash
./vexo dev test -q
./vexo dev faults
./vexo dev smoke --backend deepgram --pipeline pipecat
.venv-pipecat/bin/python -B -m unittest discover -s tests -p test_pipecat_runtime.py -q
.venv-vexo/bin/python -m unittest scripts.test_vexo_capture -q
```

Smoke checks use temporary ports and synthesized or supplied test audio, not the production microphone. Cloud checks upload that test audio. The fault runner exercises eight deterministic fault/corruption scenarios. The paired benchmark is `./vexo dev benchmark`; reports retain exact source/configuration and are not current live-band latency guarantees.

## Legacy alternatives

The following remain supported compatibility tools outside the active Vexo/BLE/Pipecat/inLoop setup; none is an automatic fallback:

- USB audio: stop BLE capture, then run `./vexo source vexo --band 43 --transport serial`.
- Direct Deepgram: set `OMI_DEEPGRAM_PIPELINE=direct` privately, then restart with capture stopped.
- Local Whisper: explicitly select `./vexo backend whisper`; return with `./vexo backend deepgram`. The switcher validates configuration, serializes updates, gracefully restarts and verifies health; failed activation recovers the prior backend when possible. Forced termination or power loss cannot guarantee recovery.
- Official Omi phone-audio compatibility and the old Cloudflare tunnel remain separate from Vexo caption input. Do not provision or enable them for inLoop. The Mini's old writer and Omi-specific autostart/tunnel jobs are disabled.

Whisper runs locally and requires native arm64 macOS, Python 3.14, its pinned requirements and the installed MLX Turbo/Silero assets. Model paths are configurable in `.env.example`. On a new Mac, create the optional worker with `python3.14 -m venv .venv-whisper`, then install `requirements-whisper.txt` using that environment's Python.

Restore the pinned assets into `~/Library/Application Support/OmiWhisper/`: Whisper `config.json` and `weights.safetensors` go in `whisper-turbo/`; Silero goes in `silero_vad.onnx`.

| Asset | Pinned source |
| --- | --- |
| Whisper Turbo FP16 | `mlx-community/whisper-large-v3-turbo`, revision `a4aaeec0636e6fef84abdcbe3544cb2bf7e9f6fb` |
| Silero VAD | `snakers4/silero-vad`, revision `066409f3d9db45a30d21dfcbf9147826ffdd7052`, file `src/silero_vad/data/silero_vad.onnx` |

The Silero SHA-256 is `1a153a22f4509e292a94e67d6f9b85e8deb25b4988682b7e174c65279d8788e3`. Existing installations need no model download.


The superseded extended Whisper fixture generator remains in the [recovery archive](archive/README.md). Existing installations need no new download merely to run inLoop. No legacy path should be described as the current audio source without checking actual source identity and backend health.
