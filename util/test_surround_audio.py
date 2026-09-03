"""Exercise the real PHP-generated encoders using Liquidsoap and FFmpeg."""
import argparse
import json
import math
import pathlib
import struct
import subprocess
import tempfile
import wave

parser = argparse.ArgumentParser()
parser.add_argument("--liquidsoap", default="liquidsoap")
parser.add_argument("--ffmpeg", default="ffmpeg")
parser.add_argument("--ffprobe", default="ffprobe")
parser.add_argument("--php", default="php")
parser.add_argument("--formats", nargs="+", help="Limit the test to selected installed codecs")
parser.add_argument("--encoders", type=pathlib.Path,
                    help="Previously exported surround_encoders.php JSON")
args = parser.parse_args()
root = pathlib.Path(__file__).resolve().parent.parent
encoders = json.loads(args.encoders.read_text() if args.encoders else subprocess.check_output(
    [args.php, str(root / "util/surround_encoders.php")], text=True))
if args.formats:
    encoders = {name: encoders[name] for name in args.formats}

with tempfile.TemporaryDirectory(prefix="azuracast-surround-") as tmp:
    directory = pathlib.Path(tmp)
    # Separate frequencies make channel loss or reordering detectable.
    frequencies = [220, 330, 440, 60, 550, 660]
    for channels in (6, 2):
        with wave.open(str(directory / f"input{channels}.wav"), "wb") as wav:
            wav.setparams((channels, 2, 48000, 0, "NONE", "not compressed"))
            wav.writeframes(b"".join(struct.pack("<h", round(4000 * math.sin(
                2 * math.pi * frequency * sample / 48000)))
                for sample in range(48000 * 3) for frequency in frequencies[:channels]))
    lines = [
        "settings.frame.audio.channels := 6",
        'settings.decoder.decoders := ["ffmpeg"]',
        "log.stdout := true",
        "log.file := false",
        "let azuracast = ()",
        f'%include {json.dumps(str(root / "util/docker/stations/liquidsoap/surround.liq"))}',
        f's = ffmpeg.raw.decode.audio(playlist.list(mode="normal", {json.dumps([str(directory / "input6.wav"), str(directory / "input2.wav")])}))',
        "s = mksafe(s)",
    ]
    for name, encoder in encoders.items():
        source = "azuracast.stereo_downmix(s)" if name == "mp3" else "s"
        if name == "mp3":
            lines += [f'output.file(%ffmpeg(format="mp3", {encoder["audio"]}), '
                      f'{json.dumps(str(directory / "out.mp3"))}, {source})']
            continue
        lines += [
            f'{name}_source = ffmpeg.encode.audio(%ffmpeg({encoder["audio"]}), {source})',
            f'output.file(%ffmpeg(format="{encoder["container"]}", %audio.copy), '
            f'{json.dumps(str(directory / ("out." + name)))}, {name}_source)',
        ]
    lines += ['thread.run(delay=7., fun () -> shutdown())']
    script = directory / "test.liq"
    script.write_text("\n".join(lines))
    subprocess.run([args.liquidsoap, "--check", script.as_posix()], check=True, timeout=60)
    subprocess.run([args.liquidsoap, script.as_posix()], check=True, timeout=60)
    for name in encoders:
        output = directory / ("out." + name)
        info = json.loads(subprocess.check_output([
            args.ffprobe, "-v", "error", "-show_streams", "-of", "json", str(output)
        ], text=True))["streams"][0]
        channels = 2 if name == "mp3" else 6
        assert info["channels"] == channels, (name, info)
        if channels == 6:
            assert info["channel_layout"] in ("5.1", "5.1(side)"), (name, info)
            # Decode the first second into standard FFmpeg PCM channel order.
            pcm = subprocess.check_output([
                args.ffmpeg, "-v", "error", "-i", str(output), "-t", "1",
                "-ar", "48000", "-f", "f32le", "-c:a", "pcm_f32le", "-"
            ])
            samples = struct.unpack("<" + "f" * (len(pcm) // 4), pcm)
            for channel, expected in enumerate(frequencies):
                signal = samples[channel::6]
                strengths = [abs(sum(value * complex(math.cos(2 * math.pi * freq * i / 48000),
                                                    math.sin(2 * math.pi * freq * i / 48000))
                                     for i, value in enumerate(signal))) for freq in frequencies]
                assert frequencies[strengths.index(max(strengths))] == expected, (name, channel)
            # The stereo track must actually play, rather than being rejected
            # by a decoder that can only accept six-channel source files.
            pcm = subprocess.check_output([
                args.ffmpeg, "-v", "error", "-i", str(output), "-ss", "4", "-t", "1",
                "-ar", "48000", "-f", "f32le", "-c:a", "pcm_f32le", "-"
            ])
            samples = struct.unpack("<" + "f" * (len(pcm) // 4), pcm)
            assert len(samples) >= 48000 * 6, (name, "stereo track missing")
            rms = [math.sqrt(sum(v * v for v in samples[channel::6]) / (len(samples) // 6))
                   for channel in range(6)]
            assert min(rms[:2]) > 0.01 and max(rms[2:]) < 0.001, (name, rms)
        print(f"PASS {name}: {channels} channels; channel order verified" if channels == 6
              else "PASS mp3: stereo compatibility output alongside surround")
