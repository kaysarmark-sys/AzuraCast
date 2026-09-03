import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

spec = importlib.util.spec_from_file_location('atmos_worker', Path(__file__).with_name('worker.py'))
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


class WorkerTest(unittest.TestCase):
    def test_joc_object_count(self):
        payload = bytes.fromhex('1800200f000110')
        data = (len(payload) + 8).to_bytes(4, 'big') + b'dec3' + payload
        self.assertEqual(worker.joc_complexity(data), 16)
        self.assertIsNone(worker.joc_complexity(data[:-2].replace(b'\x00\x00\x00\x0f', b'\x00\x00\x00\x0d')))
        with self.assertRaises(ValueError):
            worker.joc_complexity(data[:-1])

    @unittest.skipUnless(os.environ.get('ATMOS_TEST_FILE'), 'Set ATMOS_TEST_FILE to a user-provided E-AC-3 JOC file')
    def test_packet_preservation_fallback_and_transition(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = {'id': 1, 'output': str(root / 'public'), 'work': str(root / 'work'),
                      'key': '1', 'start': time.time() - 20, 'path': os.environ['ATMOS_TEST_FILE'],
                      'live': False, 'cue': 0, 'duration': 18}
            station = worker.Station(source)
            try:
                station.update(source, time.time())
                job = station.jobs[0]
                self.assertEqual(job.process.wait(timeout=30), 0)
                segments = job.segments()
                self.assertEqual(job.objects, 16)
                # Compare compressed audio packets: no lossy re-encoding of Atmos.
                def packets(path):
                    command = ['ffprobe', '-v', 'error', '-select_streams', 'a:0',
                               '-show_packets', '-show_data_hash', 'sha256',
                               '-show_entries', 'packet=data_hash', '-of', 'json', str(path)]
                    return [p['data_hash'] for p in json.loads(subprocess.check_output(command))['packets']]
                copied = packets(job.directory / 'packager.m3u8')
                original = packets(source['path'])
                self.assertEqual(copied, original[:len(copied)])
                station.publish(time.time())
                self.assertIn('16/JOC', (station.output / 'master.m3u8').read_text())
                before = station.entries[-1]['sequence']
                fallback = root / 'fallback.wav'
                subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=18',
                                '-ac', '2', str(fallback)], check=True)
                source.update(key='2', path=str(fallback), start=time.time() - 10)
                station.last_attempt = 0
                station.update(source, time.time())
                self.assertEqual(station.jobs[-1].process.wait(timeout=30), 0)
                self.assertIsNone(station.jobs[-1].segments() and station.jobs[-1].objects)
                station.publish(time.time() + 12)
                playlist = (station.output / 'audio.m3u8').read_text()
                self.assertIn('#EXT-X-DISCONTINUITY\n', playlist)
                self.assertGreater(station.entries[-1]['sequence'], before)
                self.assertEqual(len({e['sequence'] for e in station.entries}), len(station.entries))
                probe = json.loads(subprocess.check_output(['ffprobe', '-v', 'error',
                    '-show_entries', 'stream=codec_name,channels', '-of', 'json',
                    str(station.jobs[-1].directory / 'packager.m3u8')]))
                self.assertEqual(probe['streams'][0]['codec_name'], 'eac3')
                self.assertEqual(probe['streams'][0]['channels'], 2)
            finally:
                station.close()
            self.assertFalse((station.output / 'master.m3u8').exists())


if __name__ == '__main__':
    unittest.main()
