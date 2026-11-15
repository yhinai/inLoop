# Vexo Bluetooth and USB captions on macOS

The active route is **Vexo band 43 → Bluetooth → Mac → Pipecat → Deepgram Nova-3 → inLoop**, with Deepgram diarization enabled. The phone supplies GPS and Health separately; it is not the audio source.

The Vexo source and recognition backend are separate choices. The input command uses
Python 3.14, Bleak, pyserial and PyAV; the existing Python 3.15 bridge still owns recognition,
session/sample clocks, immutable save retries, journal and caption delivery.

## Install

Clone the `vexo` branch with `--recurse-submodules`, or run `git submodule update --init`.
The MIT-licensed upstream SDK is pinned by `vendor/vexo-open-kit` at revision
`1e4291e2fa4896b1f603d3d4f0b009c483425da0`; attribution remains in its LICENSE.

Create `.venv-vexo` using Python 3.14, then install `requirements-vexo.txt -c requirements-vexo.lock`.
Create the bridge and Pipecat environments as described in OPERATIONS.md. The optional legacy Whisper environment is not needed for the active setup.
Use private `.env` settings; do not copy installed environments between machines.
Set `OMI_HOST=127.0.0.1`, `OMI_STT_BACKEND=deepgram`,
`OMI_DEEPGRAM_PIPELINE=pipecat`, `OMI_DEEPGRAM_DIARIZE=true`, `OMI_LANGUAGE=en`, `OMI_LANGUAGES=en`.
The Nova-3 model is the adapter default (`OMI_DEEPGRAM_MODEL=nova-3` when explicit).
Deepgram requires a valid private key; never reuse an event key exposed in chat.
Ask the organisers to replace an exposed key.

## Operate

If another browser/serial client owns the band, disconnect that client first. Double-tap band 43 so it blinks blue. In the checkout:

```sh
./vexo start
./vexo source vexo --band 43 --transport ble
```

Bluetooth is the primary wireless connection. USB may remain connected for charging;
no serial port is opened in Bluetooth mode. Keep the band near the Mac. If it cannot
be found, double-tap it again to reopen its 60-second discovery window. Grant macOS
Bluetooth access to the calling app if prompted. Do not pair in System Settings.

For the USB fallback, stop Bluetooth capture and run
`./vexo source vexo --band 43 --transport serial`.

The source command runs in the foreground. Ctrl+C disables the microphone, closes the device connection,
drains queued PCM, sends CloseStream and waits for bridge completion. From another terminal:

```sh
./vexo status
./inloop
./vexo captions
./vexo verify --phrase 'silver otter carries' --timeout 60
```

Use `./inloop` to open the local web app; `./vexo captions` is the optional terminal viewer. Stop capture before `./vexo stop` or any explicit backend switch. The current route is Pipecat/Deepgram; direct Deepgram and local Whisper remain explicit alternatives outside the active setup. There is no silent cloud/local fallback. See [operations](OPERATIONS.md#legacy-alternatives) before changing the route.

Raw audio is not recorded. The blue light means the microphone is on. With Deepgram
selected, nearby sound is sent to that company; tell people nearby before enabling it.
Normal output is `logs/omi_transcript_events.jsonl` plus daily Markdown.

## Input guarantees and limits

USB discovery requires Vexo's vendor/product IDs and product/manufacturer name, excludes
Samsung, refuses busy ports, and verifies the reported band number before enabling audio.
A file lock prevents duplicate capture processes. Vexo and Omi cannot replace each other's
active source, even from the same remote address; existing Omi reconnect semantics remain.

A short device callback copies compressed packets into a bounded 50-packet queue.
A decoder thread validates Opus and uses the upstream PcmDecoder to emit little-endian,
16 kHz mono PCM16 into a second 50-packet queue. Sending is paced by actual sample count.
The first live decoded frame can contain 304 rather than 320 samples due to resampling;
the final resampler tail is drained at normal stop. No WAV headers or Opus reach ingress.

Sequence rollover is accepted; duplicate/old packets are discarded and counted. Any
forward sequence gap ends the source session. SDK concealment is bypassed by feeding
individual validated packets without sequence arguments. Corruption, overload, stale
audio, unplug, or stream takeover ends the session; a fresh USB scan and decoder are
used on retry in USB mode; Bluetooth retries use the SDK filter for band 43 and a new decoder. No invented samples bridge these breaks. Unknown-duration breaks are
journalled as source-discontinuity events rather than assigned fabricated durations.
Source counters appear in loopback health, and console totals report received packets,
missing/old/corrupt/discarded packets, queue overflows and sent samples.

Source identity is copied into each finalized event by its recognizer session, including
late finals; it is not read from the latest mutable source status. This identifies the
verified wearable connection, not a speaker. A complete process crash can still lose RAM queues.
There is no automatic launch-at-login setup in the generic source command.

## Checks

```sh
./vexo dev test -q
./vexo dev faults
.venv-pipecat/bin/python -B -m unittest discover -s tests -p test_pipecat_runtime.py -q
.venv-vexo/bin/python -m unittest scripts.test_vexo_capture -q
./vexo dev smoke --backend deepgram --pipeline pipecat
```

The capture checks exercise real Opus decoding of upstream sample audio, exact sample
count, rollover, loss, duplicate handling, USB filtering, busy-port refusal and normal
microphone shutdown/PCM drain. Core tests cover source ownership and late-final identity;
existing faults cover save recovery and deduplication. They do not prove physical unplug
recovery or arbitrary slow-consumer behavior on hardware.

The Mac is the active deployment; the former Mini writer and its Omi-specific autostart/tunnel jobs are stopped. Retain recovery copies and never rsync old journals over the Mac's newer events. Historical migrations must reconcile by immutable event identity.

## Historical migration verification scope

On the target Mac, core discovery passed 424 tests (two optional runtime tests skipped);
the two runtime tests passed separately in the Pipecat environment. All eight existing
fault/corruption scenarios and eight capture checks passed. Both isolated Pipecat and
direct Deepgram smokes produced finals with matching JSONL and Markdown.

Real band 43 reported firmware 1.1.0. A deliberately spoken short phrase was observed
as a new authenticated caption and verified in the journal, Markdown and viewer layout,
with Vexo source identity and Pipecat/Nova-3 provenance. Longer phrase attempts were
only partially recognized; this is not a measured word-error-rate or accuracy result.
One sustained run received 9,631 packets and drained 3,081,920 samples with zero missing,
old, corrupt, overflowed or discarded packets. A separate hardware stop test exited
normally after draining 279 packets. Terminal captions were opened in a PTY; human
readability was not independently assessed. Physical unplug/replug was not performed.

The target's five migrated model files were verified against SHA-256 hashes from the
source installation. Its isolated Whisper smoke produced a final with matching JSONL
and Markdown. The actual `./vexo backend whisper` / `./vexo backend deepgram` switch
commands were then exercised with capture stopped, returning to Pipecat/Deepgram.
Whisper was verified with synthetic speech, not the live band phrase.


## Bluetooth verification and current transport

Bluetooth uses the same PCM queues, Opus decoder, authentication and recognizer path.
`X-Vexo-Transport` binds `ble` or `serial` to the input session and saved final provenance.
There is no automatic transport switching. The adapter closes and rescans the same band
on link loss; double-tap again if its advertising window has expired. USB fallback stays
available explicitly. No firmware changes were made.

The Bluetooth change passed 438 core tests (two optional runtime tests skipped), nine
capture checks and the existing eight fault scenarios. A real BLE session received
7,837 audio packets and drained 2,507,840 samples with zero missing, old, corrupt,
overflowed or discarded packets. Its spoken test sentence produced a Bluetooth-tagged
Pipecat final, verified in authenticated caption replay, JSONL, Markdown and viewer
layout. Recognition omitted one article; this was input/persistence verification,
not an accuracy benchmark. Normal stop disabled the microphone and drained the bridge.

## App and motion scope

inLoop reads the existing caption WebSocket and the phone's GPS/Health snapshots, then shows transcript-linked items and read-only GitHub issues/PRs. Deepgram Nova-3 supplies speech and anonymous speaker turns. The app uses `gemini-decision-1` through the Decisions API to classify finalized-text candidates as `none`, `todo`, `calendar`, or `action_item`. Titles keep exact source wording; Decision does not generate task descriptions or event details. With Google Calendar event-edit authorization, explicit spoken calendar requests can create events or change/cancel an unambiguous existing event. Missing details remain pending; a durable ledger prevents replayed writes. The Today editor is available for manual adjustments. Gemini Decision can also match explicit spoken task completion to an existing open task.

The existing standalone IMU preview uses `gemini-decision-1` and six-axis Vexo data. That optional motion workflow is separate from inLoop and has not been replaced or expanded by the web app. Its raw-motion preview does not inject Mac input. Screen-relative directions still need an appropriate fresh wearing-direction reference; raw accelerometer axes alone do not establish screen direction.
