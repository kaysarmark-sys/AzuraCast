"""Separate HLS timeline: copy E-AC-3, encode other sources, never mix Atmos PCM.

The source snapshot is a local CLI command, not a public file-access endpoint.
Only completed fragments are published, with fresh maps at every track boundary.
"""
import collections
import datetime
import json
import math
import os
from pathlib import Path
import shutil
import selectors
import signal
import subprocess
import time
import uuid

SEGMENT = 2
DELAY = 12
WINDOW = 12
RETENTION = 180
ROOT = Path(__file__).resolve().parents[2]


def edit_boxes(data, replacement=None):
    """Find/replace dec3 while updating enclosing MP4 box sizes."""
    result = bytearray()
    found = None
    offset = 0
    containers = {b'moov': 0, b'trak': 0, b'mdia': 0, b'minf': 0,
                  b'stbl': 0, b'stsd': 8, b'ec-3': 28}
    while offset < len(data):
        if offset + 8 > len(data):
            raise ValueError('Truncated MP4 box header')
        size = int.from_bytes(data[offset:offset + 4], 'big')
        kind = data[offset + 4:offset + 8]
        header = 8
        if size == 1:
            header = 16
            size = int.from_bytes(data[offset + 8:offset + 16], 'big')
        if size == 0:
            size = len(data) - offset
        if size < header or offset + size > len(data):
            raise ValueError('Invalid MP4 box size')
        payload = data[offset + header:offset + size]
        if kind == b'dec3':
            found = payload
            if replacement is not None:
                payload = replacement
        elif kind in containers:
            prefix = containers[kind]
            children, child_found = edit_boxes(payload[prefix:], replacement)
            payload = payload[:prefix] + children
            found = child_found if found is None else found
        if header == 16:
            result += b'\x00\x00\x00\x01' + kind + (16 + len(payload)).to_bytes(8, 'big')
        else:
            result += (8 + len(payload)).to_bytes(4, 'big') + kind
        result += payload
        offset += size
    return bytes(result), found


def original_dec3(path):
    # Seek over mdat instead of loading a potentially multi-gigabyte media file.
    with open(path, 'rb') as handle:
        while True:
            header = handle.read(8)
            if len(header) < 8:
                return None
            size = int.from_bytes(header[:4], 'big')
            header_size = 8
            if size == 1:
                size = int.from_bytes(handle.read(8), 'big')
                header_size = 16
            if size < header_size:
                return None
            if header[4:] == b'moov':
                if size > 32 * 1024 * 1024:
                    raise ValueError('Oversized MP4 metadata box')
                return edit_boxes(handle.read(size - header_size))[1]
            handle.seek(size - header_size, 1)


def atomic(path, text):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(text, encoding='utf-8')
    temporary.replace(path)


def joc_complexity(data):
    """Read extension_type_a/complexity_index_type_a from a dec3 box.

    The value is the decodable object count, NOT the PCM channel count.
    """
    offset = data.find(b'dec3')
    if offset < 4:
        return None
    size = int.from_bytes(data[offset - 4:offset], 'big')
    if size < 10 or offset - 4 + size > len(data):
        raise ValueError('Invalid dec3 box')
    payload = data[offset + 4:offset - 4 + size]
    bits = ''.join(f'{b:08b}' for b in payload)
    pos = 0

    def take(count):
        nonlocal pos
        if pos + count > len(bits):
            raise ValueError('Truncated dec3 box')
        value = int(bits[pos:pos + count], 2)
        pos += count
        return value

    take(13)
    independent = take(3) + 1
    for _ in range(independent):
        take(19)
        dependent = take(4)
        take(9 if dependent else 1)
    if len(bits) - pos < 8:
        return None
    take(7)
    if not take(1):
        return None
    complexity = take(8)
    if not 1 <= complexity <= 16:
        raise ValueError('Unsupported JOC object count')
    return complexity


def read_segments(path):
    if not path.exists():
        return []
    segments, duration, elapsed = [], None, 0.0
    for line in path.read_text().splitlines():
        if line.startswith('#EXT-X-MEDIA-SEQUENCE:'):
            elapsed = int(line.split(':', 1)[1]) * SEGMENT
        elif line.startswith('#EXTINF:'):
            duration = float(line.split(':', 1)[1].split(',')[0])
        elif line and not line.startswith('#') and duration is not None:
            name = Path(line).name
            if name != line or not name.endswith('.m4s'):
                raise ValueError('Unexpected packager segment name')
            segments.append((name, elapsed, duration))
            elapsed += duration
            duration = None
    return segments


class Job:
    def __init__(self, source, now):
        self.key = source['key']
        self.start = now if source['live'] else source['start']
        self.end = float('inf')
        self.token = uuid.uuid4().hex
        self.directory = Path(source['work']) / self.token
        self.directory.mkdir(parents=True)
        self.log = (self.directory / 'ffmpeg.log').open('w')
        self.expected_atmos = False
        self.live = source['live']
        self.objects = None
        self.original_dec3 = None
        self.init_for_publish = 'init.mp4'
        self.init_checked = False
        if not source['live']:
            probe = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'a:0',
                                    '-show_entries', 'stream=codec_name,profile', '-of', 'json',
                                    source['path']], capture_output=True, text=True, timeout=15, check=True)
            stream = json.loads(probe.stdout)['streams'][0]
            self.expected_atmos = 'Atmos' in stream.get('profile', '')
            copy = stream['codec_name'] == 'eac3'
            if self.expected_atmos:
                self.original_dec3 = original_dec3(source['path'])
        else:
            copy = False
        command = ['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'warning', '-y']
        if source['live']:
            command += ['-re']
        elif source['cue']:
            command += ['-ss', str(source['cue'])]
        command += ['-i', source['path'], '-map', '0:a:0', '-vn', '-sn', '-dn']
        if copy:
            command += ['-c:a', 'copy']
        else:
            command += ['-c:a', 'eac3', '-ac', '6', '-ar', '48000', '-b:a', '768k', '-threads', '2']
        if not source['live'] and source['duration']:
            command += ['-t', str(source['duration'])]
        command += ['-f', 'hls', '-hls_time', str(SEGMENT), '-hls_list_size', '120' if self.live else '0',
                    '-hls_delete_threshold', '90',
                    '-hls_segment_type', 'fmp4', '-hls_flags', 'temp_file+delete_segments' if self.live else 'temp_file',
                    '-hls_fmp4_init_filename', 'init.mp4',
                    '-hls_segment_filename', (self.directory / '%06d.m4s').as_posix(),
                    (self.directory / 'packager.m3u8').as_posix()]
        self.process = subprocess.Popen(command, stdout=self.log, stderr=self.log)

    def segments(self):
        result = read_segments(self.directory / 'packager.m3u8')
        if result and not self.init_checked:
            init = (self.directory / 'init.mp4').read_bytes()
            self.objects = joc_complexity(init)
            if self.expected_atmos and self.objects is None and self.original_dec3:
                init, _ = edit_boxes(init, self.original_dec3)
                self.objects = joc_complexity(init)
                self.init_for_publish = 'published-init.mp4'
                (self.directory / self.init_for_publish).write_bytes(init)
            if self.expected_atmos and self.objects is None:
                raise ValueError('Refusing to publish Atmos with missing JOC signaling')
            self.init_checked = True
        return result

    def stop(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.log.close()

    def remove(self):
        self.stop()
        shutil.rmtree(self.directory)


class Station:
    def __init__(self, source):
        self.output = Path(source['output'])
        self.output.mkdir(parents=True, exist_ok=True)
        self.jobs = []
        self.published = set()
        self.entries = collections.deque(maxlen=WINDOW)
        # New sessions never reuse old sequence numbers or fragment URLs.
        self.sequence = int(time.time() * 1000)
        self.discontinuity = int(time.time())
        self.last_token = None
        self.last_cleanup = 0
        self.last_attempt = 0
        self.bandwidth = 1100000

    def update(self, source, now):
        current = self.jobs[-1] if self.jobs else None
        failed = current and (current.process.poll() not in (None, 0) or
                              (current.live and current.process.poll() is not None))
        if current is None or current.key != source['key'] or (failed and now - self.last_attempt > 30):
            if now - self.last_attempt < 5:
                return
            self.last_attempt = now
            job = Job(source, now)
            if current:
                current.end = job.start
                current.stop()
            self.jobs.append(job)
            print(f"Station {source['id']}: packaging {source['key']}", flush=True)
        self.publish(now)

    def publish(self, now):
        for job in self.jobs:
            for name, offset, duration in job.segments():
                identity = (job.token, name)
                timestamp = job.start + offset
                if identity in self.published or timestamp + duration > job.end:
                    continue
                if timestamp + duration > now - DELAY:
                    continue
                self.published.add(identity)
                if timestamp < now - DELAY - WINDOW * SEGMENT:
                    continue
                init = f'{job.token}_init.mp4'
                segment = f'{job.token}_{name}'
                for src, dst in [(job.init_for_publish, init), (name, segment)]:
                    destination = self.output / dst
                    if not destination.exists():
                        shutil.copyfile(job.directory / src, destination.with_suffix('.tmp'))
                        destination.with_suffix('.tmp').replace(destination)
                if self.last_token != job.token:
                    self.discontinuity += 1
                self.entries.append({'sequence': self.sequence, 'disc': self.discontinuity,
                                     'init': init, 'segment': segment, 'duration': duration,
                                     'time': timestamp, 'objects': job.objects})
                self.bandwidth = max(self.bandwidth, math.ceil((self.output / segment).stat().st_size * 8 / duration * 1.1))
                self.sequence += 1
                self.last_token = job.token
        if self.entries:
            self.write_playlists()
        if now - self.last_cleanup > 30:
            self.last_cleanup = now
            referenced = {e[k] for e in self.entries for k in ('init', 'segment')}
            for path in self.output.iterdir():
                if path.suffix in ('.m4s', '.mp4', '.tmp') and path.name not in referenced:
                    if now - path.stat().st_mtime > RETENTION:
                        path.unlink()
            while len(self.jobs) > 1 and self.jobs[0].end < now - RETENTION:
                old = self.jobs.pop(0)
                self.published = {key for key in self.published if key[0] != old.token}
                old.remove()
            if len(self.published) > 2000:
                self.published = set(sorted(self.published)[-1000:])

    def write_playlists(self):
        first = self.entries[0]
        lines = ['#EXTM3U', '#EXT-X-VERSION:7',
                 f'#EXT-X-TARGETDURATION:{max(3, math.ceil(max(e["duration"] for e in self.entries)))}',
                 f'#EXT-X-MEDIA-SEQUENCE:{first["sequence"]}',
                 f'#EXT-X-DISCONTINUITY-SEQUENCE:{first["disc"]}']
        previous = None
        for entry in self.entries:
            if previous and entry['disc'] != previous['disc']:
                lines.append('#EXT-X-DISCONTINUITY')
            if not previous or entry['init'] != previous['init']:
                lines.append(f'#EXT-X-MAP:URI="{entry["init"]}"')
            date = datetime.datetime.fromtimestamp(entry['time'], datetime.timezone.utc).isoformat()
            lines += [f'#EXT-X-PROGRAM-DATE-TIME:{date}', f'#EXTINF:{entry["duration"]:.6f},', entry['segment']]
            previous = entry
        atomic(self.output / 'audio.m3u8', '\n'.join(lines) + '\n')
        objects = max((e['objects'] or 0 for e in self.entries), default=0)
        channels = f'{objects}/JOC' if objects else '6'
        label = 'Dolby Atmos' if objects else 'Dolby Digital Plus'
        master = ['#EXTM3U', '#EXT-X-VERSION:7',
                  f'#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="dolby",NAME="{label}",DEFAULT=YES,AUTOSELECT=YES,CHANNELS="{channels}",URI="audio.m3u8"',
                  f'#EXT-X-STREAM-INF:BANDWIDTH={self.bandwidth},CODECS="ec-3",AUDIO="dolby"', 'audio.m3u8']
        atomic(self.output / 'master.m3u8', '\n'.join(master) + '\n')

    def close(self):
        for job in self.jobs:
            job.remove()
        # Remove public entry points immediately when disabled; retain fragments
        # briefly for clients that already downloaded the final playlist.
        for name in ('master.m3u8', 'audio.m3u8'):
            (self.output / name).unlink(missing_ok=True)


def main():
    stations = {}
    running = True
    watcher = None
    selector = selectors.DefaultSelector()
    sources = []
    last_snapshot = time.time()

    def stop(*_):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        while running:
            try:
                if watcher is None:
                    watcher = subprocess.Popen(['php', str(ROOT / 'backend/bin/console'),
                                                'azuracast:internal:atmos-sources', '--watch', '--no-ansi'],
                                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
                    selector.register(watcher.stdout, selectors.EVENT_READ)
                    last_snapshot = time.time()
                if selector.select(timeout=0.5):
                    line = watcher.stdout.readline()
                    if line.startswith('['):
                        snapshot = json.loads(line)
                        if not isinstance(snapshot, list):
                            raise ValueError('Invalid source snapshot')
                        sources = snapshot
                        last_snapshot = time.time()
                if watcher.poll() is not None or time.time() - last_snapshot > 30:
                    selector.unregister(watcher.stdout)
                    watcher.terminate()
                    watcher.wait(timeout=5)
                    watcher.stdout.close()
                    watcher = None
                    sources = []
                    print('Restarting Atmos source watcher after loss of heartbeat.', flush=True)
                active = {s['id'] for s in sources}
                for station_id in list(stations):
                    if station_id not in active:
                        stations.pop(station_id).close()
                for source in sources:
                    try:
                        station = stations.setdefault(source['id'], None)
                        if station is None:
                            station = stations[source['id']] = Station(source)
                        station.update(source, time.time())
                    except Exception as exc:
                        print(f"Atmos station {source['id']}: {exc}", flush=True)
            except Exception as exc:
                print(f'Atmos source snapshot unavailable: {exc}', flush=True)
                time.sleep(1)
    finally:
        if watcher:
            watcher.terminate()
            try:
                watcher.wait(timeout=5)
            except subprocess.TimeoutExpired:
                watcher.kill()
                watcher.wait()
        selector.close()
        for station in stations.values():
            if station:
                station.close()


if __name__ == '__main__':
    main()
