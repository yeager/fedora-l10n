# Fedora Translation Status

A GTK4/Adwaita application that shows the translation progress of Fedora projects via the [Weblate API](https://translate.fedoraproject.org/).

![License](https://img.shields.io/badge/license-GPL--3.0-blue)

## Features

- Lists all 127 Fedora translation projects
- Per-language translation statistics (translated/fuzzy/untranslated %)
- Auto-detects system language with manual override
- Color-coded progress bars (heatmap style)
- Drill-down: click a project to see component-level stats
- Search and filter projects
- Direct links to Weblate for translating
- Local cache (~/.cache/fedora-l10n/, 1h TTL)
- Rate limiting with exponential backoff

## Installation

### From Debian repository

```bash
sudo apt install fedora-l10n
```

### From RPM repository

```bash
sudo dnf install fedora-l10n
```

### From source

```bash
pip install .
fedora-l10n
```

## Requirements

- Python 3.10+
- GTK 4
- libadwaita
- PyGObject

## License

GPL-3.0-or-later — see [LICENSE](LICENSE)

## Author

Daniel Nylander <daniel@danielnylander.se>
