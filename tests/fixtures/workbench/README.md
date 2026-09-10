# Synthetic reader fixtures

All text and layout are authored for PaperPilot tests (2026-09-10), not real papers. Test text/generator are provided under the repository license. No production data or model output is included. `translated.pdf` is a synthetic alternate document, not a BabelDOC result.

`generate.py` uses ReportLab (BSD, build-time only), invariant output, standard Helvetica (no font program embedded), an embedded subset of AR PL SungtiL GB (`/usr/share/fonts/truetype/arphic-gbsn00lp/gbsn00lp.ttf`, Debian fonts-arphic-gbsn00lp; Arphic Public License reproduced in FONT-LICENSE.txt), and nonembedded STSong-Light CID text to exercise PDF.js Adobe CMaps. PDF.js distributed font/CMap licenses are shipped with its assets.

- original.pdf: 100 pages, second page rotated 90 degrees, English and Chinese text, uncompressed streams to exercise Range.
- translated.pdf: two synthetic alternate pages, including a rotated page.
- encrypted.pdf: one password-protected page, synthetic password `synthetic-password`.

Regenerate with `python generate.py` in an environment with ReportLab and the documented Arphic font. Runtime/Web dependencies do not include ReportLab or server PDF parsers. SHA256.json records exact committed fixture bytes. Corrupt/missing fixtures are constructed only in temporary test directories.
