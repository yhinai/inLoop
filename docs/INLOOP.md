# inLoop

A local Mac workspace for Vexo speech, action suggestions, GPS, GitHub, and phone Health.

## Open

```sh
./inloop
```

Or double-click `inLoop.command`. The launcher starts the app and opens <http://127.0.0.1:8790>. `./inloop --no-open` starts it without opening a browser. No frontend build or npm runtime is required.

Capture must already be running. Inspect it with `./vexo status` and `./vexo check`. The dashboard reads the existing caption stream; it does not create a second Bluetooth connection. Closing the browser leaves capture running.

## Speech and decisions

```text
Vexo band 43 → Bluetooth → Mac → Pipecat → Deepgram Nova-3
                                              ↓
                                  Transcript + speaker labels
                                              ↓
                                     gemini-decision-1
                                              ↓
                           To-do / Calendar suggestion / Action item
```

- **Vexo** supplies microphone audio directly to the Mac. The phone is not an audio relay.
- **Pipecat** runs the streaming Deepgram service in its isolated worker. The bridge owns source timing, reconnect handling, and persisted finals.
- **Deepgram** provides transcription and speaker diarization. `Speaker 1` distinguishes a voice within its recognition session; it is not verified personal identity.
- **Gemini Decision 1** classifies finalized transcript candidates as `none`, `todo`, `calendar`, or `action_item`. The title and quote come from the original text; there is no free-form generation or Flash-Lite fallback. Only validated decisions meeting the confidence threshold create suggestions.

Gemini Decision can apply explicit calendar requests automatically after Google event-edit authorization: create a clearly dated obligation, or change/cancel one unambiguous existing event. Missing dates and unclear targets remain pending with a reason shown on the task. Duplicate/replayed requests do not send repeated writes; an uncertain write result is never retried automatically. Spoken completion such as “I finished testing Bluetooth” can mark the matching existing task done. Use **Add to calendar**, **+ Event** or **Edit** for manual adjustments. Old and manually added tasks retain their original provenance.

The [Decisions API](https://aistudio.google.com/docs/decisions-api) returns fixed choices and scores rather than generated prose. Motion experiments also use Gemini Decision, through a separate preview path; they do not replace the speech/action pipeline above.

## Read and review

Live drafts and saved captions appear **newest first**. Scrolling into older speech keeps the visible passage stable as new entries arrive. `New speech ↑` returns to the top. Select a final passage or task source to inspect its matching GPS fix.

Tasks can be added, completed, edited, or deleted locally. GitHub reads open issues and PRs involving the configured account (`yhinai`); it does not change them. Refresh failures retain cached results and label them accordingly.

## GPS, Health, and devices

The phone supplies GPS and Android Health Connect data separately from speech. When attached and authorized, ADB reads a private snapshot refreshed every five seconds. Without USB, the existing authenticated Tailscale receiver and website telemetry remain fallbacks.

Each Health reading keeps its own measurement timestamp. Missing readings remain unavailable. A recent upload is not proof that an individual sensor reading is new. GPS matches use fixes recorded at or before speech; older speech can have no matching fix.

The device list shows the Mac LAN IP and phone Wi-Fi IP. The Mac's Tailscale IP is available in its tooltip. Phone IPs are network metadata, not the Bluetooth audio route.

The additive phone update preserves existing website and direct-Mac uploads. See the [ADB snapshot notes](../scripts/inloop-phone-snapshot.md) and [wireless phone telemetry](PHONE_TAILSCALE.md). APKs, keystores, credentials, build output, and personal data stay private under ignored paths.

## Maps

Location uses Google satellite imagery for the selected phone fix. Interactive 3D is enabled when private `.env` contains a browser Maps key authorized for localhost and the necessary Maps access. This browser-visible key is separate from Gemini's server key. Without a configured local 3D key, satellite embedding remains available. No personal-site key restrictions are changed.

## Storage and privacy

Audio is processed by Deepgram. Finalized transcript candidates are sent to Gemini Decision for classification. App state uses private `logs/inloop-app.sqlite3`; app logs use `logs/inloop-app.log`. The caption bridge also retains its authoritative journal and daily notes. Do not publish these files or credentials.

The interface follows the personal site's palette and headings above cards. Desktop content fits the viewport; long lists and the transcript scroll independently. This app does not deploy or write changes to alhinai.dev.
