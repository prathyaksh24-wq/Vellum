# Kannada dictation language control

Researched 2026-10-19 after the user reported Kannada-dominant speech with a few English words being rendered in Tamil by Turbo's automatic language selection. This research did not reproduce the user's recording or run model inference.

## Recommendation

Offer an explicit **Kannada** dictation language choice, persist the user's choice through the existing settings owner, and send `language="kn"` with `task="transcribe"`. Keep **Auto** available for other recordings. This follows the user's stated language; it avoids inferring their speech language from location, UI locale, or the script of an already incorrect transcript. Whisper's language mapping includes `kn` as Kannada. [OpenAI tokenizer](https://github.com/openai/whisper/blob/main/whisper/tokenizer.py)

The following behavior is verified from faster-whisper **v1.2.1** source:

- `language=None` invokes language detection. An explicit language skips that step and configures the tokenizer with that language.
- The forced-language path sets `language_probability=1`. That value reflects configuration, not measured confidence or perfect recognition.
- Detection defaults are one segment and threshold `0.5`. A segment is up to 30 seconds. Raising the threshold allows additional segments to be considered; if none clears the threshold, the code still chooses a language by majority of segment winners. It does not abstain.
- More detection segments cannot add speech that a short clip does not contain.
- Keep `multilingual=False`, the default, when honoring a fixed language. `multilingual=True` re-detects language per decoding segment and changes the tokenizer language; it can override the initial choice.

Source: [versioned transcription and detection implementation](https://github.com/SYSTRAN/faster-whisper/blob/v1.2.1/faster_whisper/transcribe.py).

For the reported case, explicit Kannada is a more direct first correction than increasing detection thresholds. A language hint still does not guarantee that every English phrase remains in Latin script, that numbers use the user's preferred form, or that names are spelled correctly. Evaluate the user's actual Kannada/English phrase, including “22 piece,” after the change. Do not force Hindi solely because earlier Hindi and English recordings worked.

## Small public local fixture

One unmodified Kannada WAV and a provenance sidecar were downloaded into the repository's **ignored** test-data folder:

- Audio: `.test-data/dictation-language/fleurs-kn-validation-81.wav`
- Metadata: `.test-data/dictation-language/fleurs-kn-validation-81.json`
- Source: **Google FLEURS**, `kn_in`, `validation`, row index `81`, example ID `1612`.
- Dataset revision: `70bb2e84b976b7e960aa89f1c648e09c59f894dd`.
- License listed by dataset owner: **CC BY 4.0**. Preserve attribution to the FLEURS dataset authors/Google and the dataset card if redistributing the sample; it is currently local test data only.
- Known reference: `100 ಅಡಿ ಅಗಲದ ಕೊಳವೆಯ ಒಳರಚನೆಯಲ್ಲಿ ನೀರು ಸುರಿಯುತ್ತಿದೆ`.
- Downloaded WAV size: **288,058 bytes**; decoded **72,000 mono samples at 16 kHz**, **4.5 seconds**.
- SHA-256: `bf3d7a53f6210a8f4e1b6eeeff028694b8a85e0c9d73feacdbf103bb3dba4e5f`.

Sources: [owner's dataset card and license](https://huggingface.co/datasets/google/fleurs), [immutable dataset revision](https://huggingface.co/datasets/google/fleurs/tree/70bb2e84b976b7e960aa89f1c648e09c59f894dd), [cached Kannada validation metadata](https://datasets-server.huggingface.co/first-rows?dataset=google%2Ffleurs&config=kn_in&split=validation). The sidecar records the downloaded asset's canonical path without its expiring public access signature.

The Hugging Face `/rows` request for the test split failed remotely with a parquet scan-size limit. The cached `/first-rows` endpoint for validation succeeded; the shortest of its exposed examples was selected to keep the local fixture small. No dataset archive, parquet shard, credentials, or private speech was downloaded.

The WAV is IEEE float audio, which Python's standard `wave` reader rejected as format 3. The installed dictation runtime's `faster_whisper.audio.decode_audio` decoded it successfully to a 72,000-element `float32` array. Keep the original WAV; a format conversion is unnecessary for the current runtime.

## What this can establish

Compare the same fixture with `language=None` and `language="kn"`, recording returned text, detected/requested language, latency and errors against the reference. Test the normal backend/worker path as well as direct model calls so request propagation is covered. Treat explicitly selected language as a preference in status/history, rather than reporting fabricated detection confidence.

This example is read Kannada with a number. It is **not** a code-switching benchmark, a recording of the user, or proof that the reported Tamil result is fixed. Retain a stated manual check for the user's natural Kannada with English words. Increasing model size alone does not establish correct language selection or faithful spelling.
