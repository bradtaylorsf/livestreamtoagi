# Livestream Encoder And RTMP Push

`scripts/livestream/stream-push.sh` is the local ffmpeg entry point for the
greenfield livestream pipeline. It can run a generated smoke source or encode a
real capture input configured through `VIDEO_INPUT_FORMAT` and `VIDEO_INPUT`.

Examples:

```bash
scripts/livestream/stream-push.sh --smoke --duration 5 --output-file /tmp/stream_smoke.flv
```

```bash
VIDEO_INPUT_FORMAT=avfoundation \
VIDEO_INPUT="1:none" \
RTMP_URL=rtmp://live.example.test/app \
RTMP_STREAM_KEY=... \
scripts/livestream/stream-push.sh
```

For live agent voices, add `--with-tts` and point `TTS_AUDIO_FIFO` at the FIFO
created by the backend bridge. See [audio-tts.md](audio-tts.md) for the
`tts_play` -> FIFO -> ffmpeg audio path and verification command.

