# PDF.js browser compatibility

The 1.0.1 standard PDF.js 6.3.289 worker uses `Map.prototype.getOrInsertComputed` in its range request bookkeeping. On the installed Microsoft Edge 139.0.3405.125, the document failed with `this._requestsByChunk.getOrInsertComputed is not a function`. Both original and translated PDFs returned PDF responses and the self-hosted worker loaded; the generic UI error incorrectly suggested several unrelated causes.

Use PDF.js's matching `legacy/build/pdf.mjs` and `legacy/build/pdf.worker.mjs`, which include the upstream compatibility implementation. This is the same PDF.js version and file endpoint, with the same CSP and worker isolation; do not downgrade security settings or replace user files. Add installed Edge to browser acceptance rather than relying exclusively on Playwright's newer bundled Chromium.

The synthetic Edge regression failed before the change and passed afterward, checking actual text layers and visible page rendering. The same candidate assets rendered the existing AutoSci original and bilingual translation (22 pages each) in Edge using production file endpoints. Production files were not changed and no model/translation/parse task was created. Candidate asset interception was confined to the acceptance browser, not a production deployment. Private before/after diagnostics and screenshots remain in ignored development evidence.
