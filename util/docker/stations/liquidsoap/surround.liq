# Resample before MP3 encoding, without constraining the station source to stereo.
# FFmpeg applies its standard downmix matrix (including center/surround channels).
def azuracast.stereo_downmix(s) =
    ffmpeg.raw.encode.audio(%ffmpeg(%audio.raw(channels=2)), s)
end
