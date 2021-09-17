# TODO

On write:

- set up temporary directory:
  - write to central directory (possible on disk for low memory usage)
  - write to sqlite DB on disk
- stream repo files directly to zip file (with compression)
- stream sqlite DB to zip file (compressed?)
- add "metadata" to zipfile
- add central directory to zipfile
- close zip file
- delete temporary director + files

On read:
