# inLoop

**Live conversations. Clear speakers. Useful next steps.**

inLoop turns speech from a **Vexo wearable** into live captions and action suggestions on your Mac, alongside location, GitHub, and phone Health.

![inLoop in dark mode with live captions, action items, GPS, GitHub, and Health](docs/images/inloop-dark.png)

*Live inLoop dashboard in dark mode — screenshot supplied from our demo.*

<h2 align="center" id="demo">Demo</h2>

<p align="center">
  <a href="https://youtu.be/6uO9b89b-s0">
    <img src="docs/images/demo-thumbnails/03-typography.png" alt="Watch the inLoop VexoHacks demo: live captions to action items" width="720">
  </a>
</p>

<p align="center">
  <a href="https://youtu.be/6uO9b89b-s0"><strong>▶ Watch the inLoop demo</strong></a>
</p>

## The pipeline

```text
Vexo → Bluetooth → Mac → Pipecat → Deepgram
                                  ↓
                       Transcript + speaker labels
                                  ↓
                         Gemini Decision 1
                                  ↓
                 To-do · Calendar suggestion · Action item
```

| Component | Role |
| --- | --- |
| **Vexo** | Captures speech and streams audio directly to the Mac over Bluetooth. |
| **Pipecat** | Runs the streaming speech pipeline between the Mac bridge and Deepgram. |
| **Deepgram Nova-3** | Transcribes speech and distinguishes speakers through diarization. |
| **Gemini Decision 1** | Classifies finalized speech into to-do, calendar, other action-item, or no-action categories. |

The phone supplies **GPS and Health**, separately from wearable audio. It is not an audio relay. Deepgram through Pipecat is the active speech path.

## What you see

- **Live transcript:** newest speech at the top, interim words as they arrive, and saved final captions with speaker labels.
- **To-do:** review suggestions, add your own tasks, and jump back to the supporting speech. Gemini Decision can complete matching tasks and apply clear calendar requests automatically once Google event-edit access is enabled.
- **Today:** see today’s Google Calendar agenda; add, edit and delete events, or use the editor when a spoken request needs more details.
- **Location:** select a passage to see a phone GPS fix matched to its recording time, when available.
- **GitHub:** browse your open issues and pull requests.
- **Devices and Health:** connection status, IP addresses, and phone readings with their measurement times.

Gemini Decision selects a category; it does not write free-form task descriptions. Suggestion text comes from the original transcript, preserving its source. A no-action decision produces no suggestion.

## Open the app

On the configured Mac, from this repository:

```sh
./inloop
```

Or double-click **inLoop.command**. The launcher opens [localhost:8790](http://127.0.0.1:8790).

Manage or inspect capture with `./vexo`:

```sh
./vexo status
./vexo check
```

The caption service and Vexo connection must already be running. Closing the dashboard leaves capture running. For a fresh installation, follow the setup guides below.

## Streaming and storage

Pipecat and Deepgram provide the streaming path; interim captions appear immediately on receipt, and final captions are saved before publication. One receiver owns the wearable connection. These choices support responsiveness and recovery; they are not a universal latency guarantee.

Audio goes to Deepgram; finalized transcript candidates go to Gemini Decision. Missing Health readings remain unavailable. GPS matches use recorded fixes, not place names inferred from speech. The current setup supports one wearer.

Sessions, transcripts, suggestions, and GPS snapshots are stored under the ignored `logs/` directory. Keep credentials, APKs, and personal recordings out of Git.

## Setup and details

| Guide | What it covers |
| --- | --- |
| [App guide](docs/INLOOP.md) | Controls, models, storage, Maps, and data sources |
| [Today calendar](docs/CALENDAR.md) | Google sign-in, agenda sync, and event editing |
| [Vexo setup](docs/VEXO.md) | Bluetooth, USB alternative, and device checks |
| [Phone connection](scripts/inloop-phone-snapshot.md) | GPS and Health over ADB |
| [Wireless phone telemetry](docs/PHONE_TAILSCALE.md) | Direct phone-to-Mac GPS and Health over Tailscale |
| [Caption service](docs/CAPTION_SERVICE.md) | Pipecat/Deepgram operation and checks |
| [Operations](docs/OPERATIONS.md) | Installation and troubleshooting |
| [Architecture](docs/ARCHITECTURE.md) | Ownership, persistence, and recovery guarantees |

inLoop runs separately from the personal website; it does not deploy changes to alhinai.dev.
