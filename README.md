# CIR · Construction Inspection Register

CIR is a Windows desktop application for construction inspection teams. It keeps prescriptions, remarks, deadlines, attachments, audit history, and contractor exchange packages in a local/server-folder workflow without requiring a separate web server.

The primary storage is SQLite. Excel is generated as a secondary export for Power BI, Power Query, and external reporting.

## Features

- Desktop GUI built with Python `tkinter/ttk`.
- SQLite storage per work profile in a shared server folder.
- Roles for construction control specialist, supervisor, and substitute user.
- Supervisor mode reads SQLite profiles directly.
- Profile locking to reduce accidental simultaneous editing conflicts.
- Audit log for create/update/delete/import actions.
- Excel export with objects, prescriptions, remarks, imported packages, and audit log sheets.
- Remark and prescription attachment folders.
- Contractor exchange through `.cirx` packages suitable for email transfer.
- Demo server for testing and demonstration.

## Repository Contents

```text
cir_app/                     application source code
cir_app/assets/              application icon
scripts/                     smoke test, demo generation, EXE build
generated_demo_server_data/  canonical demo server data
main.py                      application entry point
requirements.txt             runtime dependency list
README.md                    project documentation
```

Generated builds, local configuration, live work databases, attachments, and exchange packages are intentionally ignored by Git.

## Requirements

- Windows 10/11
- Python 3.11 or newer

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

## Run From Source

```powershell
python main.py
```

On first launch, CIR asks for:

- server folder, where profiles and SQLite databases are stored;
- user name;
- user code;
- role.

The selected server folder is the application's data repository. Do not point it at the Git source repository unless you intentionally want test data there.

## Server Folder Structure

```text
server_data/
  profiles/
    ivanov/
      cir.sqlite
      export.xlsx
      profile.json
      edit.lock
      attachments/
```

`cir.sqlite` is the source of truth. `export.xlsx` is recreated after data changes and is intended for Power BI/Power Query integration.

## Demo Data

The repository includes one canonical demo server:

```text
generated_demo_server_data/
```

In the application settings, the "Демо-данные" button adds demo objects, prescriptions, and remarks to the currently selected server folder/profile. The button is disabled until a server folder is specified and cannot be used in supervisor/read-only mode.

If the current profile already contains data, CIR shows a large warning before adding demo data because repeated use will add extra demo projects and modify the selected data repository.

To regenerate the canonical demo server:

```powershell
python -B scripts\generate_demo_profiles.py --force
```

Without `--force`, the script refuses to overwrite an existing demo server and does not create extra numbered folders.

## Contractor Exchange

CIR supports file-based exchange with subcontractors:

1. The office exports an assignment package as `.cirx`.
2. The subcontractor imports the package into their local CIR instance.
3. The subcontractor updates remarks and attaches remark photos.
4. The subcontractor exports a response `.cirx` package.
5. The office imports the response package back into the project.

The package format is intended for email transfer. Attachments are included primarily for remarks, where photo evidence matters most.

## Smoke Test

Run a non-GUI verification:

```powershell
python -B scripts\smoke_test.py
```

The smoke test checks SQLite storage, Excel export, audit log, locking behavior, contractor exchange, duplicate package protection, and attachment import.

## Build EXE

Build a single developer EXE:

```powershell
python -B scripts\build_exe.py --clean
```

Build release artifacts:

```powershell
python -B scripts\build_release.py --version v3 --clean
```

The release build writes:

```text
dist/v3/CIR-v3-portable/
dist/v3/CIR-v3-portable.zip
dist/v3/CIR-v3-full.exe
dist/v3/CIR-v3-Setup.exe
```

Publish ready-made ZIP/EXE builds through GitHub Releases rather than committing `dist/` to the repository.

## GitHub Hygiene

Commit source code, scripts, documentation, and the canonical demo server only.

Do not commit:

- `build/`
- `dist/`
- `.cir_app_config.json`
- live `server_data/`
- real `profiles/`
- production `cir.sqlite`
- attachments from real projects
- `.cirx` exchange packages
- lock and SQLite WAL/SHM files

For a public repository, review demo data and remove any real project names, contractor names, comments, or photos before publishing.

## License

MIT License. See [LICENSE](LICENSE).
