import json
from pathlib import Path
import tempfile
import unittest
from carrier_metadata import metadata_path, read_length, write_length
from make_samples import make_bmp


class MetadataTests(unittest.TestCase):
    def test_round_trip_and_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '中文载体.bmp'
            bmp = make_bmp(4,4).embed(b'?S')
            self.assertIsNone(read_length(path,bmp))
            write_length(path,bmp,2)
            self.assertEqual(read_length(path,bmp),2)
            self.assertIsNone(read_length(path,bmp.embed(b'AB')))
            record = json.loads(metadata_path(path).read_text(encoding='utf-8'))
            self.assertEqual(set(record),{'version','length_bytes','bmp_sha256'})

    def test_bad_records(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'carrier.bmp'
            bmp = make_bmp(4,4)
            for value in (-1,3,True,'2',None):
                write_length(path,bmp,2)
                record = json.loads(metadata_path(path).read_text(encoding='utf-8'))
                record['length_bytes'] = value
                metadata_path(path).write_text(json.dumps(record),encoding='utf-8')
                self.assertIsNone(read_length(path,bmp))
                with self.assertRaises(ValueError):
                    write_length(path,bmp,value)
            for text in ('invalid JSON','[]','null','{}'):
                metadata_path(path).write_text(text,encoding='utf-8')
                self.assertIsNone(read_length(path,bmp))


if __name__ == '__main__':
    unittest.main()
