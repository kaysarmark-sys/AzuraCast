# Per-station 5.1 output

In **Station Profile → Edit → AutoDJ → Audio Output Channels**, select
**5.1 Surround (6 channels)**, save and restart the station. Stereo remains the
default. The API field is `backend_config.audio_channels` (`2` or `6`); existing
stations need no migration.

Use an AAC, Ogg Vorbis, Opus or FLAC mount to listen in surround. AAC uses AAC-LC,
including HLS streams; Opus uses channel mapping family 1. Start with 320 kbps
for lossy surround streams and adjust to your content and bandwidth. The bitrate
is the total for all channels. MP3 mounts and MP3 live recordings remain stereo
downmixes and can serve as compatibility streams. Other live recording formats
follow the station channel setting. Remote outputs use the same encoder rules;
the receiving server must accept the chosen format.

Surround mode sets Liquidsoap's default PCM channel count to six and uses FFmpeg
decoding and shared FFmpeg encoders. Each encoder converts from the station's
PCM layout independently; MP3 uses a separate raw FFmpeg downmix, so it cannot
force the station into stereo. Inputs pass through raw FFmpeg decoding to handle
mixed channel counts. The six channels are front left/right, center, LFE and
surround left/right (reported as `5.1` or `5.1(side)` by the codec). Use actual 5.1
source files or a compatible live encoder. Stereo sources are converted to the
six-channel layout; this does not create discrete surround content.

Audio post-processing is bypassed in surround mode. The existing processing and
encoder-sharing preferences are retained and take effect again when returning
to stereo. Custom Liquidsoap code must also support six-channel sources.

Icecast relays the encoded stream and needs no invented `channels` XML option.
The bundled stereo fallback files are not attached to surround mounts; the
Liquidsoap fallback is decoded and encoded in the station layout instead. If
Liquidsoap stops completely, these mounts disconnect unless you configure a
compatible explicit fallback mount. User-supplied intro files and explicit
fallbacks must match the mount's codec, sample rate and channel layout.

Listener hardware and software must support the codec and 5.1 output. Browser
or operating-system audio settings may downmix playback even when the stream
contains six channels.

## Verification

Run `vendor/bin/codecept run Unit SurroundAudioTest` for configuration and codec
regressions. Run `python3 util/test_surround_audio.py` in the AzuraCast image
(Liquidsoap 2.4.5, FFmpeg and Python required) for an actual encode/decode test.
It generates six distinct channel tones and a stereo track, runs both through
Liquidsoap, and checks six-channel output and stereo MP3 compatibility.

For deployment acceptance, upload a spoken channel-identification file, restart
the station, and capture an Icecast mount with FFmpeg. Confirm `ffprobe` reports
six channels and `5.1`, then listen to each channel. Repeat with live input, HLS,
fallback playback and a simultaneous MP3 mount before using it on air.

### Checks performed on this change

- PHP 8.4 syntax checks and isolated configuration/encoder regression tests passed.
- Frontend `vue-tsc --noEmit` passed.
- Liquidsoap 2.4.5 type checks passed for stereo and surround common runtime paths
  (with the Linux-only daemon setting omitted for the Windows check).
- The actual PHP-generated Vorbis, Opus and FLAC encoders passed channel-count,
  channel-order and mixed stereo-source playback checks alongside a stereo MP3
  output. The smoke test uses six distinct channel tones.
- AAC-LC configuration was checked, but the portable Windows Liquidsoap build
  lacks `libfdk_aac`, so AAC/HLS encoding and a complete running AzuraCast/Icecast
  deployment still require validation in the Linux image. The full Codeception
  suite was not run locally.

References: [Liquidsoap stream types](https://www.liquidsoap.info/doc-2.4.2/stream_content.html),
[FFmpeg integration](https://www.liquidsoap.info/doc-2.4.2/ffmpeg.html),
[Icecast fallback configuration](https://www.icecast.org/docs/icecast-latest/config_file/).
