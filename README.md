# DesatNerd

**Oxygen desaturation and hypoxic burden analysis for polysomnography and pulse oximetry.**

DesatNerd is part of the SleepNerd suite. It reads overnight SpO2 recordings from PSG and standalone oximeters, removes artefact, detects desaturation events and calculates both conventional and newer hypoxic burden metrics. It runs as a desktop app (PySide6) or headless from the command line for batch processing.

Author: Dr Brett Duce, Metro South Sleep Service, Princess Alexandra Hospital, Brisbane, Australia.

> **Research use.** DesatNerd is not a registered medical device. Its outputs are intended for research and to support, not replace, review by qualified sleep scientists and physicians.

---

## What it calculates

| Group | Metrics |
|---|---|
| Conventional | ODI 3%, ODI 4%, T90 / T88 / T85 / T80 (minutes and % of valid time), baseline, mean and minimum SpO2 |
| Hypoxic burden | Azarbarzin hypoxic burden (%min/h), REDTA (%h and %min/h), Kulkas desaturation, recovery and total severity (%min/h) |
| Event morphology | Duration, fall and recovery duration, depth, fall and recovery slopes (%/s), and fall and recovery limb areas for every event |
| Analysis windows | Total sleep time (TST), sleep period time (SPT) or total recording time (TRT) |

When a Compumedics Profusion XML file sits beside the EDF (`<study>.edf.XML`, `<study>_Profusion.xml` or `<study>_events.xml`), DesatNerd uses its sleep staging and scored respiratory events for the TST/SPT windows and for the event-linked burden metrics.

## Supported inputs

- **EDF / EDF+ / BDF**: Compumedics, Nox, REMlogic/Embla and generic EDF. Uses pyEDFlib when installed, otherwise a built-in pure-Python EDF reader.
- **Nonin**: nVISION / WristOx2 ASCII exports (`.asc`, `.csv`, `.txt`, `.dat`)
- **Nellcor**: N-600x / OxiMax serial ASCII trend output
- **Masimo**: Radical-7, Rad-97 and Rad-5 tabular and TrendCom exports
- **Generic CSV/TSV** with an identifiable SpO2 column

The full method, thresholds and references are in [`assets/DesatNerd Clinical & Technical User Guide.pdf`](assets/DesatNerd%20Clinical%20%26%20Technical%20User%20Guide.pdf).

## Installing

### Windows installer

Download the latest `DesatNerd_Setup_vX.Y.Z.exe` from the [Releases](https://github.com/BrettDuce/desat-nerd/releases) page and run it. No Python installation is needed.

### From source

Requires Python 3.10 or later.

```bash
git clone https://github.com/BrettDuce/desat-nerd.git
cd desat-nerd
python -m venv .venv
.venv\Scripts\activate          # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
```

## Usage

### Desktop app

```bash
python main.py
```

Pick a single recording or a batch folder, choose a 3% or 4% threshold and an output folder, then select **Start Analysis**. You can step through the SpO2 trace, click events in the morphology table to jump to them, and review the summary; results are saved as CSV files in the output folder.

### Command line (batch)

```bash
python main.py --cli --input <file_or_folder> --output <results_folder> [--threshold 3.0]
```

| Option | Description |
|---|---|
| `--cli` | Run without the GUI |
| `-i`, `--input` | A single recording, or a folder of recordings |
| `-o`, `--output` | Folder for results (default: `./oximetry_results`) |
| `-t`, `--threshold` | Desaturation threshold in % (default 3.0) |

For each study the CLI writes:

- `<study>_oximetry_summary.csv`: one row of summary metrics
- `<study>_desaturation_events.csv`: one row per desaturation event
- `batch_oximetry_hypoxic_burden_summary.csv`: a running master table that every analysed study is appended to

> **Patient data:** result files can contain study identifiers. The repository's `.gitignore` excludes recordings and result CSVs, so keep clinical data out of the project folder or check `git status` before committing.

## Running the tests

The test suite builds synthetic EDF, Nonin, Nellcor and Masimo recordings with known desaturations and checks parsing, detection and export:

```bash
python -m unittest -v test_oximetry
```

Tests run automatically on GitHub for every push (see `.github/workflows/tests.yml`).

## Building the Windows executable and installer

```bash
pip install -r requirements-dev.txt
pyinstaller DesatNerd.spec
```

This produces `dist/DesatNerd.exe`. To build the installer, open `DesatNerd.iss` in [Inno Setup 6](https://jrsoftware.org/isinfo.php) and compile; the setup file is written to `installer_output/`. Build outputs are not committed to the repository. Attach the installer to a GitHub Release instead.

## Project layout

| File | Purpose |
|---|---|
| `main.py` | Entry point: launches the GUI or the headless CLI |
| `gui.py` | PySide6 interface: trace viewer, event table, summary and export |
| `worker.py` | Background thread that runs analyses without freezing the GUI |
| `parsers.py` | EDF, Profusion XML and oximeter text-file readers |
| `oximetry_engine.py` | Artefact detection, desaturation detection and all metric calculations |
| `exporter.py` | CSV export of summaries, event tables and the batch master table |
| `config.py` | App constants, channel/column aliases, stage colours and UI styling |
| `test_oximetry.py` | Validation test suite using synthetic recordings |
| `DesatNerd.spec` | PyInstaller build configuration |
| `DesatNerd.iss` | Inno Setup installer script |
| `assets/` | App icon and the clinical & technical user guide |

## Key references

- Azarbarzin A, et al. The hypoxic burden of sleep apnoea predicts cardiovascular disease-related mortality. *European Heart Journal* 2019.
- de Chazal P, et al. Respiratory event desaturation transient area (REDTA). *Sleep* 2021.
- Kulkas A, et al. Novel parameters indicating severity of desaturation and recovery. *Medical & Biological Engineering & Computing* 2013.
