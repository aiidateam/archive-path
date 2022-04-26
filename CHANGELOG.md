# Change Log

## v0.4.0 - 2022-04-26

- ⬆️ UPGRADE: Drop Python 3.7 support
- 👌 IMPROVE: Allow `file_size` to be passed to `ZipPath.open`.
  This is used by `zipfile.open`, to compute if the `ZIP64` extension is required when writing

## v0.3.6 - 2021-11-23

✨ NEW: Allow parsing `ZipPath` -> `ZipPath.putfile` (propagates compression type+level and comment)

## v0.3.4 - 2021-09-30

✨ NEW: Add `TarPath.parts` and `ZipPath.parts`

## v0.3.2 - 2021-09-30

✨ NEW: Add `ZipPath.mkdir` method.

## v0.3.1 - 2021-09-22

✨ NEW: `open_file_in_zip`/`open_file_in_tar` contexts

## v0.3.0 - 2021-09-18

👌 IMPROVE: Introduce more zip read/write options

🧪 TESTS: drop python 3.6

## v0.2.1 - 2020-11-09

🐛 FIX: Ensure base directory always created in `extract_tree`

## v0.2.0 - 2020-11-09

✨ NEW: Add `glob` method

✨ NEW: Add `extract_tree` method

## v0.1.1 - 2020-11-08

✨ Initial PyPi release
