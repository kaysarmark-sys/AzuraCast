# Atmos HLS passthrough

Enable **Station Profile → Edit → HLS → Enable Dolby Atmos HLS Passthrough**
alongside ordinary HLS. Save and restart the station after initially enabling HLS.
The additional URL is `/hls/STATION_SHORTCODE/atmos/master.m3u8`.
The API setting is `backend_config.output_mode`: `stereo` (default) or `atmos`.
Legacy `hls_atmos` settings remain accepted. Legacy six-channel AutoDJ settings
are normalized to stereo.

This separate worker follows the station's current-song record without consuming
its scheduling queue. Dolby Digital Plus files are packet-copied into fragmented
MP4 HLS. Other files are encoded to 48 kHz, stereo Dolby Digital Plus at
768 kbps. Stereo sources do not acquire discrete surround content. When no local
file is available, including live DJ and remote storage playback, it transcodes
the ordinary HLS stream as non-Atmos fallback. Ordinary HLS must remain enabled.

File playback bypasses AutoDJ crossfades, normalization, DSP, custom Liquidsoap
processing and volume changes. Cue-in and calculated duration are applied at
compressed-frame boundaries. The additional playlist is buffered by 12 seconds
before the client's own HLS buffer; it follows the same songs but is not sample-
synchronized with Icecast. Transitions occur at approximately two-second segment
boundaries and carry discontinuity tags plus a new initialization map. Fallback
from the ordinary HLS stream adds its existing latency too.

Atmos signaling is read from the source/packaged `dec3` box, including the real
JOC object count. Older FFmpeg versions may omit this extension while remuxing;
the worker restores the original MP4 decoder configuration without modifying any
audio packet. It refuses an Atmos package if valid JOC signaling cannot be found.
Use Dolby Digital Plus JOC M4A/MP4 source files with valid decoder metadata. This
is not an Atmos encoder and does not support lossless TrueHD Atmos passthrough.

During a non-Atmos track the audio is ordinary Dolby Digital Plus. The master
manifest reports the content in the current window, and each fragment map carries
its decoder configuration. Player behavior when changing between Atmos and
ordinary surround must be checked on the target iPhone/receiver; a desktop codec
probe alone cannot establish what the device will display or render.

The Atmos URL uses the existing station HLS serving and blocklist path. It is a
mode-specific URL, selected automatically by the public player.
Its audience is not currently added to the per-AAC-rendition listener totals.

The production Dockerfile installs `util/atmos-hls/supervisor.conf`. The worker log
is `/var/azuracast/www_tmp/service_atmos_hls.log`. Disabling the option stops its
packager and removes its playlists. Public fragments are retained briefly for
in-flight requests; live fallback packaging uses a bounded rolling window.

## Tests

`ATMOS_TEST_FILE=/path/to/user-provided-atmos.m4a python3 util/atmos-hls/test_worker.py`

Tests check JOC metadata, exact compressed-packet preservation, stereo
non-Atmos fallback, discontinuity/map changes, sequence ordering and disable
cleanup. No commercial test audio is included in the repository or image.

Reference: [Dolby Atmos HLS signaling](https://ott.dolby.com/OnDelKits/DDP/Dolby_Digital_Plus_Online_Delivery_Kit_v1.5/Documentation/Content_Creation/SDM/help_files/topics/hls_c_hls_signal_atmos_ddp.html).
