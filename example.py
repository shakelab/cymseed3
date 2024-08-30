from cymseed3 import libmseed

# Initialise a Miniseed object
ms = libmseed.MiniSeed()

record_dict = {
    'network' : 'OX',
    'station' : 'ABCD',
    'location' : '00',
    'channel' : 'HHZ',
    'starttime' : '2010-01-10T08:23:45.019538Z',
    'rate' : 200,
    'nsamp' : 100,
    'data' : [i for i in range(100)]
}

ms.import_record(record_dict)

# Write data into binary buffer
byte_buffer = ms.write(msformat=2, reclen=512, encoding=11)

# Write bytes to file
with open("my_file.mseed", "wb") as fid:
    fid.write(byte_buffer)



# Read the file
with open("my_file.mseed", 'rb') as fid:
    byte_buffer = fid.read()

# Read the buffer
ms.read(byte_buffer, verbose=1)

# Export data to a list of dictionaries.
rec_list = ms.export_records()

print(rec_list[0])