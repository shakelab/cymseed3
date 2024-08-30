# cymseed3

 `cymseed3` is a Python package for reading and writing MiniSEED files using the `libmseed` library. This package provides a simple and efficient interface for handling seismic data in the MiniSEED format, making it easy to import, export, and manipulate seismic records.

 ## Features

 - **Read MiniSEED Files**: Import data from MiniSEED files into Python objects for easy manipulation.
 - **Write MiniSEED Files**: Export seismic data to MiniSEED format files.
 - **Data Export**: Convert MiniSEED data to Python dictionaries for integration with other tools and workflows.
 - **Support for Multiple Data Encodings**: Handle various data encodings supported by the `libmseed` library.

 ## Installation

 ### Prerequisites

 Ensure you have Python 3.6 or higher installed. Additionally, you'll need `setuptools`, `wheel`, and `cython` for building the package:

 ```bash
 pip install setuptools wheel cython
 ```

 ### Installing cymseed3

 You can install `cymseed3` directly from the source using pip. Clone the repository and run the installation command:

 ```bash
 git clone https://github.com/your-username/cymseed3.git
 cd cymseed3
 pip install .
 ```

 Replace `your-username` with your GitHub username.

 ## Usage

 Here’s an example of how to use `cymseed3` to create, write, read, and export MiniSEED data:

 ```python
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
 ```

 ### Example Output

 Running the example above will print the first record from the MiniSEED file as a Python dictionary, showing details like network, station, channel, and the data itself.

 ## Contributing

 Contributions are welcome! If you would like to contribute to this project, please fork the repository and submit a pull request. You can also report bugs or suggest new features by opening an issue.

 ### How to Contribute

 1. Fork the repository.
 2. Create a new branch (`git checkout -b feature/YourFeature`).
 3. Commit your changes (`git commit -am 'Add a new feature'`).
 4. Push to the branch (`git push origin feature/YourFeature`).
 5. Open a Pull Request.

 ## License

 This project is licensed under the GNU General Public License v3.0 (GPL-3.0). You are free to use, modify, and distribute this software under the terms of the GPL-3.0 license. See the [LICENSE](LICENSE) file for more details.

 ## Acknowledgements

 `cymseed3` uses the `libmseed` library for handling MiniSEED files. Special thanks to the contributors of `libmseed` for providing a robust library for seismic data processing.

 ## Support

 If you have any questions or need help, please open an issue on the GitHub repository or contact us via email.

 ## Contact

 - Author: Valerio Poggi
 - Email: vpoggi@ogs.it
 - GitHub: [your-username](https://github.com/your-username)
