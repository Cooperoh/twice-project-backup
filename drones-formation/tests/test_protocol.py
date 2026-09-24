#!/usr/bin/env python3

import threading
import time
import unittest
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from client.autopilot import (
    FrameStreamParser,
    LatestFrameReader,
    ProtocolError,
    ReceivedFrame,
    SentFrame,
    build_frame,
    pack_send_frame,
    parse_frame,
    parse_receive_frame,
)


class FormationProtocolTest(unittest.TestCase):
    def test_pack_send_frame_matches_document_example(self):
        frame = pack_send_frame(
            seq=1,
            target_system=1,
            lat=40.8663949,
            lon=109.5596,
            alt=1380,
            spd=125,
        )

        self.assertEqual(
            frame.hex(" ").upper(),
            "EB 90 01 11 01 00 01 09 93 4E 1A A0 DD 86 46 "
            "60 DE 02 00 D4 30 93",
        )

    def test_parse_receive_frame_matches_document_example(self):
        frame = (
            "EB 90 02 12 01 00 01 01 09 93 4E 1A "
            "A0 DD 86 46 60 DE 02 00 D4 30 94"
        )

        received = parse_receive_frame(frame)

        self.assertIsInstance(received, ReceivedFrame)
        self.assertEqual(received.seq, 1)
        self.assertEqual(received.sending_system, 1)
        self.assertEqual(received.phase, 1)
        self.assertAlmostEqual(received.lat, 40.8663949, places=7)
        self.assertAlmostEqual(received.lon, 109.5596, places=7)
        self.assertAlmostEqual(received.alt, 1380.0, places=2)
        self.assertAlmostEqual(received.spd, 125.0, places=2)

    def test_parse_receive_frame_rejects_document_checksum_typo(self):
        typo_frame = (
            "EB 90 02 12 01 00 01 01 09 93 4E 1A "
            "A0 DD 86 46 60 DE 02 00 D4 30 93"
        )

        with self.assertRaises(ProtocolError):
            parse_receive_frame(typo_frame)

    def test_parse_rejects_bad_header(self):
        frame = bytearray(
            pack_send_frame(
                seq=1,
                target_system=1,
                lat=40.8663949,
                lon=109.5596,
                alt=1380,
                spd=125,
            )
        )
        frame[0] = 0xEA

        with self.assertRaises(ProtocolError):
            parse_frame(frame)

    def test_parse_rejects_bad_length(self):
        frame = bytearray(
            pack_send_frame(
                seq=1,
                target_system=1,
                lat=40.8663949,
                lon=109.5596,
                alt=1380,
                spd=125,
            )
        )
        frame[3] = 0x12

        with self.assertRaises(ProtocolError):
            parse_frame(frame)

    def test_parse_rejects_bad_checksum(self):
        frame = bytearray(
            pack_send_frame(
                seq=1,
                target_system=1,
                lat=40.8663949,
                lon=109.5596,
                alt=1380,
                spd=125,
            )
        )
        frame[8] ^= 0x01

        with self.assertRaises(ProtocolError):
            parse_frame(frame)

    def test_negative_coordinates_round_trip_through_int32(self):
        frame = pack_send_frame(
            seq=65535,
            target_system=3,
            lat=-10.5,
            lon=-20.125,
            alt=100.25,
            spd=12.34,
        )

        parsed = parse_frame(memoryview(frame))

        self.assertIsInstance(parsed, SentFrame)
        self.assertEqual(parsed.seq, 65535)
        self.assertEqual(parsed.target_system, 3)
        self.assertAlmostEqual(parsed.lat, -10.5, places=7)
        self.assertAlmostEqual(parsed.lon, -20.125, places=7)
        self.assertAlmostEqual(parsed.alt, 100.25, places=2)
        self.assertAlmostEqual(parsed.spd, 12.34, places=2)

    def test_stream_parser_waits_for_complete_frame(self):
        parser = FrameStreamParser()
        frame = _receive_frame()

        self.assertEqual(parser.feed(frame[:8]), [])
        frames = parser.feed(frame[8:])

        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].seq, 1)
        self.assertAlmostEqual(frames[0].spd, 125.0, places=2)

    def test_stream_parser_returns_multiple_frames(self):
        parser = FrameStreamParser()
        first = _receive_frame(seq=1, spd=120)
        second = _receive_frame(seq=2, spd=130)

        frames = parser.feed(first + second)

        self.assertEqual([frame.seq for frame in frames], [1, 2])
        self.assertAlmostEqual(frames[-1].spd, 130.0, places=2)

    def test_stream_parser_skips_noise_before_header(self):
        parser = FrameStreamParser()

        frames = parser.feed(b"\x00\xFF\x55" + _receive_frame())

        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].seq, 1)

    def test_stream_parser_recovers_after_bad_checksum(self):
        parser = FrameStreamParser()
        bad = bytearray(_receive_frame(seq=1))
        bad[-1] ^= 0x01

        frames = parser.feed(bytes(bad) + _receive_frame(seq=2))

        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].seq, 2)

    def test_stream_parser_keeps_split_header_byte(self):
        parser = FrameStreamParser()
        frame = _receive_frame()

        self.assertEqual(parser.feed(b"\x00\xEB"), [])
        frames = parser.feed(frame[1:])

        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].seq, 1)

    def test_latest_frame_reader_keeps_only_newest_frame(self):
        fake_serial = _FakeSerial(
            [
                _receive_frame(seq=1, spd=110),
                _receive_frame(seq=2, spd=120) + _receive_frame(seq=3, spd=130),
            ]
        )
        reader = LatestFrameReader(fake_serial, read_size=128, idle_sleep=0.001)

        try:
            reader.start()
            deadline = time.time() + 1.0
            latest = None
            while time.time() < deadline:
                latest = reader.get_latest()
                if latest is not None and latest.seq == 3:
                    break
                time.sleep(0.01)
        finally:
            reader.stop()

        self.assertIsNotNone(latest)
        self.assertEqual(latest.seq, 3)
        self.assertAlmostEqual(latest.spd, 130.0, places=2)


def _receive_frame(
    *,
    seq=1,
    sending_system=1,
    phase=1,
    lat=40.8663949,
    lon=109.5596,
    alt=1380,
    spd=125,
):
    payload = bytearray()
    payload += int(seq).to_bytes(2, byteorder="little", signed=False)
    payload += int(sending_system).to_bytes(1, byteorder="little", signed=False)
    payload += int(phase).to_bytes(1, byteorder="little", signed=False)
    payload += round(lat * 3600 * 3000).to_bytes(4, byteorder="little", signed=True)
    payload += round(lon * 3600 * 3000).to_bytes(4, byteorder="little", signed=True)
    payload += round((alt + 500) / 0.01).to_bytes(4, byteorder="little", signed=False)
    payload += round(spd / 0.01).to_bytes(2, byteorder="little", signed=False)
    return build_frame(2, payload)


class _FakeSerial:
    def __init__(self, chunks):
        self._chunks = list(chunks)
        self._lock = threading.Lock()

    def read(self, _size):
        with self._lock:
            if self._chunks:
                return self._chunks.pop(0)
        time.sleep(0.005)
        return b""


if __name__ == "__main__":
    unittest.main()
