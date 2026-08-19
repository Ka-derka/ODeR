# Third-party notices

ODeR is licensed under the MIT License. That license applies only to ODeR's original source code and assets. Third-party software retains its own copyright and license terms.

The versions actually installed or bundled may vary because `requirements.txt` specifies compatible version ranges. Before publishing a binary release, verify the resolved dependency versions and preserve the license files supplied with those exact distributions.

## Runtime dependencies

| Component | Purpose | License | Upstream license information |
| --- | --- | --- | --- |
| PySide6, PySide6 Essentials, PySide6 Addons and Shiboken6 | Python bindings and support libraries for Qt | LGPL-3.0/GPL-3.0 or a Qt commercial license, depending on the distribution and use | [Qt for Python](https://doc.qt.io/qtforpython-6/) and [license details](https://doc.qt.io/qtforpython-6/licenses.html) |
| Qt 6 libraries used by PySide6 | Desktop interface framework | LGPL-3.0/GPL-3.0 or a Qt commercial license; individual Qt modules may have additional terms | [Qt licensing](https://doc.qt.io/qt-6/licensing.html) |
| Requests | HTTP client | Apache-2.0 | [Requests LICENSE](https://github.com/psf/requests/blob/main/LICENSE) |
| Charset Normalizer | Response character-set detection used by Requests | MIT | [Charset Normalizer LICENSE](https://github.com/jawah/charset_normalizer/blob/master/LICENSE) |
| idna | Internationalized domain-name handling used by Requests | BSD-3-Clause | [idna LICENSE](https://github.com/kjd/idna/blob/master/LICENSE.md) |
| urllib3 | HTTP transport used by Requests | MIT | [urllib3 LICENSE](https://github.com/urllib3/urllib3/blob/main/LICENSE.txt) |
| certifi and its CA certificate bundle | Certificate authorities used for TLS verification | MPL-2.0 for the Mozilla-derived certificate bundle | [certifi LICENSE](https://github.com/certifi/python-certifi/blob/master/LICENSE) |

Python and its standard library may also be included in packaged application builds. Python is distributed under the [Python Software Foundation License](https://docs.python.org/3/license.html), along with the additional notices listed there.

## Build and installer tooling

PyInstaller is used to create the Windows executable. PyInstaller is licensed under GPL-2.0-or-later with a bootloader exception; its runtime hooks have separate Apache-2.0 terms, and some components are alternatively available under MIT terms. See [PyInstaller's COPYING file](https://github.com/pyinstaller/pyinstaller/blob/develop/COPYING.txt). The bootloader exception permits distribution of the generated executable without applying the GPL to ODeR solely because PyInstaller was used.

Inno Setup may optionally be used to create the Windows installer. It is a build-time tool and is not included in this repository. Review the license accompanying the installed Inno Setup version before distributing installers produced with it.

## Binary distribution responsibilities

The repository does not vendor third-party wheels or their complete license texts. A person distributing an ODeR executable or installer should:

1. Determine the exact packages, Qt modules, libraries, runtime hooks and other files included in that build.
2. Include the corresponding copyright notices and complete license texts supplied with those versions.
3. Comply with the applicable PySide6 and Qt LGPL, GPL or commercial-license requirements; the MIT License for ODeR does not replace them.
4. Keep this notice with the distribution and update it whenever dependencies or packaging behavior change.

This file is an attribution and compliance aid, not a replacement for the complete license text of any dependency and not legal advice.
