import os
import pytest
from cymseed3 import MiniSeed

# Path to the directory containing example MiniSEED files
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


@pytest.fixture
def miniseed():
    """Fixture for initializing and freeing MiniSeed object."""
    ms = MiniSeed()
    yield ms
    del ms


def test_import_record(miniseed):
    """Test importing a record into MiniSeed."""
    record_dict = {
        'network': 'OX',
        'station': 'ABCD',
        'location': '00',
        'channel': 'HHZ',
        'starttime': '2010-01-10T08:23:45.019538Z',
        'rate': 200,
        'nsamp': 100,
        'data': [i for i in range(100)]
    }
    miniseed.import_record(record_dict)
    assert miniseed is not None, "Failed to import record into MiniSeed"


def test_write_and_read(miniseed, tmp_path):
    """Test writing and reading MiniSEED records to and from a file."""
    record_dict = {
        'network': 'OX',
        'station': 'ABCD',
        'location': '00',
        'channel': 'HHZ',
        'starttime': '2010-01-10T08:23:45.019538Z',
        'rate': 200,
        'nsamp': 100,
        'data': [i for i in range(100)]
    }
    miniseed.import_record(record_dict)
    
    # Write data into binary buffer
    byte_buffer = miniseed.write(msformat=2, reclen=512, encoding=11)
    assert byte_buffer, "Failed to write MiniSEED data to buffer"

    # Write bytes to a temporary file
    output_file = tmp_path / "my_file.mseed"
    with open(output_file, "wb") as fid:
        fid.write(byte_buffer)
    assert output_file.exists(), "Failed to write buffer to file"

    # Read the file
    with open(output_file, 'rb') as fid:
        byte_buffer = fid.read()
    assert byte_buffer, "Failed to read MiniSEED data from file"

    # Read the buffer back into the MiniSeed object
    miniseed.read(byte_buffer, verbose=1)
    rec_list = miniseed.export_records()
    assert len(rec_list) > 0, "Failed to export records from MiniSeed"


def test_export_records(miniseed):
    """Test exporting records from MiniSeed to a list of dictionaries."""
    record_dict = {
        'network': 'OX',
        'station': 'ABCD',
        'location': '00',
        'channel': 'HHZ',
        'starttime': '2010-01-10T08:23:45.019538Z',
        'rate': 200,
        'nsamp': 100,
        'data': [i for i in range(100)]
    }
    miniseed.import_record(record_dict)
    rec_list = miniseed.export_records()
    assert isinstance(rec_list, list), "Exported records are not a list"
    assert len(rec_list) > 0, "Exported records list is empty"
    assert rec_list[0]['network'] == 'OX', "Record data mismatch"
    assert rec_list[0]['station'] == 'ABCD', "Record data mismatch"
    assert rec_list[0]['location'] == '00', "Record data mismatch"
    assert rec_list[0]['channel'] == 'HHZ', "Record data mismatch"
    assert rec_list[0]['starttime'] == '2010-01-10T08:23:45.019538Z', \
        "Record data mismatch"
    assert rec_list[0]['rate'] == 200, "Record data mismatch"
    assert rec_list[0]['nsamp'] == 100, "Record data mismatch"
    assert rec_list[0]['data'] == [i for i in range(100)], \
        "Record data mismatch"
