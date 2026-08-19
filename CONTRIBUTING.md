# Contributing to ODeR

Thanks for helping improve ODeR. Small, focused changes are the easiest to review.

## Development setup

1. Fork and clone the repository.
2. Create a virtual environment.
3. Install `requirements.txt`.
4. Create a branch from `main`.
5. Keep runtime files out of the repository; `data/` is intentionally ignored.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Before opening a pull request

Run the same checks used by continuous integration:

```powershell
python -m compileall -q core gui main.py
python -m unittest discover -s tests -v
```

Please also check the affected interface manually when changing PySide6 widgets or styling. Avoid committing profiles, cached indexes, URLs from private directories, downloaded files, `.oder` exports, build output, or credentials.

## Pull requests

- Explain the user-visible problem and the chosen fix.
- Keep unrelated formatting or refactoring out of the change.
- Add or update tests for core behavior where practical.
- Update `CHANGELOG.md` for user-visible changes.
- Include a screenshot for meaningful interface changes.

By submitting a contribution, you confirm that you have the right to provide it and agree that it may be distributed under the project's MIT License.
