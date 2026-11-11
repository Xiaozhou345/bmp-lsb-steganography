"""BMP 旁的长度记录，不占图内容量，不保存消息明文。"""
import hashlib
import json
from pathlib import Path


def metadata_path(path):
    return Path(str(path) + '.lsb.json')


def write_length(path, bmp, length):
    if type(length) is not int or not 0 <= length <= bmp.capacity:
        raise ValueError('无效的消息字节数。')
    record = {'version': 1, 'length_bytes': length,
              'bmp_sha256': hashlib.sha256(bmp.data).hexdigest()}
    metadata_path(path).write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')


def read_length(path, bmp):
    try:
        record = json.loads(metadata_path(path).read_text(encoding='utf-8'))
        if not isinstance(record, dict):
            return None
        length = record.get('length_bytes')
        if (record.get('version') != 1 or type(length) is not int
                or not 0 <= length <= bmp.capacity
                or record.get('bmp_sha256') != hashlib.sha256(bmp.data).hexdigest()):
            return None
        return length
    except (OSError, ValueError, RecursionError):
        return None
