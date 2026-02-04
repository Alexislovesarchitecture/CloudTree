# CloudTree

CloudTree is a small snapshot tool that generates a filtered tree TXT and a filtered TSV file index for any chosen folder. It never modifies, moves, deletes, or renames source files.

## Usage

Use the python.org Python 3.14 build for Tkinter (not Homebrew Python).

GUI app:

```
python3.14 cloud_tree_gui.py
```

CLI:

```
python3.14 cloud_tree.py --root "/path/to/folder" --label mylabel
```

CLI examples:

```
python3.14 cloud_tree.py \
  --root "/path/to/folder" \
  --label mylabel \
  --exclude-exts "obj, fbx, stl" \
  --exclude-words "draft, backup"
```

Optional output directory:

```
python3.14 cloud_tree.py --root "/path/to/folder" --label mylabel --out "/path/to/output"
```

## Output

Files are written to the output directory with names:

- `<label>_tree_FILTERED_<TS>.txt`
- `<label>_files_index_FILTERED_<TS>.tsv`

`TS` is in `YYYYMMDD_HHMMSS` format.

Default output directory (if `--out` is not provided):

```
../snapshots/cloud_tree
```

This is resolved based on whether the app is packaged (see Default Output Location).

## Default Output Location

- Running from source: `/Users/alexislovesarchitecture/Desktop/CodexWorkspace/snapshots/cloud_tree`
- Running as packaged app: `~/Documents/CloudTree/snapshots/cloud_tree`

The GUI remembers the last output folder and settings in:

```
~/Library/Application Support/CloudTree/config.json
```

## Filters

Excluded file extensions (case-insensitive, editable in the GUI):

- udsmesh, uds, obj, fbx, stl, gltf, glb, ply, las, laz, e57, rcp, rcs
- .DS_Store

Excluded directories anywhere in the path (case-insensitive, editable in the GUI):

- `mesh`, `meshes`
- names that start with `pointcloud` or `point cloud`

Exclude words (case-insensitive, editable in the GUI):

- Any word or phrase you enter will remove files or folders whose names contain it.
- Extensions field accepts comma/space separation. Words field accepts comma or line separation.
- The GUI includes an Advanced Filters dialog with checkbox presets for common extensions.
- Keyword filtering is case-insensitive and matches file/folder names.

## Notes

- The tree TXT uses the system `tree` command if available; if you set word filters it switches to a Python tree renderer for accurate filtering.
- The TSV lists: `full_path<TAB>size_bytes<TAB>mtime_epoch`.
- Paths are sanitized to replace tabs and newlines with spaces in the TSV.
- If you see permission issues reading a folder, grant Full Disk Access to Terminal/Python.
- If the packaged app can’t read a folder, grant Full Disk Access to CloudTree.app.

## Test

Run the GUI and select the CloudTree folder itself (small test) and confirm outputs appear in `snapshots/cloud_tree`.
